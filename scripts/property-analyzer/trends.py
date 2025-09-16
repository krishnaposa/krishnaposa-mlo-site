# trends.py
import io, zipfile, tempfile, pathlib
import pandas as pd
from utils import warn, log

# Hardcoded Kaggle dataset + file
KAGGLE_DATASET = "redfin/usa-housing-market"
KAGGLE_FILENAME = "market-tracker/median_sale_price.csv"

def _fetch_via_kaggle() -> str | None:
    try:
        from kaggle import api as kaggle_api
    except Exception as e:
        warn(f"Kaggle package not installed. Run `pip install kaggle`. ({e})")
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            log(f"Kaggle: downloading {KAGGLE_FILENAME} from {KAGGLE_DATASET}")
            kaggle_api.dataset_download_file(
                KAGGLE_DATASET, KAGGLE_FILENAME, path=tmpdir, force=True, quiet=True
            )
        except Exception as e:
            warn(f"Kaggle download failed: {e}")
            return None

        raw = pathlib.Path(tmpdir) / KAGGLE_FILENAME
        zipped = pathlib.Path(tmpdir) / (KAGGLE_FILENAME + ".zip")

        if zipped.exists():
            with zipfile.ZipFile(zipped, "r") as zf:
                names = zf.namelist()
                if not names:
                    return None
                with zf.open(names[0]) as f:
                    return f.read().decode("utf-8")

        if raw.exists():
            return raw.read_text(encoding="utf-8")

    return None


def redfin_zip_trend(zip_code: str):
    text = _fetch_via_kaggle()
    if text is None:
        return {"error": "csv_load"}

    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as e:
        warn(f"CSV parse error: {e}")
        return {"error": "csv_load"}

    required = {"region_type", "region", "period_end", "median_sale_price"}
    if not required.issubset(df.columns):
        return {"columns": list(df.columns)[:20]}

    z = df[(df.region_type == "zip") & (df.region.astype(str) == str(zip_code))].copy()
    if z.empty:
        warn(f"No ZIP data for {zip_code}")
        return {"zip": str(zip_code), "found": False}

    z["period_end"] = pd.to_datetime(z["period_end"])
    z = z.sort_values("period_end")

    latest = z.iloc[-1]
    latest_price = float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
    latest_date = str(latest["period_end"].date())

    yoy, cagr5 = None, None
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