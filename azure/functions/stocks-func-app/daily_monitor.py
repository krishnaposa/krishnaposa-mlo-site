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
TICKERS: List[str] = [
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
    "NXT","EXEL","BILI","SFM","HAS","BMRN","RGTI","MNDY","LSCC","ENSG","PEGA","PSN","CORT","NICE",
    "KVYO","BLSH","MKSI","HALO","PLNT","BROS","CVLT","OLLI","MHK","SAIA","IESC","PONY","ELF","CAVA",
    "ROAD","FOUR","MARA","APLD","ONTO","US","OPEN","SOUN","ACHR","PATH","RNA","SANM","LEGN","S",
    "CRSP","LEU","EAT","TGTX","UPST","BILL","BTSG","PI","SMR","ATAT","ENPH","PCVX","ZETA","STNE",
    "CALM","YOU","TDS","TMDX","FHI","QUBT","LMND","AGX","ADMA","DOCN","SLNO","VKTX","WRD","ACLS",
    "PLMR","DAVE","SEZL","SGRY","KNTK","AMSC","BBAI","IBRX","UPWK","AI","TVTX","IRON","RXRX","TRMD",
    "SRPT","DXPE","LQDA","DAC","NNE","RVLV","SDGR","GBX","JANX","ROOT","EH","LUNR","EVEX","NKTR",
    "TRVI","GCT","LMB","HLF","FTRE","FVRR","PHAT","EVER","AOSL","URGN","SERV","SRFM","DPRO","ELDN",
    "ATYR"
]
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


# ---------------- Trend-Follow Scoring ----------------
def score_row(r):
    """
    Trend-following score:
    - Heavier on 60-120d momentum & MA structure
    - Rewards proximity to highs & breakouts
    - Softer risk penalties so strong trends aren't over-penalized
    """
    logger.debug(f"Scoring row (trend-follow) for {r['ticker']}")

    momentum_trend = (
        0.50 * r.get("ret_20_z", 0.0) +
        1.00 * r.get("ret_60_z", 0.0) +
        1.20 * r.get("ret_120_z", 0.0) +
        1.00 * (1.0 if (r.get("sma20", 0) > r.get("sma50", 0) > r.get("sma200", 0)) else 0.0) +
        0.80 * r.get("close_above_sma50", 0.0) +
        0.50 * r.get("close_above_sma200", 0.0) +
        0.60 * (1.0 if r.get("macd_hist", 0.0) > 0 else 0.0) +
        0.80 * (1.0 if r.get("dist_52w_high", -1.0) > -0.05 else 0.0) +  # within 5% of 52w high
        0.50 * r.get("new_55d_high", 0.0) +
        0.50 * max(0.0, r.get("sma50_slope", 0.0)) +
        0.50 * max(0.0, r.get("sma200_slope", 0.0))
    )

    liquidity = 1.0 if r.get("adv_usd_20", 0.0) >= MIN_DOLLAR_VOL else -1.0

    vol20 = r.get("vol20", 0.0)
    mdd_60 = r.get("mdd_60", 0.0)
    risk_penalty = 0.30 * vol20 + 1.20 * abs(min(0.0, mdd_60))

    event_penalty = 1.0 if r.get("earnings_within_7d", False) else 0.0

    score = momentum_trend + liquidity - risk_penalty - event_penalty
    logger.debug(f"TF score for {r['ticker']}: {score:.3f}")
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

    logger.info("Fetching SPY benchmark data (kept for future beta calc)")
    _ = yf.download("SPY", period="400d", auto_adjust=True, progress=False)["Close"].pct_change()

    rows = []

    for t, df in frames.items():
        logger.info(f"Processing {t}")
        try:
            d = df.copy()
            d["CloseAdj"] = d["Adj Close"]

            # --- returns ---
            d["ret"] = d["CloseAdj"].pct_change()
            d["ret_5d"] = d["CloseAdj"].pct_change(5)
            d["ret_20"] = d["CloseAdj"].pct_change(20)
            d["ret_21d"] = d["CloseAdj"].pct_change(21)  # ~1 trading month
            d["ret_60"] = d["CloseAdj"].pct_change(60)
            d["ret_120"] = d["CloseAdj"].pct_change(120)

            # --- moving averages & structure ---
            d["sma20"] = d["CloseAdj"].rolling(20).mean()
            d["sma50"] = d["CloseAdj"].rolling(50).mean()
            d["sma200"] = d["CloseAdj"].rolling(200).mean()

            # slopes (pct change over windows; avoid inf)
            d["sma50_slope"] = (d["sma50"].diff(5) / d["sma50"].shift(5)).replace([np.inf, -np.inf], np.nan)
            d["sma200_slope"] = (d["sma200"].diff(10) / d["sma200"].shift(10)).replace([np.inf, -np.inf], np.nan)

            # position vs MAs
            d["close_above_sma50"] = (d["CloseAdj"] > d["sma50"]).astype(float)
            d["close_above_sma200"] = (d["CloseAdj"] > d["sma200"]).astype(float)

            # --- oscillators ---
            d["rsi14"] = rsi(d["CloseAdj"])
            _, _, hist = macd(d["CloseAdj"])
            d["macd_hist"] = hist

            # --- risk/vol ---
            d["tr"] = true_range(d)
            d["atr14"] = d["tr"].rolling(14).mean()
            d["vol20"] = realized_vol(d["ret"], 20)
            d["mdd_60"] = (d["CloseAdj"] / d["CloseAdj"].cummax() - 1.0).rolling(60).min()

            # --- liquidity ---
            d["adv_usd_20"] = d["Volume"].rolling(20).mean() * d["CloseAdj"].rolling(20).mean()

            # --- highs/breakouts ---
            d["hi_252"] = d["CloseAdj"].rolling(252, min_periods=60).max()
            d["dist_52w_high"] = d["CloseAdj"] / d["hi_252"] - 1.0
            d["hi_55"] = d["CloseAdj"].rolling(55, min_periods=30).max()
            d["new_55d_high"] = (d["CloseAdj"] >= d["hi_55"]).astype(float)

            # --- momentum z-scores (use 180d window for stability) ---
            for col in ["ret_20", "ret_60", "ret_120"]:
                mu = d[col].rolling(180).mean()
                sd = d[col].rolling(180).std()
                d[f"{col}_z"] = (d[col] - mu) / sd.replace(0, np.nan)

            # ✅ Safety check
            d_valid = d.dropna(subset=["CloseAdj", "sma50", "sma200"])
            if d_valid.empty:
                logger.warning(f"No valid rows after calculations for {t}, skipping")
                continue

            latest = d.iloc[-1].to_dict()
            latest["ticker"] = t
            latest["earnings_within_7d"] = False  # placeholder for now

            # carry keys that score_row expects (get() already safe, but explicit helps)
            for k in [
                "ret_20_z","ret_60_z","ret_120_z","sma20","sma50","sma200","macd_hist",
                "close_above_sma50","close_above_sma200","dist_52w_high","new_55d_high",
                "sma50_slope","sma200_slope","adv_usd_20","vol20","mdd_60","rsi14",
                "ret_5d","ret_21d"
            ]:
                latest[k] = latest.get(k, np.nan)

            rows.append(latest)
            logger.info(f"Finished indicators for {t}")

        except Exception as e:
            logger.exception(f"Error processing {t}: {e}")

    if not rows:
        logger.error("No rows generated. Exiting.")
        return

    logger.info("Building output DataFrame")
    out = pd.DataFrame(rows)

    # ---------- Trend-Following Score & Buy Filter ----------
    out["score"] = out.apply(score_row, axis=1)
    out["buy_flag"] = (
        (out["score"] > 1.5) &
        (out["rsi14"].between(45, 80)) &
        (out["close_above_sma50"] == 1.0) &
        (out["close_above_sma200"] == 1.0) &
        (out["dist_52w_high"] > -0.10) &   # within 10% of 52w high
        (~out.get("earnings_within_7d", False))
    )

    # ---------- Relative Strength Leaders (5d & 21d, % matters) ----------
    def zscore(s: pd.Series) -> pd.Series:
        mu, sd = s.mean(), s.std()
        if pd.isna(sd) or sd == 0:
            return pd.Series(0.0, index=s.index)
        return (s - mu) / sd

    out["z_5d"] = zscore(out["ret_5d"]).fillna(0.0)
    out["z_21d"] = zscore(out["ret_21d"]).fillna(0.0)

    # Trend-follow tilt: 21d (0.7) over 5d (0.3)
    out["strength_score"] = 0.3 * out["z_5d"] + 0.7 * out["z_21d"]

    leaders = out[(out["ret_5d"] > 0) & (out["ret_21d"] > 0)].copy()
    leaders = leaders.sort_values("strength_score", ascending=False)

    # ---------- Save snapshot ----------
    stamp = TODAY.strftime("%Y-%m-%d")
    csv_path = os.path.join(OUT_DIR, f"daily_snapshot_{stamp}.csv")
    out.to_csv(csv_path, index=False)
    logger.info(f"Saved daily snapshot to {csv_path}")

    # Write rolling parquet history in two flavors
    _append_and_write_parquet(out, OUT_DIR)

    # ---------- Logs ----------
    logger.info("Top picks today (trend-follow score):\n" + str(
        out[out["buy_flag"]][["ticker", "score"]]
        .sort_values("score", ascending=False)
        .head(12)
        .reset_index(drop=True)
        .round({"score": 4})
    ))

    logger.info("Leaders by 5d & 21d performance (both positive, 21d-weighted):\n" + str(
        leaders[["ticker", "ret_5d", "ret_21d", "strength_score"]]
        .head(15)
        .reset_index(drop=True)
        .round({"ret_5d": 4, "ret_21d": 4, "strength_score": 4})
    ))

    logger.info("=== Job finished ===")


if __name__ == "__main__":
    main()