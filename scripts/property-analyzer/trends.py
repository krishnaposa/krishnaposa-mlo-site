# trends.py
"""
ZIP-level housing trends using Kaggle Redfin dataset.
Creates/uses ./kaggle_data/median_sale_price.csv (cached).
"""

import os, io, re, zipfile, shutil, sys
import pandas as pd

# Optional shared log helpers
try:
    from utils import log, warn
except Exception:
    def log(m):  print(f"[INFO] {m}", flush=True)
    def warn(m): print(f"[WARN] {m}", flush=True)

# Kaggle dataset & target file inside the dataset
DATASET      = "redfin/usa-housing-market"
ZIP_MEMBER   = "market-tracker/median_sale_price.csv"  # path within the dataset
CACHE_DIR    = "./kaggle_data"
CACHE_PATH   = os.path.join(CACHE_DIR, "median_sale_price.csv")


def _authenticate_kaggle():
    """
    Ensures Kaggle API is importable and user is authenticated.
    Requires kaggle.json at:
      Windows: %USERPROFILE%\\.kaggle\\kaggle.json
      macOS/Linux: ~/.kaggle/kaggle.json  (chmod 600 recommended)
    """
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except Exception as e:
        raise RuntimeError(
            "Kaggle package not installed. Run: pip install kaggle\n"
            f"Import error: {e}"
        )
    api = KaggleApi()
    try:
        api.authenticate()
    except Exception as e:
        raise RuntimeError(
            "Kaggle authentication failed. Ensure kaggle.json is in the standard location.\n"
            f"Auth error: {e}"
        )
    return api


def _safe_extract_member(zf: zipfile.ZipFile, member_name: str, dest_path: str):
    """
    Extracts `member_name` from zip into `dest_path` (file path, not folder).
    If the member is nested in subfolders, this flattens it to `dest_path`.
    """
    with zf.open(member_name) as src, open(dest_path, "wb") as out:
        shutil.copyfileobj(src, out)


def _ensure_csv_on_disk() -> str:
    """
    Guarantee that ./kaggle_data/median_sale_price.csv exists.
    If not, download from Kaggle and extract it.
    Returns the absolute path to the CSV.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 0:
        log(f"Using cached CSV: {CACHE_PATH}")
        return os.path.abspath(CACHE_PATH)

    api = _authenticate_kaggle()

    # Download the specific file (Kaggle saves as a .zip next to it)
    log(f"Downloading '{ZIP_MEMBER}' from Kaggle dataset '{DATASET}'…")
    api.dataset_download_file(
        DATASET,
        file_name=ZIP_MEMBER,
        path=CACHE_DIR,
        force=True,
        quiet=False,
    )

    zip_path = os.path.join(CACHE_DIR, os.path.basename(ZIP_MEMBER) + ".zip")
    # Some Kaggle versions save the zip using the *full* member path as the base name.
    # So if the file isn't there, try a looser search for a .zip we just downloaded.
    if not os.path.exists(zip_path):
        # Look for any new .zip in CACHE_DIR
        zips = [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR) if f.endswith(".zip")]
        if not zips:
            raise FileNotFoundError("Downloaded zip not found in ./kaggle_data after Kaggle download.")
        # Heuristic: pick the newest zip
        zip_path = max(zips, key=os.path.getmtime)

    # Extract exactly the CSV we need
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        # Try exact member first
        target = None
        if ZIP_MEMBER in names:
            target = ZIP_MEMBER
        else:
            # Fall back: find any entry that ends with the filename (flatten subfolders)
            base = os.path.basename(ZIP_MEMBER)
            matches = [n for n in names if n.endswith("/" + base) or n.endswith(base)]
            if matches:
                target = matches[0]

        if not target:
            raise FileNotFoundError(
                f"Expected '{ZIP_MEMBER}' not found in zip. Members seen: {names[:10]}…"
            )

        log(f"Extracting '{target}' → {CACHE_PATH}")
        _safe_extract_member(zf, target, CACHE_PATH)

    # Clean up the zip; keep only the extracted CSV
    try:
        os.remove(zip_path)
    except Exception:
        pass

    if not os.path.exists(CACHE_PATH) or os.path.getsize(CACHE_PATH) == 0:
        raise FileNotFoundError("CSV write failed; file is missing or empty after extraction.")

    log(f"CSV ready: {CACHE_PATH}")
    return os.path.abspath(CACHE_PATH)


def redfin_zip_trend(zip_code: str):
    """
    Load ./kaggle_data/median_sale_price.csv and compute:
      - latest median price
      - YoY change
      - 5-year CAGR
    """
    try:
        csv_path = _ensure_csv_on_disk()
        df = pd.read_csv(csv_path)
    except Exception as e:
        warn(f"CSV load error: {e}")
        return {"error": "csv_load"}

    required = {"region_type", "region", "period_end", "median_sale_price"}
    if not required.issubset(df.columns):
        return {"error": "bad_columns", "columns": list(df.columns)[:20]}

    z = df[(df.region_type == "zip") & (df.region.astype(str) == str(zip_code))].copy()
    if z.empty:
        warn(f"No ZIP data for {zip_code}")
        return {"zip": str(zip_code), "found": False}

    z["period_end"] = pd.to_datetime(z["period_end"], errors="coerce")
    z = z.sort_values("period_end")
    z = z[pd.notna(z["period_end"])]

    latest = z.iloc[-1]
    latest_price = float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
    latest_date = str(latest["period_end"].date())

    yoy = None
    cagr5 = None
    if len(z) > 12:
        prev = float(z.iloc[-13]["median_sale_price"]) if pd.notna(z.iloc[-13]["median_sale_price"]) else None
        if latest_price and prev and prev > 0:
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
        "csv_path": os.path.abspath(CACHE_PATH),
    }


# ---------- tiny CLI for quick testing ----------
if __name__ == "__main__":
    # Example: python trends.py 30009
    if len(sys.argv) < 2:
        print("Usage: python trends.py <ZIP>")
        sys.exit(1)
    zip_arg = re.sub(r"\D", "", sys.argv[1]) or sys.argv[1]
    print(json.dumps(redfin_zip_trend(zip_arg), indent=2))