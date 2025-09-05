import os, json, sys, tempfile, subprocess, shutil, logging
import azure.functions as func
from openai import AzureOpenAI

app = func.FunctionApp()

# ---------- App Settings ----------
GITHUB_REPO   = os.getenv("GITHUB_REPO", "github.com/YourOrg/wb4u_stock_analysis.git")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
WB4U_ENTRY    = os.getenv("WB4U_ENTRY", "wb4u_main.py")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")  # fine-grained PAT, repo read, contents:read

AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# ---------- Helpers ----------
def _parse_json_body(req: func.HttpRequest) -> dict:
    try:
        return req.get_json()
    except ValueError:
        return {}

def _clone_and_run() -> list[str]:
    """Clone private repo and execute wb4u_main.py; return a normalized list of tickers."""
    tmp = tempfile.mkdtemp()
    try:
        if not GITHUB_TOKEN:
            raise RuntimeError("GITHUB_TOKEN not set")
        repo_url = f"https://{GITHUB_TOKEN}@{GITHUB_REPO}"
        subprocess.check_call(["git", "clone", "--depth", "1", "--branch", GITHUB_BRANCH, repo_url, tmp])

        entry = os.path.join(tmp, WB4U_ENTRY)
        if not os.path.exists(entry):
            raise FileNotFoundError(f"Missing entry script: {entry}")

        run = subprocess.run([sys.executable, entry], check=True, capture_output=True, text=True)
        out = run.stdout.strip()

        # Accept JSON array or Python list literal
        try:
            tickers = json.loads(out)
        except json.JSONDecodeError:
            tickers = eval(out, {"__builtins__": {}}, {})

        if not isinstance(tickers, (list, tuple)):
            raise ValueError("wb4u_main.py must print a list/JSON array")

        cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
        if not cleaned:
            raise ValueError("No tickers produced by wb4u_main.py")
        return cleaned
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _make_prompt(tickers, strategy: str, horizon_text: str):
    """
    Build system/user messages. horizon_text is a free-form string like:
    '3 years', '8 months', '30 days'. We pass it directly to the model.
    """
    system = (
        "You are an equity analyst. Return ONLY JSON. "
        "Rank the provided tickers for the chosen strategy with concise reasoning."
    )
    user = {
        "strategy": strategy,
        "horizon": horizon_text,        # <- free-form string
        "tickers": tickers,
        "output_format": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string"},
                "horizon": {"type": "string"},
                "ranked": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "score": {"type": "number"},
                            "thesis": {"type": "string"},
                            "risks": {"type": "string"},
                            "suggested_action": {"type": "string"}
                        },
                        "required": ["ticker", "score", "thesis"]
                    }
                },
                "notes": {"type": "string"}
            },
            "required": ["strategy", "horizon", "ranked"]
        },
        "instructions": {
            "long_term": f"Evaluate long-term durability, compounding and drawdown resilience for the horizon: {horizon_text}.",
            "leaps": f"Evaluate suitability for LEAP calls over the horizon '{horizon_text}': catalysts, trend quality, IV + liquidity, macro sensitivity.",
            "swing": f"Evaluate 1–8 week setups relative to the stated horizon '{horizon_text}' with emphasis on momentum and risk control."
        }.get(strategy, f"Evaluate strategy: {strategy} over horizon '{horizon_text}'.")
    }
    return system, user

def _score_with_azure_openai(tickers, strategy: str, horizon_text: str) -> dict:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        raise RuntimeError("Azure OpenAI settings missing (endpoint/key/deployment).")

    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    system, user = _make_prompt(tickers, strategy, horizon_text)
    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)

# ---------- Function 1: Universe (run wb4u_main.py) ----------
@app.function_name(name="universe")
@app.route(route="universe", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def get_universe(req: func.HttpRequest) -> func.HttpResponse:
    try:
        tickers = _clone_and_run()
        return func.HttpResponse(
            json.dumps({"ok": True, "tickers": tickers}, ensure_ascii=False),
            mimetype="application/json"
        )
    except Exception as e:
        logging.exception("universe error")
        return func.HttpResponse(
            json.dumps({"ok": False, "error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

# ---------- Function 2: Rank (call Azure OpenAI) ----------
@app.function_name(name="rank")
@app.route(route="rank", methods=["POST", "GET"], auth_level=func.AuthLevel.ANONYMOUS)
def rank(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = _parse_json_body(req)

        # Accept tickers from body or query (?tickers=AAPL,MSFT)
        tickers = body.get("tickers")
        if not tickers:
            qp = req.params.get("tickers")
            if qp:
                tickers = [t.strip().upper() for t in qp.split(",") if t.strip()]
        if not tickers:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "Provide 'tickers' as JSON array or comma-separated query param."}),
                status_code=400,
                mimetype="application/json"
            )
        tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]

        # Strategy (default long_term)
        strategy = (body.get("strategy") or req.params.get("strategy") or "long_term").strip()

        # NEW: Horizon is a free-form string; keep old 'horizon_years' for back-compat
        horizon_text = body.get("horizon") or req.params.get("horizon")
        if not horizon_text:
            # Back-compat: accept horizon_years and convert to "X years"
            hy = body.get("horizon_years") or req.params.get("horizon_years")
            if hy is not None:
                try:
                    horizon_text = f"{int(hy)} years"
                except Exception:
                    horizon_text = f"{str(hy).strip()} years"
        if not horizon_text:
            horizon_text = "3 years"

        result = _score_with_azure_openai(tickers, strategy, horizon_text)

        # Ensure horizon is present in top-level response for your UI
        return func.HttpResponse(
            json.dumps({"ok": True, "strategy": strategy, "horizon": horizon_text, "result": result}, ensure_ascii=False),
            mimetype="application/json"
        )
    except Exception as e:
        logging.exception("rank error")
        return func.HttpResponse(
            json.dumps({"ok": False, "error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )