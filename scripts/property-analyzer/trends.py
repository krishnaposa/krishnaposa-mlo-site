# trends.py
"""
ZIP-level housing trends using Kaggle Redfin dataset.
"""

import os, pandas as pd
from kaggle.api.kaggle_api_extended import KaggleApi
from utils import log, warn

DATASET = "redfin/usa-housing-market"
FILENAME = "market-tracker/median_sale_price.csv"
CACHE_DIR = "./kaggle_data"
CACHE_PATH = os.path.join(CACHE_DIR, "median_sale_price.csv")


def ensure_kaggle_csv():
    """Download Redfin ZIP-level CSV via Kaggle API if not already cached."""
    if os.path.exists(CACHE_PATH):
        return CACHE_PATH

    log(f"Downloading {FILENAME} from Kaggle dataset {DATASET} …")
    os.makedirs(CACHE_DIR, exist_ok=True)

    api = KaggleApi()
    api.authenticate()
    api.dataset_download_file(DATASET, file_name=FILENAME, path=CACHE_DIR, force=True)

    # Kaggle delivers as .zip, so unzip
    zip_path = os.path.join(CACHE_DIR, FILENAME + ".zip")
    if os.path.exists(zip_path):
        import zipfile
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(CACHE_DIR)
        os.remove(zip_path)

    if not os.path.exists(CACHE_PATH):
        raise FileNotFoundError("CSV not found after Kaggle download.")
    return CACHE_PATH


def redfin_zip_trend(zip_code: str):
    """Return latest, YoY, and 5-year CAGR metrics for a ZIP from Kaggle dataset."""
    try:
        csv_path = ensure_kaggle_csv()
        df = pd.read_csv(csv_path)
    except Exception as e:
        warn(f"CSV load error: {e}")
        return {"error": "csv_load"}

    need = {"region_type", "region", "period_end", "median_sale_price"}
    if not need.issubset(df.columns):
        return {"error": "bad_columns", "columns": list(df.columns)[:20]}

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