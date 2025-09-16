# trends.py
import os, re, glob, pandas as pd
import kagglehub

DATASET_SLUG = "soulaimaneebenayyad/united-states-redfin-housing-market-csv"  # from your screenshot
CACHE_DIR = os.path.join("data")
CACHE_CSV = os.path.join(CACHE_DIR, "median_sale_price.csv")  # normalized name we write to

def log(m):  print(f"[INFO] {m}", flush=True)
def warn(m): print(f"[WARN] {m}", flush=True)

def _pick_csv_file(download_dir: str) -> str | None:
    """
    Try to pick the 'median sale price' CSV from the downloaded dataset.
    If the dataset has multiple files, we search by common patterns.
    """
    # try very specific first
    candidates = glob.glob(os.path.join(download_dir, "**", "*median*sale*price*.csv"), recursive=True)
    if candidates:
        return candidates[0]

    # fallback: show what exists
    any_csv = glob.glob(os.path.join(download_dir, "**", "*.csv"), recursive=True)
    if any_csv:
        # Heuristic: prefer 'median' or 'sale' in filename
        ranked = sorted(any_csv, key=lambda p: (
            0 if re.search(r"median.*sale|sale.*median", os.path.basename(p), re.I) else
            1 if re.search(r"median|sale", os.path.basename(p), re.I) else
            2,
            len(os.path.basename(p))
        ))
        return ranked[0]

    return None

def _ensure_csv_on_disk() -> str:
    """
    1) Use local cache if present
    2) Else download dataset with kagglehub and pick the right CSV
    3) Copy/normalize to CACHE_CSV for consistent downstream loading
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if os.path.exists(CACHE_CSV) and os.path.getsize(CACHE_CSV) > 0:
        log(f"Using cached CSV: {CACHE_CSV}")
        return CACHE_CSV

    # Allow manual override too (useful while testing)
    manual = os.environ.get("REDFIN_TRENDS_CSV_PATH")
    if manual and os.path.exists(manual):
        log(f"Using manual CSV (REDFIN_TRENDS_CSV_PATH): {manual}")
        # normalize name
        with open(manual, "rb") as src, open(CACHE_CSV, "wb") as dst:
            dst.write(src.read())
        return CACHE_CSV

    # Download via kagglehub
    log(f"Downloading Kaggle dataset via kagglehub: {DATASET_SLUG}")
    try:
        download_dir = kagglehub.dataset_download(DATASET_SLUG)
        log(f"Dataset downloaded to: {download_dir}")
    except Exception as e:
        warn(f"Kaggle download failed: {e}")
        raise

    picked = _pick_csv_file(download_dir)
    if not picked or not os.path.exists(picked):
        # Show available files to help debugging
        csvs = glob.glob(os.path.join(download_dir, "**", "*.csv"), recursive=True)
        warn(f"Could not find a median sale price CSV. Found CSVs: {csvs[:10]}")
        raise FileNotFoundError("Median sale price CSV not found in downloaded dataset")

    # Normalize path for consistent reads
    log(f"Selected CSV: {picked}")
    with open(picked, "rb") as src, open(CACHE_CSV, "wb") as dst:
        dst.write(src.read())

    return CACHE_CSV

def redfin_zip_trend(zip_code: str):
    """
    Compute latest median sale price, YoY, and 5-year CAGR for a ZIP
    from the Kaggle dataset (cached locally after first run).
    """
    try:
        csv_path = _ensure_csv_on_disk()
        df = pd.read_csv(csv_path)
    except Exception as e:
        warn(f"CSV load error: {e}")
        return {"error": "csv_load", "detail": str(e)}

    # Common Redfin schema names. If the dataset schema differs, adjust here.
    expected_cols = {"region_type","region","period_end","median_sale_price"}
    if not expected_cols.issubset(df.columns):
        # Try to adapt to alternate schemas (some datasets use different column names)
        # Minimal mapping attempt:
        rename_map = {}
        # region_type
        for c in df.columns:
            if c.lower() in {"region_type","regiontype"}: rename_map[c] = "region_type"
            if c.lower() in {"region","zip","zipcode","postal_code"}: rename_map[c] = "region"
            if c.lower() in {"period_end","date","periodend"}: rename_map[c] = "period_end"
            if re.search(r"median.*sale.*price", c, re.I): rename_map[c] = "median_sale_price"
        if rename_map:
            df = df.rename(columns=rename_map)

    if not expected_cols.issubset(df.columns):
        return {"error":"bad_columns", "columns": list(df.columns)[:30]}

    # Filter by ZIP (dataset stores ZIP as string/int in 'region' where region_type == 'zip')
    z = df[(df["region_type"].astype(str).str.lower()=="zip") & (df["region"].astype(str)==str(zip_code))].copy()
    if z.empty:
        return {"zip": str(zip_code), "found": False}

    z["period_end"] = pd.to_datetime(z["period_end"], errors="coerce")
    z = z.dropna(subset=["period_end"]).sort_values("period_end")

    latest = z.iloc[-1]
    latest_price = float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
    latest_date = str(latest["period_end"].date()) if pd.notna(latest["period_end"]) else None

    yoy = None
    cagr5 = None
    if len(z) > 12:
        prev = z.iloc[-13]["median_sale_price"]
        if pd.notna(prev) and latest_price:
            prev = float(prev)
            yoy = (latest_price - prev) / prev if prev else None

    if len(z) > 60:
        prev5 = z.iloc[-61]["median_sale_price"]
        if pd.notna(prev5) and latest_price and float(prev5) > 0:
            prev5 = float(prev5)
            cagr5 = (latest_price / prev5) ** (1/5) - 1

    return {
        "zip": str(zip_code),
        "latest_period_end": latest_date,
        "median_sale_price_latest": latest_price,
        "median_sale_price_yoy": round(yoy, 4) if yoy is not None else None,
        "median_sale_price_cagr_5y": round(cagr5, 4) if cagr5 is not None else None,
        "observations": int(len(z)),
        "source": "kagglehub",
    }