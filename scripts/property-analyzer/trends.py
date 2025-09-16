import os, pandas as pd
from kaggle.api.kaggle_api_extended import KaggleApi

DATASET_SLUG = "soulaimaneebnayyad/united-states-redfin-housing-market-csv"
LOCAL_CSV = "data/redfin_housing.csv"

def ensure_kaggle_csv():
    if not os.path.exists(LOCAL_CSV):
        api = KaggleApi()
        api.authenticate()
        print(f"[INFO] Downloading dataset {DATASET_SLUG} via Kaggle API...")
        api.dataset_download_file(DATASET_SLUG, file_name="median_sale_price.csv", path="data", force=True)
        # Kaggle API downloads as ZIP by default, so unzip
        import zipfile
        zip_path = os.path.join("data", "median_sale_price.csv.zip")
        if os.path.exists(zip_path):
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall("data")
            os.remove(zip_path)
    return LOCAL_CSV

def redfin_zip_trend(zip_code: str):
    try:
        csv_path = ensure_kaggle_csv()
        df = pd.read_csv(csv_path)
    except Exception as e:
        return {"error": f"csv_load_failed: {e}"}

    if not {"region_type","region","period_end","median_sale_price"}.issubset(df.columns):
        return {"columns": list(df.columns)}

    z = df[(df.region_type=="zip") & (df.region.astype(str)==str(zip_code))].copy()
    if z.empty:
        return {"zip":zip_code, "found":False}

    z["period_end"] = pd.to_datetime(z["period_end"])
    z = z.sort_values("period_end")

    latest = z.iloc[-1]
    latest_price = float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
    latest_date = str(latest["period_end"].date())

    yoy = None; cagr5 = None
    if len(z) > 12:
        prev = float(z.iloc[-13]["median_sale_price"]) if pd.notna(z.iloc[-13]["median_sale_price"]) else None
        if latest_price and prev:
            yoy = (latest_price-prev)/prev
    if len(z) > 60:
        prev5 = float(z.iloc[-61]["median_sale_price"]) if pd.notna(z.iloc[-61]["median_sale_price"]) else None
        if latest_price and prev5 and prev5>0:
            cagr5 = (latest_price/prev5)**(1/5)-1

    return {
        "zip": str(zip_code),
        "latest_period_end": latest_date,
        "median_sale_price_latest": latest_price,
        "median_sale_price_yoy": round(yoy,4) if yoy is not None else None,
        "median_sale_price_cagr_5y": round(cagr5,4) if cagr5 is not None else None,
        "observations": int(len(z))
    }