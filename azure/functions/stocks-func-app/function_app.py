import os, json, sys, subprocess, logging, pathlib, importlib.util, datetime, shlex
import azure.functions as func
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient, ContentSettings
from typing import List
import daily_monitor  # <--- our new module
# replace old _read_universe_blob definition
from universe_utils import read_universe_blob as _read_universe_blob
app = func.FunctionApp()

# ---------- Settings ----------
WB4U_ENTRY = os.getenv("WB4U_ENTRY", "wb4u_main.py")

# Universe caching (Blob)
UNIVERSE_CONTAINER = os.getenv("UNIVERSE_CONTAINER", "cache")
UNIVERSE_BLOB_NAME = os.getenv("UNIVERSE_BLOB_NAME", "universe.json")
UNIVERSE_TTL_MIN   = int(os.getenv("UNIVERSE_TTL_MIN", "720"))   # 12h staleness flag
UNIVERSE_MAX_SECONDS = int(os.getenv("UNIVERSE_MAX_SECONDS", "60"))  # hard budget

# Manual refresh protection
REFRESH_SHARED_KEY = os.getenv("REFRESH_SHARED_KEY")  # set a strong random string

# Azure OpenAI
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

SIGNALS_CONTAINER = os.getenv("SIGNALS_CONTAINER", "signals")
TICKERS_CSV = os.getenv("TICKERS_CSV", "").strip()         # optional comma-separated override
MIN_DOLLAR_VOL = int(os.getenv("MIN_DOLLAR_VOL", "1000000"))

# Blob client (uses AzureWebJobsStorage)
_BLOB_SVC = BlobServiceClient.from_connection_string(os.getenv("AzureWebJobsStorage"))

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

def _read_universe_blob() -> dict | None:
    cont = _blob_container()
    try:
        blob = cont.get_blob_client(UNIVERSE_BLOB_NAME)
        data = blob.download_blob().readall()
        return json.loads(data)
    except Exception:
        return None

# ---------- Universe computation (budgeted) ----------
def _load_module_from_path(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        raise ImportError(f"Could not load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod

def _compute_universe_budgeted(max_seconds: int) -> list[str]:
    """
    Prefer calling a function in wb4u_main.py: get_universe(max_seconds: int|None)
    Fallback: execute script with --max-seconds and parse stdout.
    This guarantees a hard wall-clock cap via subprocess timeout.
    """
    script_path = (pathlib.Path(__file__).parent / WB4U_ENTRY).resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"WB4U entry not found at {script_path}")

    # Try import & call first (fast path)
    try:
        mod = _load_module_from_path("wb4u_main_dynamic", str(script_path))
        fn = getattr(mod, "get_universe", None)
        if callable(fn):
            # Soft budget via function arg; still enforce a hard cap with subprocess if desired.
            tickers = fn(max_seconds=max_seconds)
            if not isinstance(tickers, (list, tuple)):
                raise TypeError("get_universe() must return a list/tuple")
            cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
            if not cleaned:
                raise ValueError("Universe function returned empty list")
            return cleaned
    except Exception as e:
        logging.info(f"[universe] import path skipped: {e}")

    # Fallback: run as script with a hard timeout
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

# ---------- OpenAI ranking ----------
def _make_prompt(tickers, strategy: str, horizon_text: str | None = None):
    """
    Builds the system+user messages for Azure OpenAI.
    Horizon is optional. If omitted, prompt/schema won’t include it.
    """
    system = (
        "You are an equity analyst. Return ONLY JSON.\n"
        "Rank the provided tickers for the chosen strategy with concise reasoning.\n"
        "Scores should be on a 0–10 scale (higher is better)."
    )

    # --- Strategy-specific instructions ---
    STRAT_INSTRUCTIONS = {
        "long_term":        "Emphasize durable moats, compounding, FCF quality, and drawdown resilience.",
        "medium_term":      "Focus on 6–24 month setup quality: earnings trend, margin trajectory, valuation re-rate potential.",
        "swing":            "Evaluate 1–8 week momentum/mean-reversion setups: trend strength, volume, risk areas.",
        "leaps":            "Suitability for long-dated options: catalysts pipeline, trend quality, IV/liquidity, macro sensitivity.",
        "short_term_options": "Weeklies/monthlies: near-term catalysts, IV crush risk, liquidity, technicals.",
        "covered_calls":    "Underlying stability for call writing: dividend safety, beta, pullback risk, implied yield.",
        "protective_puts":  "Hedge candidates: drawdown risk profile, tail risk factors, correlation benefits.",
        "value":            "Undervaluation: low P/E/P/B/EV/EBITDA vs peers, FCF yield, balance sheet strength.",
        "growth":           "Secular growth: revenue/EPS acceleration, TAM expansion, reinvestment runway, unit economics.",
        "dividend_income":  "Income stability: dividend yield, payout ratio safety, growth history, balance sheet.",
        "quality":          "Quality bias: high ROE/ROIC, stable margins, low leverage, consistent execution.",
        "momentum":         "Relative/absolute strength: new highs, breadth, volume confirmation, trend persistence.",
        "contrarian":       "Mean-reversion asymmetry: oversold extremes, improving revisions, identifiable catalysts.",
        "tech_innovation":  "AI/semis/software leadership: product velocity, R&D moat, platform effects.",
        "energy_transition":"Renewables/EV/infrastructure: policy tailwinds, cost curves, supply chains.",
        "defensive":        "Defensive posture: staples/utilities/healthcare with stable cash flows and low beta.",
        "cyclical":         "Economic leverage: operating leverage, order books, inventory cycles, sensitivity to PMI/rates.",
        "earnings_play":    "Earnings skew: revision trends, surprise history, positioning/IV, post-earnings drift.",
        "merger_arbitrage": "Announced deals: spread, deal risk, regulatory odds, timeline—expected outcome.",
        "catalyst_trading": "Near-term discrete events: product launches, FDA/regulatory, investor days, macro prints.",
        "short_squeeze":    "High short interest dynamics: borrow cost, days to cover, rel-vol, technical triggers."
    }

    base_instruction = STRAT_INSTRUCTIONS.get(
        strategy,
        f"Evaluate the '{strategy}' approach with clear, investable reasoning."
    )

    # Append horizon only if provided
    if horizon_text:
        instruction = f"{base_instruction} Horizon: {horizon_text}."
    else:
        instruction = base_instruction

    # --- Output schema ---
    schema_props = {
        "strategy": {"type": "string"},
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
    }
    required_fields = ["strategy", "ranked"]

    if horizon_text:  # only include horizon if present
        schema_props["horizon"] = {"type": "string"}
        required_fields.append("horizon")

    user = {
        "strategy": strategy,
        "tickers": tickers,
        "instructions": instruction,
        "output_format": {
            "type": "object",
            "properties": schema_props,
            "required": required_fields
        },
        "scoring_guidance": {
            "scale": "0-10",
            "rough_buckets": {"excellent": "8-10", "good": "6-7.9", "ok": "4-5.9", "weak": "<4"}
        },
        "format_expectations": "Return valid JSON that matches the schema. Keep theses/risks concise (1-3 lines)."
    }

    if horizon_text:
        user["horizon"] = horizon_text  # provide context to the model

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
    logging.info(f"[upload] wrote {container_client.container_name}/{blob_name} ({len(data)} bytes)")

# Your in-code default list (same one you’ve been using)
LIST_TICKERS: List[str] = [
    "META","TSM","ORCL","WMT","BABA","ABBV","PLTR","ASML","GE","UNH","SAP","IBM","AMD","AZN",
    "NVO","AXP","RTX","APP","MU","UBER","NOW","PDD","ANET","SHOP","LRCX","BKNG","BLK","AMAT",
    "GEV","TJX","ARM","ISRG","APH","KLAC","SPOT","ADBE","ETN","COF","PANW","BYDDF","CRWD","KKR",
    "MELI","SE","CEG","HOOD","VRTX","BMY","CDNS","MCK","ICE","DELL","MSTR","SNPS","RBLX","RACE",
    "RCL","MCO","COIN","HWM","AJG","SNOW","NET","EMR","TDG","MRVL","VST","JCI","FI","FTNT","ZTS",
    "PYPL","REGN","WDAY","PWR","COR","ALNY","CRWV","CPNG","LHX","STX","DDOG","ARES","IDXX","TCOM",
    "ZS","VEEV","CVNA","PMRTY","XYZ","MPWR","FANG","TEAM","CCL","EBAY","RMD","RDDT","HEI","TRGP",
    "GFI","FICO","TME","CSGP","EQT","MCHP","SYM","SOFI","ALAB","NRG","SMCI","INSM","CRCL","UAL",
    "FIX","ROL","PSTG","EXPE","NBIS","SYF","MDB","VLTO","LI","EXE","LPLA","DXCM","HUBS","AFRM",
    "CYBR","LDOS","BNTX","WSM","GRAB","FSLR","ESLT","RKLB","TTD","PINS","XPEV","TER","IOT","IONQ",
    "PODD","SATS","DG","TYL","TOST","BE","NTNX","RPRX","LULU","ASTS","DKNG","GMAB","GFS","GDDY",
    "TRMB","CTRA","NIO","COHR","THC","FTAI","AVAV","OKLO","FTI","TKO","RBRK","TWLO","CHWY","OKTA",
    "KTOS","DOCU","DECK","IFF","SMMT","ROKU","XPO","TEM","CELH","SN","SNAP","DUOL","NBIX","DOCS",
    "ONON","DOC","VNOM","HIMS","CRS","IREN","BAH","MANH","LSRCY","ASND","GLXY","RNR","DRS","PAYC",
    "NXT","EXEL","BILI","HAS","BMRN","RGTI","MNDY","LSCC","ENSG","PEGA","PSN","CORT","NICE",
    "KVYO","BLSH","MKSI","HALO","PLNT","BROS","CVLT","OLLI","MHK","SAIA","IESC","PONY","ELF","CAVA",
    "ROAD","FOUR","MARA","APLD","ONTO","USM","OPEN","SOUN","ACHR","PATH","RNA","SANM","LEGN","S",
    "CRSP","LEU","EAT","TGTX","UPST","BILL","BTSG","PI","SMR","ATAT","ENPH","PCVX","ZETA","STNE",
    "CALM","YOU","TDS","TMDX","FHI","QUBT","LMND","AGX","ADMA","DOCN","SLNO","VKTX","WRD","ACLS",
    "PLMR","DAVE","SEZL","SGRY","KNTK","AMSC","BBAI","IBRX","UPWK","AI","TVTX","IRON","RXRX","TRMD",
    "SRPT","DXPE","LQDA","DAC","NNE","RVLV","SDGR","GBX","JANX","ROOT","EH","LUNR","EVEX","NKTR",
    "TRVI","GCT","LMB","HLF","FTRE","FVRR","PHAT","EVER","AOSL","URGN","SERV","SRFM","DPRO","ELDN",
    "ATYR"
]

def _get_tickers() -> List[str]:
    if TICKERS_CSV:
        return [t.strip().upper() for t in TICKERS_CSV.split(",") if t.strip()]
    return LIST_TICKERS


# --- ADD this new timer function (Mon–Fri 23:30 UTC) ---
# --- Timer function: run daily monitor (Mon–Fri 23:30 UTC) ---
@app.schedule(schedule="0 30 23 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def monitor_signals(timer: func.TimerRequest) -> None:
    try:
        tickers = _get_tickers()
        logging.info(f"[monitor_signals] running for {len(tickers)} tickers")

        # Run monitor (daily_monitor handles scoring + email internally)
        df_all, df_leaders = daily_monitor.run_monitor(
            tickers,
            min_dollar_vol=MIN_DOLLAR_VOL
        )

        stamp = datetime.date.today().strftime("%Y-%m-%d")
        cont = _signals_container()

        # ✅ Parquet uploads only
        try:
            import pyarrow  # noqa: F401
            engine = "pyarrow"
            _upload_bytes(cont, f"daily_snapshot_{stamp}.snappy.parquet",
                          df_all.to_parquet(engine=engine, compression="snappy", index=False),
                          "application/octet-stream")
            _upload_bytes(cont, f"leaders_{stamp}.snappy.parquet",
                          df_leaders.to_parquet(engine=engine, compression="snappy", index=False),
                          "application/octet-stream")
            _upload_bytes(cont, f"daily_snapshot_{stamp}.plain.parquet",
                          df_all.to_parquet(engine=engine, compression="none", index=False),
                          "application/octet-stream")
            _upload_bytes(cont, f"leaders_{stamp}.plain.parquet",
                          df_leaders.to_parquet(engine=engine, compression="none", index=False),
                          "application/octet-stream")
            logging.info("[parquet] wrote daily + leaders to blob")
        except Exception as e:
            logging.warning(f"[parquet] skipped ({e})")

        # Log quick summary
        logging.info("[top picks]\n" + str(
            df_all[df_all["buy_flag"]][["ticker", "score"]]
            .sort_values("score", ascending=False)
            .head(12)
            .reset_index(drop=True)
        ))
        logging.info("[leaders]\n" + str(
            df_leaders.head(15).reset_index(drop=True)
        ))

        # ✅ Email already sent inside daily_monitor.run_monitor()

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

        # stale flag
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

# ---------- Manual refresh (shared-key protected) ----------
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