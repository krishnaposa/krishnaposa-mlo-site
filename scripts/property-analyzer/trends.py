# trends.py
import io, requests, pandas as pd

from constants import REDFIN_MEDIAN_CSV, UA_STR
from utils import warn

def redfin_zip_trend(zip_code: str):
    try:
        r = requests.get(REDFIN_MEDIAN_CSV, headers={"User-Agent": UA_STR, "Accept": "text/csv"}, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        warn(f"CSV load error: {e}")
        return {"error":"csv_load"}

    need = {"region_type","region","period_end","median_sale_price"}
    if not need.issubset(df.columns):
        return {"columns": list(df.columns)[:20]}

    z = df[(df.region_type=="zip") & (df.region.astype(str)==str(zip_code))].copy()
    if z.empty:
        warn(f"No ZIP data for {zip_code}")
        return {"zip":zip_code, "found":False}

    z["period_end"]=pd.to_datetime(z["period_end"]); z=z.sort_values("period_end")
    latest=z.iloc[-1]
    latest_price=float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
    latest_date=str(latest["period_end"].date())

    yoy=None; cagr5=None
    if len(z)>12:
        prev=float(z.iloc[-13]["median_sale_price"]) if pd.notna(z.iloc[-13]["median_sale_price"]) else None
        if latest_price and prev: yoy=(latest_price-prev)/prev
    if len(z)>60:
        prev5=float(z.iloc[-61]["median_sale_price"]) if pd.notna(z.iloc[-61]["median_sale_price"]) else None
        if latest_price and prev5 and prev5>0: cagr5=(latest_price/prev5)**(1/5)-1

    return {
        "zip": str(zip_code),
        "latest_period_end": latest_date,
        "median_sale_price_latest": latest_price,
        "median_sale_price_yoy": round(yoy,4) if yoy is not None else None,
        "median_sale_price_cagr_5y": round(cagr5,4) if cagr5 is not None else None,
        "observations": int(len(z))
    }