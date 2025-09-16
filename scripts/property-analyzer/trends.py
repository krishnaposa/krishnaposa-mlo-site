# trends.py
"""
ZIP-level housing trends using Kaggle Redfin dataset.
Creates/uses ./kaggle_data/median_sale_price.csv (cached).
Auto-discovers the correct file path inside the Kaggle dataset to avoid 404s.
"""

import os, re, sys, json, shutil, zipfile
import pandas as pd

# Simple logging
def log(m):  print(f"[INFO] {m}", flush=True)
def warn(m): print(f"[WARN] {m}", flush=True)

# Kaggle dataset slug (adjust if you use a forked dataset)
DATASET   = "redfin/usa-housing-market"
CACHE_DIR = "./kaggle_data"
CACHE_PATH = os.path.join(CACHE_DIR, "median_sale_price.csv")

# Patterns we accept for the target CSV (order = priority)
CANDIDATE_PATTERNS = [
    r"^market[-_/]tracker/median_sale_price\.csv$",
    r"^housing[-_/]market[-_/]data/.*/median_sale_price\.csv$",
    r"^median_sale_price\.csv$",
    r"median_sale_price\.csv$",              # anywhere inside subfolders
]

def _authenticate_kaggle():
    """Authenticate with Kaggle API (requires kaggle.json in ~/.kaggle/)."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except Exception as e:
        raise RuntimeError("Kaggle not installed. Run: pip install kaggle") from e
    api = KaggleApi()
    api.authenticate()
    return api

def _find_candidate_name(file_names):
    """Pick the best-matching file name from dataset file list."""
    # normalize to forward slashes
    norm = [f.replace("\\", "/") for f in file_names]
    # 1) regex patterns in priority order
    for pat in CANDIDATE_PATTERNS:
        rx = re.compile(pat, re.IGNORECASE)
        for name in norm:
            if rx.search(name):
                return name
    # 2) fallback: anything ending with the base filename
    base = "median_sale_price.csv"
    for name in norm:
        if name.lower().endswith("/" + base) or name.lower().endswith(base):
            return name
    return None

def _list_dataset_files(api):
    """Return a list of file names inside the dataset."""
    log(f"Listing files for Kaggle dataset '{DATASET}' …")
    meta = api.dataset_list_files(DATASET)
    names = [f.ref for f in meta.files] if hasattr(meta, "files") else []
    if not names:
        warn("No files listed by Kaggle; dataset may be unavailable.")
    else:
        log(f"Dataset contains {len(names)} files (showing first 10): {names[:10]}")
    return names

def _download_exact_file(api, member_name, dest_dir):
    """
    Try Kaggle single-file download (creates a .zip). Return path to extracted CSV.
    Raise on failure so caller can try full-dataset download.
    """
    log(f"Downloading single file from Kaggle: '{member_name}' …")
    api.dataset_download_file(DATASET, file_name=member_name, path=dest_dir, force=True, quiet=False)
    # Kaggle writes a zip next to it; name may be either <basename>.zip or <fullpath>.zip
    zip_guess = os.path.join(dest_dir, os.path.basename(member_name) + ".zip")
    if not os.path.exists(zip_guess):
        zips = [os.path.join(dest_dir, f) for f in os.listdir(dest_dir) if f.endswith(".zip")]
        if not zips:
            raise FileNotFoundError("Single-file download zip not found after Kaggle download.")
        zip_guess = max(zips, key=os.path.getmtime)

    with zipfile.ZipFile(zip_guess, "r") as zf:
        names = zf.namelist()
        # prefer exact member path
        target = member_name if member_name in names else None
        if not target:
            base = os.path.basename(member_name)
            picks = [n for n in names if n.lower().endswith("/" + base.lower()) or n.lower().endswith(base.lower())]
            if picks:
                target = picks[0]
        if not target:
            raise FileNotFoundError(f"Expected '{member_name}' not in zip. Members sample: {names[:10]}")
        os.makedirs(CACHE_DIR, exist_ok=True)
        out_path = os.path.join(CACHE_DIR, "median_sale_price.csv")
        log(f"Extracting '{target}' → {out_path}")
        with zf.open(target) as src, open(out_path, "wb") as out:
            shutil.copyfileobj(src, out)

    try: os.remove(zip_guess)
    except: pass

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise FileNotFoundError("CSV write failed after single-file extraction.")
    return out_path

def _download_full_dataset(api, dest_dir):
    """
    Download & unzip the entire dataset, then locate median_sale_price.csv
    and copy it to CACHE_PATH. Return CACHE_PATH or raise on failure.
    """
    log("Single-file download failed; downloading full dataset …")
    api.dataset_download_files(DATASET, path=dest_dir, force=True, quiet=False, unzip=True)
    # Search recursively for the CSV
    candidates = []
    for root, _, files in os.walk(dest_dir):
        for f in files:
            path = os.path.join(root, f)
            rel  = os.path.relpath(path, dest_dir).replace("\\", "/")
            if _find_candidate_name([rel]):
                candidates.append(path)
    if not candidates:
        raise FileNotFoundError("Full-dataset unzip complete, but median_sale_price.csv not found.")
    # Pick best match (first by our priority fn)
    best_rel = _find_candidate_name([os.path.relpath(p, dest_dir).replace("\\", "/") for p in candidates])
    best = None
    for p in candidates:
        if os.path.relpath(p, dest_dir).replace("\\", "/") == best_rel:
            best = p; break
    if best is None:
        best = candidates[0]
    os.makedirs(CACHE_DIR, exist_ok=True)
    shutil.copyfile(best, CACHE_PATH)
    log(f"Copied '{best}' → {CACHE_PATH}")
    return CACHE_PATH

def _ensure_csv_on_disk():
    """Ensure CACHE_PATH exists, using auto-discovery & robust fallbacks."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 0:
        log(f"Using cached CSV: {CACHE_PATH}")
        return os.path.abspath(CACHE_PATH)

    api = _authenticate_kaggle()
    names = _list_dataset_files(api)
    if not names:
        # as a last resort, try full dataset right away
        return _download_full_dataset(api, CACHE_DIR)

    candidate = _find_candidate_name(names)
    if not candidate:
        warn("Did not find a matching median_sale_price.csv in file list; trying full dataset.")
        return _download_full_dataset(api, CACHE_DIR)

    # Try single-file download first; if it 404s, fall back to full dataset
    try:
        return _download_exact_file(api, candidate, CACHE_DIR)
    except Exception as e:
        warn(f"Single-file download failed ({e}); trying full dataset …")
        return _download_full_dataset(api, CACHE_DIR)

def redfin_zip_trend(zip_code: str):
    """
    Compute median, YoY, and 5-year CAGR for a ZIP using the Kaggle dataset.
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

# Tiny CLI for quick testing: python trends.py 30009
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python trends.py <ZIP>")
        sys.exit(1)
    zip_arg = re.sub(r"\D", "", sys.argv[1]) or sys.argv[1]
    print(json.dumps(redfin_zip_trend(zip_arg), indent=2))