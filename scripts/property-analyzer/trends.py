# trends.py
import io
import requests
import pandas as pd

from utils import warn, log

# Primary: GitHub mirror of Redfin public data (avoids S3 403)
PRIMARY_CSV = (
    "https://raw.githubusercontent.com/RedfinEngineering/public-data/main/"
    "housing-market-data/market-tracker/median_sale_price.csv"
)

# Fallback: original S3 object (sometimes 403s)
FALLBACK_CSV = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "housing-market-data/market-tracker/median_sale_price.csv"
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/124.0"


def _fetch_csv_text() -> str | None:
    # 1) GitHub mirror
    try:
        log("ZIP trends: fetching CSV from GitHub mirror…")
        r = requests.get(PRIMARY_CSV, headers={"User-Agent": UA, "Accept": "text/csv"}, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        warn(f"GitHub CSV fetch failed: {e}")

    # 2) S3 (with Referer + UA — helps in some regions)
    try:
        log("ZIP trends: fetching CSV from S3 (fallback)…")
        r = requests.get(
            FALLBACK_CSV,
            headers={"User-Agent": UA, "Accept": "text/csv", "Referer": "https://www.redfin.com/"},
            timeout=30,
        )
        r.raise_for_status()
        return r.text
    except Exception as e:
        warn(f"S3 CSV fetch failed: {e}")

    return None


def redfin_zip_trend(zip_code: str):
    text = _fetch_csv_text()
    if text is None:
        return {"error": "csv_load"}

    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as e:
        warn(f"CSV parse error: {e}")
        return {"error": "csv_load"}

    need = {"region_type", "region", "period_end", "median_sale_price"}
    if not need.issubset(df.columns):
        return {"columns": list(df.columns)[:20]}

    z = df[(df.region_type == "zip") & (df.region.astype(str) == str(zip_code))].copy()
    if z.empty:
        warn(f"No ZIP data for {zip_code}")
        return {"zip": zip_code, "found": False}

    z["period_end"] = pd.to_datetime(z["period_end"])
    z = z.sort_values("period_end")

    latest = z.iloc[-1]
    latest_price = float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
    latest_date = str(latest["period_end"].date())

    yoy = None
    cagr5 = None
    if len(z) > 12:
        prev = float(z.iloc[-13]["median_sale_price"]) if pd.notna(z.iloc[-13]["median_sale_price"]) else None
        if latest_price and prev:
            yoy = (latest_price - prev) / prev
    if len(z) > 60:
        prev5 = float(z.iloc[-61]["median_sale_price"]) if pd.notna(z.iloc[-61]["median_sale_price"]) else None
        if latest_price and prev5 and prev5 > 0:
            cagr5 = (latest_price / prev5) ** (1 / 5) - 1

    return {
        "zip": str(zip_code),
        "latest_period_end": latest_date,
        "median_sale_price_latest": latest_price,
        "median_sale_price_yoy": round(yoy, 4) if yoy is not None else None,
        "median_sale_price_cagr_5y": round(cagr5, 4) if cagr5 is not None else None,
        "observations": int(len(z)),
    }