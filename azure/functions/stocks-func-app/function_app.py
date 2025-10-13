# function_app.py  — quiet HTTP logging
#
# NOTE: To also quiet Azure Functions host trigger chatter, add a host.json:
# {
#   "logging": {
#     "logLevel": { "default": "Warning" }
#   }
# }
import os, json, sys, subprocess, logging, pathlib, importlib.util, datetime, shlex
import azure.functions as func
from azure.storage.blob import BlobServiceClient, ContentSettings
import pandas as pd

import daily_monitor
from universe_utils import read_universe_blob as _read_universe_blob
from local_list_utils import load_local_list
from ai_utils import ai_rank_tickers

app = func.FunctionApp()

# ---------- Quiet noisy HTTP logs ----------
QUIET_HTTP_LOGS = os.getenv("QUIET_HTTP_LOGS", "1") == "1"
if QUIET_HTTP_LOGS:
    noisy_loggers = [
        "urllib3",
        "requests",
        "httpx",
        "azure.core.pipeline",
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.storage.blob",
        "azure.identity",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

# ---------- Settings ----------
WB4U_ENTRY = os.getenv("WB4U_ENTRY", "wb4u_main.py")

UNIVERSE_CONTAINER   = os.getenv("UNIVERSE_CONTAINER", "cache")
UNIVERSE_BLOB_NAME   = os.getenv("UNIVERSE_BLOB_NAME", "universe.json")
UNIVERSE_TTL_MIN     = int(os.getenv("UNIVERSE_TTL_MIN", "720"))
UNIVERSE_MAX_SECONDS = int(os.getenv("UNIVERSE_MAX_SECONDS", "60"))

REFRESH_SHARED_KEY = os.getenv("REFRESH_SHARED_KEY")

AZURE_OPENAI_API_VER = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")  # still used by ai_utils via env

SIGNALS_CONTAINER = os.getenv("SIGNALS_CONTAINER", "signals")
MIN_DOLLAR_VOL    = int(os.getenv("MIN_DOLLAR_VOL", "1000000"))
PENNY_PRICE       = float(os.getenv("PENNY_PRICE", "5"))
AI_TOPK           = int(os.getenv("AI_TOPK", "10"))

_BLOB_SVC = BlobServiceClient.from_connection_string(os.getenv("MONITOR_STORAGE"))

# ---------- Small utils ----------
def _parse_json_body(req: func.HttpRequest) -> dict:
    try:
        return req.get_json()
    except ValueError:
        return {}

def _blob_container():
    cont = _BLOB_SVC.get_container_client(UNIVERSE_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont

def _signals_container():
    cont = _BLOB_SVC.get_container_client(SIGNALS_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont

def _upload_bytes(container_client, blob_name: str, data: bytes, content_type: str):
    container_client.upload_blob(
        blob_name, data=data, overwrite=True,
        content_settings=ContentSettings(content_type=content_type)
    )
    # quieter: only show in DEBUG (headers/status come from SDK otherwise)
    logging.debug(f"[upload] wrote {container_client.container_name}/{blob_name} ({len(data)} bytes)")

def _write_universe_blob(tickers: list[str], meta: dict | None = None) -> None:
    cont = _blob_container()
    payload = {
        "ok": True,
        "tickers": tickers,
        "updated_utc": datetime.datetime.utcnow().isoformat() + "Z"
    }
    if isinstance(meta, dict):
        payload.update(meta)
    cont.upload_blob(
        UNIVERSE_BLOB_NAME,
        data=json.dumps(payload).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json")
    )

# ---------- Universe computation (budgeted) ----------
def _load_module_from_path(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        raise ImportError(f"Could not load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod

def _compute_universe_budgeted(max_seconds: int) -> list[str]:
    script_path = (pathlib.Path(__file__).parent / WB4U_ENTRY).resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"WB4U entry not found at {script_path}")

    try:
        mod = _load_module_from_path("wb4u_main_dynamic", str(script_path))
        fn = getattr(mod, "get_universe", None)
        if callable(fn):
            tickers = fn(max_seconds=max_seconds)
            if not isinstance(tickers, (list, tuple)):
                raise TypeError("get_universe() must return a list/tuple")
            cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
            if not cleaned:
                raise ValueError("Universe function returned empty list")
            return cleaned
    except Exception as e:
        logging.info(f"[universe] import path skipped: {e}")

    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))} --max-seconds {int(max_seconds)}"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=max_seconds+5)
    out = (proc.stdout or "").strip()

    try:
        tickers = json.loads(out)
    except json.JSONDecodeError:
        tickers = eval(out, {"__builtins__": {}}, {})

    if not isinstance(tickers, (list, tuple)):
        raise ValueError("Entry script must print a list/JSON array")

    cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
    if not cleaned:
        raise ValueError("No tickers produced by entry script")
    return cleaned

# --------------------------- Timer: monitor ---------------------------
@app.schedule(schedule="0 30 23 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def monitor_signals(timer: func.TimerRequest) -> None:
    try:
        # 1) Quant run (includes email inside daily_monitor)
        df_all, df_leaders = daily_monitor.run_monitor(
            [],  # dynamic list handled in daily_monitor
            min_dollar_vol=MIN_DOLLAR_VOL
        )

        # 2) Persist parquet outputs
        stamp = datetime.date.today().strftime("%Y-%m-%d")
        cont = _signals_container()
        try:
            import pyarrow  # noqa: F401
            engine = "pyarrow"
            _upload_bytes(cont, f"daily_snapshot_{stamp}.snappy.parquet",
                          df_all.to_parquet(engine=engine, compression="snappy", index=False),
                          "application/octet-stream")
            _upload_bytes(cont, f"leaders_{stamp}.snappy.parquet",
                          df_leaders.to_parquet(engine=engine, compression="snappy", index=False),
                          "application/octet-stream")
            logging.info("[parquet] wrote daily + leaders to blob")
        except Exception as e:
            logging.warning(f"[parquet] skipped ({e})")

        # 3) Build combined local+universe list for AI ranking
        try:
            cached = _read_universe_blob() or {}
            universe = [str(t).upper().strip() for t in (cached.get("tickers") or []) if str(t).strip()]
        except Exception:
            universe = []
        try:
            local = load_local_list(initial_fallback=[])
        except Exception:
            local = []

        combined = sorted(set(universe) | set(local))
        if not combined:
            combined = df_all["ticker"].astype(str).str.upper().unique().tolist()

        # Filter out <$5 using df_all’s last_price when available
        if "last_price" in df_all.columns:
            px_map = dict(zip(df_all["ticker"].astype(str).str.upper(), df_all["last_price"].astype(float)))
            combined = [t for t in combined if px_map.get(t, float("inf")) >= PENNY_PRICE]

        # 4) AI rankings (LEAPS & 30–40d debit call spreads)
        ai_leaps   = ai_rank_tickers(combined, strategy="leaps", horizon_text="12–24 months", top_k=AI_TOPK)
        ai_spreads = ai_rank_tickers(combined, strategy="debit_call_spread", horizon_text="30–40 days", top_k=AI_TOPK)

        # Persist AI outputs alongside daily snapshot
        try:
            _upload_bytes(cont, f"ai_leaps_{stamp}.json",
                          ai_leaps.to_json(orient="records").encode("utf-8"),
                          "application/json")
            _upload_bytes(cont, f"ai_debit_call_spreads_{stamp}.json",
                          ai_spreads.to_json(orient="records").encode("utf-8"),
                          "application/json")
            logging.info(f"[ai] wrote AI picks (leaps & 30–40d) -> {SIGNALS_CONTAINER}")
        except Exception as e:
            logging.warning(f"[ai] failed to persist AI outputs: {e}")

        # Log quick summary (kept)
        logging.info("[top picks]\n" + str(
            df_all[df_all["buy_flag"]][["ticker", "score"]]
            .sort_values("score", ascending=False)
            .head(12)
            .reset_index(drop=True)
        ))
        logging.info("[leaders]\n" + str(df_leaders.head(15).reset_index(drop=True)))
        if not ai_leaps.empty:
            logging.info("[AI LEAPS]\n" + str(ai_leaps.head(10)))
        if not ai_spreads.empty:
            logging.info("[AI 30–40d Debit Call Spreads]\n" + str(ai_spreads.head(10)))

    except Exception as e:
        logging.exception(f"[monitor_signals] failed: {e}")

# ---------- Timer: refresh cache ----------
@app.schedule(schedule="0 9 * * 1-5", arg_name="myTimer", run_on_startup=True, use_monitor=True)
def refresh_universe(myTimer: func.TimerRequest) -> None:
    try:
        tickers = _compute_universe_budgeted(UNIVERSE_MAX_SECONDS)
        _write_universe_blob(tickers, {"budget_seconds": UNIVERSE_MAX_SECONDS})
        logging.info(f"[refresh_universe] Cached {len(tickers)} tickers")
    except subprocess.TimeoutExpired:
        logging.exception("[refresh_universe] universe computation timed out")
    except Exception as e:
        logging.exception(f"[refresh_universe] Failed: {e}")

# ---------- Health ----------
@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"ok": true}', mimetype="application/json")

# ---------- Universe (read cache, fallback compute once) ----------
@app.function_name(name="universe")
@app.route(route="universe", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_universe(req: func.HttpRequest) -> func.HttpResponse:
    try:
        cached = _read_universe_blob()
        if not cached:
            tickers = _compute_universe_budgeted(UNIVERSE_MAX_SECONDS)
            _write_universe_blob(tickers, {"budget_seconds": UNIVERSE_MAX_SECONDS})
            cached = {"ok": True, "tickers": tickers, "updated_utc": datetime.datetime.utcnow().isoformat() + "Z"}

        try:
            ts = datetime.datetime.fromisoformat(cached.get("updated_utc", "").replace("Z", ""))
            age_min = (datetime.datetime.utcnow() - ts).total_seconds() / 60.0
            cached["stale"] = age_min > UNIVERSE_TTL_MIN
        except Exception:
            cached["stale"] = False

        return func.HttpResponse(json.dumps(cached, ensure_ascii=False), mimetype="application/json")

    except subprocess.TimeoutExpired:
        return func.HttpResponse(json.dumps({"ok": False, "error": "Universe build timed out"}), status_code=504, mimetype="application/json")
    except Exception as e:
        logging.exception("universe error")
        return func.HttpResponse(json.dumps({"ok": False, "error": str(e)}), status_code=500, mimetype="application/json")

# ---------- Manual refresh ----------
@app.function_name(name="refresh")
@app.route(route="refresh", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def manual_refresh(req: func.HttpRequest) -> func.HttpResponse:
    try:
        if not REFRESH_SHARED_KEY:
            return func.HttpResponse(json.dumps({"ok": False, "error": "REFRESH_SHARED_KEY not set"}), status_code=500, mimetype="application/json")
        supplied = req.headers.get("x-refresh-key") or req.params.get("key")
        if supplied != REFRESH_SHARED_KEY:
            return func.HttpResponse(json.dumps({"ok": False, "error": "Forbidden"}), status_code=403, mimetype="application/json")

        tickers = _compute_universe_budgeted(UNIVERSE_MAX_SECONDS)
        _write_universe_blob(tickers, {"manual": True, "budget_seconds": UNIVERSE_MAX_SECONDS})
        return func.HttpResponse(json.dumps({"ok": True, "count": len(tickers)}), mimetype="application/json")
    except subprocess.TimeoutExpired:
        return func.HttpResponse(json.dumps({"ok": False, "error": "Universe build timed out"}), status_code=504, mimetype="application/json")
    except Exception as e:
        logging.exception("manual refresh error")
        return func.HttpResponse(json.dumps({"ok": False, "error": str(e)}), status_code=500, mimetype="application/json")

# ---------- Rank ----------
@app.function_name(name="rank")
@app.route(route="rank", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def rank(req: func.HttpRequest) -> func.HttpResponse:
    from ai_utils import score_with_azure_openai  # local import to avoid any tool load order issues
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
        horizon_text = body.get("horizon") or (f"{int(body['horizon_years'])} years" if body.get("horizon_years") else "3 years")

        result = score_with_azure_openai(tickers, strategy, horizon_text)
        return func.HttpResponse(
            json.dumps({"ok": True, "strategy": strategy, "horizon": horizon_text, "result": result}, ensure_ascii=False),
            mimetype="application/json"
        )
    except Exception as e:
        logging.exception("rank error")
        return func.HttpResponse(json.dumps({"ok": False, "error": str(e)}), status_code=500, mimetype="application/json")