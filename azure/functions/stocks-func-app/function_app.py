import os, json, sys, subprocess, logging, pathlib, importlib.util, datetime
import azure.functions as func
from openai import AzureOpenAI

# Blob SDK for cache
from azure.storage.blob import BlobServiceClient, ContentSettings

app = func.FunctionApp()

# ---------- Settings ----------
WB4U_ENTRY = os.getenv("WB4U_ENTRY", "wb4u_main.py")

# Cached universe location
UNIVERSE_CONTAINER = os.getenv("UNIVERSE_CONTAINER", "cache")
UNIVERSE_BLOB_NAME = os.getenv("UNIVERSE_BLOB_NAME", "universe.json")
UNIVERSE_TTL_MIN   = int(os.getenv("UNIVERSE_TTL_MIN", "720"))  # 12h for freshness checks in /api/universe

# Azure OpenAI
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# Blob client (uses AzureWebJobsStorage automatically)
_BLOB_SVC = BlobServiceClient.from_connection_string(os.getenv("AzureWebJobsStorage"))

# ---------- Helpers ----------
def _parse_json_body(req: func.HttpRequest) -> dict:
    try:
        return req.get_json()
    except ValueError:
        return {}

def _load_module_from_path(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        raise ImportError(f"Could not load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod

def _compute_universe_local() -> list[str]:
    """
    Runs your local wb4u_main.py to build the ticker list.
    Prefers a callable (get_universe/run_universe/build_universe/main), else runs as a script and parses stdout.
    """
    script_path = (pathlib.Path(__file__).parent / WB4U_ENTRY).resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"WB4U entry not found at {script_path}")

    # Try to import and call
    try:
        mod = _load_module_from_path("wb4u_main_dynamic", str(script_path))
        for fn_name in ("get_universe", "run_universe", "build_universe", "main"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                tickers = fn()
                break
        else:
            raise AttributeError("No exported universe function found; falling back to script exec")
    except Exception as e:
        logging.info(f"[universe] Import/call path not used ({e}); executing script.")
        run = subprocess.run([sys.executable, str(script_path)], check=True, capture_output=True, text=True)
        out = run.stdout.strip()
        try:
            tickers = json.loads(out)
        except json.JSONDecodeError:
            tickers = eval(out, {"__builtins__": {}}, {})

    if not isinstance(tickers, (list, tuple)):
        raise ValueError("wb4u_main must return/print a list/JSON array of tickers")

    cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
    if not cleaned:
        raise ValueError("Universe computation returned an empty list")
    return cleaned

def _blob_container():
    cont = _BLOB_SVC.get_container_client(UNIVERSE_CONTAINER)
    try:
        cont.create_container()  # idempotent
    except Exception:
        pass
    return cont

def _write_universe_blob(tickers: list[str]) -> None:
    cont = _blob_container()
    payload = {
        "ok": True,
        "tickers": tickers,
        "updated_utc": datetime.datetime.utcnow().isoformat() + "Z"
    }
    cont.upload_blob(
        UNIVERSE_BLOB_NAME,
        data=json.dumps(payload).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json")
    )

def _read_universe_blob() -> dict | None:
    cont = _blob_container()
    try:
        blob = cont.get_blob_client(UNIVERSE_BLOB_NAME)
        data = blob.download_blob().readall()
        return json.loads(data)
    except Exception:
        return None

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
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)

# ---------- Timer Trigger: refresh universe cache ----------
# Every 6 hours (CRON: {sec} {min} {hour} {day} {month} {day-of-week})
@app.schedule(schedule="0 0 */6 * * *", arg_name="myTimer", run_on_startup=True, use_monitor=True)
def refresh_universe(myTimer: func.TimerRequest) -> None:
    """
    Precompute and cache the universe on a cadence so HTTP is fast.
    run_on_startup=True warms the cache right after deployment.
    """
    try:
        tickers = _compute_universe_local()
        _write_universe_blob(tickers)
        logging.info(f"[refresh_universe] Cached {len(tickers)} tickers at {UNIVERSE_CONTAINER}/{UNIVERSE_BLOB_NAME}")
    except Exception as e:
        logging.exception(f"[refresh_universe] Failed: {e}")

# ---------- HTTP: health ----------
@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"ok": true}', mimetype="application/json")

# ---------- HTTP: universe (reads the cache) ----------
@app.function_name(name="universe")
@app.route(route="universe", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_universe(req: func.HttpRequest) -> func.HttpResponse:
    try:
        cached = _read_universe_blob()
        if not cached:
            # If cache is empty (first minute after deploy), compute once synchronously as a fallback
            tickers = _compute_universe_local()
            _write_universe_blob(tickers)
            cached = {"ok": True, "tickers": tickers, "updated_utc": datetime.datetime.utcnow().isoformat() + "Z"}
        else:
            # optional TTL warning flag
            try:
                ts = datetime.datetime.fromisoformat(cached.get("updated_utc","").replace("Z",""))
                age_min = (datetime.datetime.utcnow() - ts).total_seconds() / 60.0
                cached["stale"] = age_min > UNIVERSE_TTL_MIN
            except Exception:
                cached["stale"] = False

        return func.HttpResponse(json.dumps(cached, ensure_ascii=False), mimetype="application/json")
    except Exception as e:
        logging.exception("universe error")
        return func.HttpResponse(json.dumps({"ok": False, "error": str(e)}), status_code=500, mimetype="application/json")

# ---------- HTTP: rank (uses Azure OpenAI) ----------
@app.function_name(name="rank")
@app.route(route="rank", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def rank(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = _parse_json_body(req)
        tickers = body.get("tickers")
        if not tickers:
            return func.HttpResponse(json.dumps({"ok": False, "error": "Provide 'tickers' as JSON array."}),
                                     status_code=400, mimetype="application/json")

        tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]
        if not tickers:
            return func.HttpResponse(json.dumps({"ok": False, "error": "No valid tickers supplied."}),
                                     status_code=400, mimetype="application/json")

        strategy = (body.get("strategy") or "long_term").strip()

        horizon_text = body.get("horizon")
        if not horizon_text:
            # Back-compat: horizon_years -> "X years"
            hy = body.get("horizon_years")
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
        return func.HttpResponse(json.dumps({"ok": False, "error": str(e)}), status_code=500, mimetype="application/json")