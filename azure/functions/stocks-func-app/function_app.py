import os, json, sys, tempfile, subprocess, shutil, logging, pathlib, importlib.util
import azure.functions as func
from openai import AzureOpenAI

app = func.FunctionApp()

# ---------- App Settings ----------
# If your main file or helpers live in a subfolder, set WB4U_ENTRY accordingly (e.g., "src/wb4u_main.py").
WB4U_ENTRY = os.getenv("WB4U_ENTRY", "wb4u_main.py")

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

def _load_module_from_path(module_name: str, file_path: str):
    """
    Dynamically import a module from an absolute file path (no need for packages).
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        raise ImportError(f"Could not load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod

def _run_local_universe() -> list[str]:
    """
    Execute your local wb4u_main.py (shipped with this Function App).
    We try to import and call a function if available; otherwise we run it as a script and parse stdout.
    Accepted function names (first one found is used):
      - get_universe()
      - run_universe()
      - build_universe()
      - main()
    If no function is found, we execute the script and expect it to PRINT either:
      - a JSON array  e.g., ["AAPL","MSFT"]
      - a Python list e.g., ['AAPL','MSFT']
    """
    wwwroot = pathlib.Path(__file__).parent  # /site/wwwroot
    script_path = (wwwroot / WB4U_ENTRY).resolve()

    if not script_path.exists():
        raise FileNotFoundError(f"WB4U entry not found at {script_path}")

    # Try to import and call
    try:
        mod = _load_module_from_path("wb4u_main_dynamic", str(script_path))
        for fn_name in ("get_universe", "run_universe", "build_universe", "main"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                tickers = fn()
                if not isinstance(tickers, (list, tuple)):
                    raise TypeError(f"{fn_name}() must return a list/tuple of tickers")
                cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
                if not cleaned:
                    raise ValueError("Universe function returned an empty list")
                return cleaned
    except Exception as e:
        # Fall back to executing as a script that prints the list
        logging.info(f"Import path failed or no function found; falling back to subprocess run. Reason: {e}")

    # Fallback: run as a script and parse stdout
    run = subprocess.run([sys.executable, str(script_path)], check=True, capture_output=True, text=True)
    out = run.stdout.strip()
    try:
        tickers = json.loads(out)
    except json.JSONDecodeError:
        # accept Python list literal
        tickers = eval(out, {"__builtins__": {}}, {})

    if not isinstance(tickers, (list, tuple)):
        raise ValueError("Entry script must print a list/JSON array of tickers")

    cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
    if not cleaned:
        raise ValueError("No tickers produced by entry script")
    return cleaned

def _make_prompt(tickers, strategy: str, horizon_text: str):
    """
    horizon_text is a free-form string like '3 years', '8 months', '30 days'.
    """
    system = (
        "You are an equity analyst. Return ONLY JSON. "
        "Rank the provided tickers for the chosen strategy with concise reasoning."
    )
    user = {
        "strategy": strategy,
        "horizon": horizon_text,
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


# ---------- Function 0: Health ----------
@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"ok": true, "msg": "host running"}', mimetype="application/json")


# ---------- Function 1: Universe (run local wb4u_main.py) ----------
@app.function_name(name="universe")
@app.route(route="universe", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def get_universe(req: func.HttpRequest) -> func.HttpResponse:
    try:
        tickers = _run_local_universe()
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


# ---------- Function 2: Rank (Azure OpenAI) ----------
@app.function_name(name="rank")
@app.route(route="rank", methods=["POST", "GET"], auth_level=func.AuthLevel.ANONYMOUS)
def rank(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = _parse_json_body(req)

        # tickers from body or query (?tickers=AAPL,MSFT)
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

        strategy = (body.get("strategy") or req.params.get("strategy") or "long_term").strip()

        # Free-form horizon string (back-compat with horizon_years)
        horizon_text = body.get("horizon") or req.params.get("horizon")
        if not horizon_text:
            hy = body.get("horizon_years") or req.params.get("horizon_years")
            if hy is not None:
                try:
                    horizon_text = f"{int(hy)} years"
                except Exception:
                    horizon_text = f"{str(hy).strip()} years"
        if not horizon_text:
            horizon_text = "3 years"

        result = _score_with_azure_openai(tickers, strategy, horizon_text)
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