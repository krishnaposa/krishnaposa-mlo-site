import os, json, sys, tempfile, subprocess, shutil, logging, pathlib
import azure.functions as func
from openai import AzureOpenAI

# NEW: pure-Python git client (no system git needed)
from dulwich import porcelain
from dulwich.client import HttpUnauthorized
from dulwich.errors import NotGitRepository

app = func.FunctionApp()

# ---------- App Settings ----------
# Accept any of:
#   "YourOrg/wb4u_stock_analysis"
#   "github.com/YourOrg/wb4u_stock_analysis.git"
#   "https://github.com/YourOrg/wb4u_stock_analysis.git"
GITHUB_REPO   = os.getenv("GITHUB_REPO", "YourOrg/wb4u_stock_analysis")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
WB4U_ENTRY    = os.getenv("WB4U_ENTRY", "wb4u_main.py")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")  # fine-grained PAT: repo:read

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

def _parse_owner_repo(repo_str: str) -> tuple[str, str]:
    s = repo_str.strip().replace("https://", "").replace("http://", "")
    if s.startswith("github.com/"):
        s = s[len("github.com/"):]
    if s.endswith(".git"):
        s = s[:-4]
    parts = s.split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    raise ValueError("GITHUB_REPO must be 'Owner/Repo' or a GitHub URL")

def _dulwich_clone_to(tmp_dir: str) -> str:
    """
    Clone the repo to tmp_dir using dulwich (pure Python, no system git).
    Supports PAT via https://<TOKEN>@github.com/owner/repo.git
    Checks out GITHUB_BRANCH.
    Returns repo_root path.
    """
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN not set")
    owner, repo = _parse_owner_repo(GITHUB_REPO)
    # Construct HTTPS URL with token
    url = f"https://{GITHUB_TOKEN}@github.com/{owner}/{repo}.git"

    try:
        porcelain.clone(url, tmp_dir, checkout=True, branch=GITHUB_BRANCH.encode("utf-8"), depth=1)
    except HttpUnauthorized:
        raise PermissionError("GitHub unauthorized. Check PAT scopes (needs repo read).")
    except Exception as e:
        raise RuntimeError(f"dulwich clone failed: {e}")

    # Ensure branch is checked out (some servers may need explicit reset)
    try:
        porcelain.reset(tmp_dir, f"origin/{GITHUB_BRANCH}".encode("utf-8"), hard=True)
    except Exception:
        pass

    return tmp_dir

def _find_entry(root_dir: str, relative_entry: str) -> str:
    candidate = os.path.join(root_dir, relative_entry)
    if os.path.exists(candidate):
        return candidate
    fname = os.path.basename(relative_entry)
    for p, _dirs, files in os.walk(root_dir):
        if fname in files:
            return os.path.join(p, fname)
    raise FileNotFoundError(f"Could not locate WB4U entry '{relative_entry}' in the repo")

def _run_entry(entry_path: str) -> list[str]:
    run = subprocess.run([sys.executable, entry_path], check=True, capture_output=True, text=True)
    out = run.stdout.strip()
    try:
        tickers = json.loads(out)
    except json.JSONDecodeError:
        tickers = eval(out, {"__builtins__": {}}, {})
    if not isinstance(tickers, (list, tuple)):
        raise ValueError("Entry script must print a list/JSON array of tickers")
    cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
    if not cleaned:
        raise ValueError("No tickers produced by entry script")
    return cleaned

def _clone_and_run() -> list[str]:
    """Clone via dulwich, find WB4U_ENTRY, run it, return normalized tickers."""
    tmp = tempfile.mkdtemp()
    try:
        repo_root = _dulwich_clone_to(tmp)
        entry = _find_entry(repo_root, WB4U_ENTRY)
        return _run_entry(entry)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _make_prompt(tickers, strategy: str, horizon_text: str):
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
            {"role":"system","content":system},
            {"role":"user","content":json.dumps(user)}
        ],
        temperature=0.3,
        response_format={"type":"json_object"}
    )
    return json.loads(resp.choices[0].message.content)

# ---------- Function 1: Universe ----------
@app.function_name(name="universe")
@app.route(route="universe", methods=["GET","POST"], auth_level=func.AuthLevel.ANONYMOUS)
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

# ---------- Function 2: Rank ----------
@app.function_name(name="rank")
@app.route(route="rank", methods=["POST","GET"], auth_level=func.AuthLevel.ANONYMOUS)
def rank(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = _parse_json_body(req)
        tickers = body.get("tickers")
        if not tickers:
            qp = req.params.get("tickers")
            if qp:
                tickers = [t.strip().upper() for t in qp.split(",") if t.strip()]
        if not tickers:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "Provide 'tickers' as JSON array or comma-separated query param."}),
                status_code=400, mimetype="application/json"
            )
        tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]

        strategy = (body.get("strategy") or req.params.get("strategy") or "long_term").strip()

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