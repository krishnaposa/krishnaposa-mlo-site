import os
import logging
from datetime import datetime, timedelta
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ---------------- Config ----------------
TICKERS: List[str] = ["META","TSM","ORCL","WMT","BABA","ABBV","PLTR","ASML","GE","UNH", "SAP", "IBM", "AMD", "AZN", "NVO", "AXP", "RTX", "APP", "MU", "UBER", "NOW", "PDD", "ANET", "SHOP", "LRCX", "BKNG", "BLK", "AMAT", "GEV", "TJX", "ARM", "ISRG", "APH", "KLAC", "SPOT", "ADBE", "ETN", "COF", "PANW", "BYDDF", "CRWD", "KKR", "MELI", "SE", "CEG", "HOOD", "VRTX", "BMY", "CDNS", "MCK", "ICE", "DELL", "MSTR", "SNPS", "RBLX", "RACE", "RCL", "MCO", "COIN", "HWM", "AJG", "SNOW", "NET", "EMR", "TDG", "MRVL", "VST", "JCI", "FI", "FTNT", "ZTS", "PYPL", "REGN", "WDAY", "PWR", "COR", "ALNY", "CRWV", "CPNG", "LHX", "STX", "DDOG", "ARES", "IDXX", "TCOM", "ZS", "VEEV", "CVNA", "PMRTY", "XYZ", "MPWR", "FANG", "TEAM", "CCL", "EBAY", "RMD", "RDDT", "HEI", "TRGP", "GFI", "FICO", "TME", "CSGP", "EQT", "MCHP", "SYM", "SOFI", "ALAB", "NRG", "SMCI", "INSM", "CRCL", "UAL", "FIX", "ROL", "PSTG", "EXPE", "NBIS", "SYF", "MDB", "VLTO", "LI", "EXE", "LPLA", "DXCM", "HUBS", "AFRM", "CYBR", "LDOS", "BNTX", "WSM", "GRAB", "FSLR", "ESLT", "RKLB", "TTD", "PINS", "XPEV", "TER", "IOT", "IONQ", "PODD", "SATS", "DG", "TYL", "TOST", "BE", "NTNX", "RPRX", "LULU", "ASTS", "DKNG", "GMAB", "GFS", "GDDY", "TRMB", "CTRA", "NIO", "COHR", "THC", "FTAI", "AVAV", "OKLO", "FTI", "TKO", "RBRK", "TWLO", "CHWY", "OKTA", "KTOS", "DOCU", "DECK", "IFF", "SMMT", "ROKU", "XPO", "TEM", "CELH", "SN", "SNAP", "DUOL", "NBIX", "DOCS", "ONON", "DOC", "VNOM", "HIMS", "CRS", "IREN", "BAH", "MANH", "LSRCY", "ASND", "GLXY", "RNR", "DRS", "PAYC", "NXT", "EXEL", "BILI", "SFM", "HAS", "BMRN", "RGTI", "MNDY", "LSCC", "ENSG", "PEGA", "PSN", "CORT", "NICE", "KVYO", "BLSH", "MKSI", "HALO", "PLNT", "BROS", "CVLT", "OLLI", "MHK", "SAIA","IESC", "PONY", "ELF", "CAVA", "ROAD", "FOUR", "MARA", "APLD", "ONTO", "US", "OPEN", "SOUN", "ACHR", "PATH", "RNA", "SANM", "LEGN", "S", "CRSP", "LEU", "EAT", "TGTX", "UPST", "BILL", "BTSG", "PI", "SMR", "ATAT", "ENPH", "PCVX", "ZETA", "STNE", "CALM", "YOU", "TDS", "TMDX", "FHI", "QUBT", "LMND", "AGX", "ADMA", "DOCN", "SLNO", "VKTX", "WRD", "ACLS", "PLMR", "DAVE", "SEZL", "SGRY", "KNTK", "AMSC", "BBAI", "IBRX", "UPWK", "AI", "TVTX", "IRON", "RXRX", "TRMD", "SRPT", "DXPE", "LQDA", "DAC", "NNE", "RVLV", "SDGR", "GBX", "JANX", "ROOT", "EH", "LUNR", "EVEX", "NKTR", "TRVI", "GCT", "LMB", "HLF", "FTRE", "FVRR", "PHAT", "EVER", "AOSL", "URGN", "SERV", "SRFM", "DPRO", "ELDN", "ATYR" ]
LOOKBACK_CAL_DAYS = 400
OUT_DIR = "daily_stock_monitor"
MIN_DOLLAR_VOL = 1_000_000
EARNINGS_BLACKOUT_DAYS = 7
TODAY = datetime.now().date()
os.makedirs(OUT_DIR, exist_ok=True)


# ---------------- Helper Functions ----------------
def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    logger.info(f"Computing RSI (n={n})")
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(n).mean()
    roll_down = pd.Series(down, index=series.index).rolling(n).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    logger.debug("RSI computation finished")
    return out.fillna(50)

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    logger.info(f"Computing MACD (fast={fast}, slow={slow}, signal={signal})")
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    logger.debug("MACD computation finished")
    return macd_line, signal_line, hist

def true_range(df: pd.DataFrame) -> pd.Series:
    logger.info("Computing True Range")
    prev_close = df["Adj Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    logger.debug("True Range computation finished")
    return tr

def realized_vol(returns: pd.Series, n=20):
    logger.info(f"Computing realized volatility (n={n})")
    out = returns.rolling(n).std() * np.sqrt(252)
    logger.debug("Realized volatility finished")
    return out

def fetch_prices(tickers: List[str]) -> dict[str, pd.DataFrame]:
    logger.info(f"Fetching price data for {len(tickers)} tickers")
    end = TODAY + timedelta(days=1)
    start = TODAY - timedelta(days=LOOKBACK_CAL_DAYS)
    data = yf.download(tickers=tickers, start=start, end=end,
                       auto_adjust=False, group_by="ticker", progress=False)
    frames = {}
    for t in tickers:
        if t in data:
            frames[t] = data[t].dropna(subset=["Adj Close"]).copy()
            logger.info(f"Fetched {len(frames[t])} rows for {t}")
        else:
            logger.warning(f"No data returned for {t}")
    logger.info("Finished fetching all prices")
    return frames


# ---------------- Scoring ----------------
def score_row(r):
    logger.debug(f"Scoring row for {r['ticker']}")
    momentum = (
        r["ret_20_z"] + r["ret_60_z"]
        + (1.0 if r["sma20"] > r["sma50"] > r["sma200"] else 0.0)
        + (1.0 if r["macd_hist"] > 0 else 0.0)
    )
    risk_penalty = (r["vol20"] * 0.5) + abs(min(0.0, r["mdd_60"])) * 1.5
    liq = 1.0 if r["adv_usd_20"] >= MIN_DOLLAR_VOL else -1.0
    event_penalty = 1.0 if r["earnings_within_7d"] else 0.0
    score = momentum + liq - risk_penalty - event_penalty
    logger.debug(f"Score for {r['ticker']}: {score:.2f}")
    return score


def _append_and_write_parquet(out_today: pd.DataFrame, out_dir: str) -> None:
    """
    Appends today's rows to rolling parquet history and writes
    both compressed and plain variants for compatibility.
    """
    logger.info("Updating rolling parquet history")
    out_today = out_today.copy()
    out_today["asof_date"] = pd.to_datetime(TODAY)

    pq_path = os.path.join(out_dir, "rolling_store.parquet")
    pq_plain_path = os.path.join(out_dir, "rolling_store_plain.parquet")

    try:
        import pyarrow  # noqa: F401
        engine = "pyarrow"
    except Exception:
        logger.warning("pyarrow not installed. Skipping parquet writes.")
        return

    # Load previous history if it exists
    if os.path.exists(pq_path):
        try:
            prev = pd.read_parquet(pq_path, engine=engine)
            hist = pd.concat([prev, out_today], ignore_index=True)
            logger.info(f"Loaded existing history with {len(prev)} rows; new total {len(hist)}")
        except Exception as e:
            logger.exception(f"Failed reading existing parquet history, recreating from today only: {e}")
            hist = out_today
    else:
        hist = out_today
        logger.info("No existing history found. Creating new parquet store")

    # Write compressed (fast) version
    try:
        hist.to_parquet(pq_path, engine=engine, compression="snappy", index=False)
        logger.info(f"Wrote compressed parquet to {pq_path}")
    except Exception as e:
        logger.exception(f"Failed writing compressed parquet: {e}")

    # Write plain (viewer-friendly) version
    try:
        hist.to_parquet(pq_plain_path, engine=engine, compression="none", index=False)
        logger.info(f"Wrote plain parquet to {pq_plain_path}")
    except Exception as e:
        logger.exception(f"Failed writing plain parquet: {e}")


# ---------------- Main ----------------
def main():
    logger.info("=== Starting daily stock monitor ===")
    frames = fetch_prices(TICKERS)
    if not frames:
        logger.error("No data downloaded. Exiting.")
        return

    logger.info("Fetching SPY benchmark data")
    spy = yf.download("SPY", period="400d", auto_adjust=True, progress=False)["Close"].pct_change()
    rows = []

for t, df in frames.items():
    logger.info(f"Processing {t}")
    try:
        d = df.copy()
        d["CloseAdj"] = d["Adj Close"]
        d["ret"] = d["CloseAdj"].pct_change()
        d["ret_20"] = d["CloseAdj"].pct_change(20)
        d["ret_60"] = d["CloseAdj"].pct_change(60)
        d["sma20"] = d["CloseAdj"].rolling(20).mean()
        d["sma50"] = d["CloseAdj"].rolling(50).mean()
        d["sma200"] = d["CloseAdj"].rolling(200).mean()
        d["rsi14"] = rsi(d["CloseAdj"])
        _, _, hist = macd(d["CloseAdj"])
        d["macd_hist"] = hist
        d["tr"] = true_range(d)
        d["atr14"] = d["tr"].rolling(14).mean()
        d["vol20"] = realized_vol(d["ret"], 20)
        d["mdd_60"] = (d["CloseAdj"] / d["CloseAdj"].cummax() - 1.0).rolling(60).min()
        d["adv_usd_20"] = d["Volume"].rolling(20).mean() * d["CloseAdj"].rolling(20).mean()
        d["dist_52w_high"] = d["CloseAdj"] / d["CloseAdj"].rolling(252).max() - 1.0
        d["ret_20_z"] = (d["ret_20"] - d["ret_20"].mean()) / d["ret_20"].std()
        d["ret_60_z"] = (d["ret_60"] - d["ret_60"].mean()) / d["ret_60"].std()

        # ✅ Safety check
        if d.empty:
            logger.warning(f"No valid rows after calculations for {t}, skipping")
            continue

        latest = d.iloc[-1].to_dict()
        latest["ticker"] = t
        latest["earnings_within_7d"] = False  # placeholder
        rows.append(latest)
        logger.info(f"Finished indicators for {t}")

    except Exception as e:
        logger.exception(f"Error processing {t}: {e}")
    
    if not rows:
        logger.error("No rows generated. Exiting.")
        return

    logger.info("Building output DataFrame")
    out = pd.DataFrame(rows)
    out["score"] = out.apply(score_row, axis=1)
    out["buy_flag"] = (out["score"] > 1.0) & (out["rsi14"].between(40, 75))

    stamp = TODAY.strftime("%Y-%m-%d")
    csv_path = os.path.join(OUT_DIR, f"daily_snapshot_{stamp}.csv")
    out.to_csv(csv_path, index=False)
    logger.info(f"Saved daily snapshot to {csv_path}")

    # Write rolling parquet history in two flavors
    _append_and_write_parquet(out, OUT_DIR)

    logger.info("Top picks today:\n" + str(
      out[out["buy_flag"]][["ticker", "score"]].head(10).reset_index(drop=True)
    ))
    logger.info("=== Job finished ===")


if __name__ == "__main__":
    main()