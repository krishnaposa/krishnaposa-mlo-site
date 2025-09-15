#!/usr/bin/env python3
import os, re, json, sys, time, random
import requests
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dateutil import parser as dtparser

UA = {"User-Agent":"Mozilla/5.0","Accept-Language":"en-US,en;q=0.9"}
BING_KEY = os.environ.get("BING_SEARCH_KEY")
BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
REDFIN_MEDIAN_CSV = "https://redfin-public-data.s3.us-west-2.amazonaws.com/housing-market-data/market-tracker/median_sale_price.csv"
    
def log(s): print(f"[INFO] {s}", flush=True)
def warn(s): print(f"[WARN] {s}", flush=True)

def extract_redfin_json_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    return json.loads(tag.string) if tag and tag.string else None

def fetch_redfin_json_playwright(url: str) -> dict | None:
    with sync_playwright() as p:
        # headful helps avoid bot flags; slow_mo adds human-like pacing
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/124.0"),
            locale="en-US"
        )
        page = context.new_page()
        # small random delay before navigation
        time.sleep(random.uniform(0.4, 1.1))
        page.goto(url, wait_until="domcontentloaded")
        # wait for network to settle; adjust if your network is slow
        page.wait_for_load_state("networkidle")
        # optional: scroll a bit to trigger lazy content
        page.mouse.wheel(0, 1200); time.sleep(0.5)
        html = page.content()
        # save artifacts for debugging
        page.screenshot(path="redfin_page.png", full_page=True)
        browser.close()
    return extract_redfin_json_from_html(html)
    
def redfin_url_via_ddg(address: str) -> str | None:
    """
    Search DuckDuckGo for a Redfin property URL from an address.
    Returns the first matching Redfin /home/ link.
    """
    q = f"site:redfin.com {address}"
    try:
        r = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": q},
            headers={"User-Agent":"Mozilla/5.0"},
            timeout=15
        )
        r.raise_for_status()
    except Exception as e:
        print(f"[WARN] DuckDuckGo request failed: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Look at result links
    for a in soup.select("a.result__a"):
        url = a.get("href") or ""
        if "redfin.com" in url and "/home/" in url:
            return url
        # Sometimes wrapped in redirect: /l/?kh=-1&uddg=<encoded>
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            from urllib.parse import unquote
            real = unquote(m.group(1))
            if "redfin.com" in real and "/home/" in real:
                return real
    return None
    
def bing_redfin_url(address: str):
    if not BING_KEY: 
        warn("BING_SEARCH_KEY not set; please pass a Redfin URL manually if lookup fails.")
        return None
    q = f"site:redfin.com {address}"
    log(f"Searching Bing: {q}")
    r = requests.get(BING_ENDPOINT, params={"q":q,"count":10,"mkt":"en-US"},
                     headers={"Ocp-Apim-Subscription-Key":BING_KEY}, timeout=15)
    r.raise_for_status()
    for it in (r.json().get("webPages",{}) or {}).get("value",[]) or []:
        url = it.get("url","")
        if "redfin.com" in url and "/home/" in url:
            log(f"Found Redfin URL: {url}")
            return url
    warn("No Redfin property URL found.")
    return None

def extract_json_from_redfin(url: str):
    log(f"Fetching Redfin page: {url}")
    r = requests.get(url, headers=UA, timeout=25)
    if r.status_code != 200:
        warn(f"HTTP {r.status_code} from Redfin")
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    tag = soup.find("script", {"id":"__NEXT_DATA__"})
    if not tag or not tag.string:
        warn("__NEXT_DATA__ not found")
        return None
    try:
        return json.loads(tag.string)
    except Exception as e:
        warn(f"JSON parse error: {e}")
        return None

def deep_find_keys(obj, keys_lower:set[str]):
    out={}
    stack=[obj]
    while stack:
        cur=stack.pop()
        if isinstance(cur,dict):
            for k,v in cur.items():
                kl=str(k).lower()
                if kl in keys_lower and kl not in out:
                    out[kl]=v
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(cur,list):
            stack.extend(cur)
        if len(out)==len(keys_lower): break
    return out

def to_float(x):
    try: return float(x)
    except: return None

def parse_property(url: str):
    data = fetch_redfin_json_playwright(url)
    if not data:
        return { "error": "no_redfin_json_playwright", "redfin_url": url}
    if not data: return {"error":"no_redfin_json"}
    wanted = {
        "address","streetline","city","state","zipcode","zip","postalcode",
        "beds","baths","bathsdecimal","sqft","lotsize","yearbuilt",
        "propertytype","monthlyhoa","hoadues","propertytax",
        "lastsaledate","lastsaleprice","price","latitude","longitude"
    }
    hits = deep_find_keys(data, wanted)
    addr = hits.get("address") or hits.get("streetline")
    city = hits.get("city"); state = hits.get("state")
    zipc = hits.get("zipcode") or hits.get("zip") or hits.get("postalcode")
    beds = to_float(hits.get("beds"))
    baths = to_float(hits.get("bathsdecimal") or hits.get("baths"))
    sqft = to_float(hits.get("sqft"))
    lot = to_float(hits.get("lotsize"))
    year_built = hits.get("yearbuilt")
    hoa = hits.get("monthlyhoa") or hits.get("hoadues")
    hoa = to_float(hoa) if hoa is not None else None
    taxes = hits.get("propertytax")
    if isinstance(taxes,dict):
        for k in ("amount","annual","value"):
            if k in taxes: taxes = taxes[k]; break
    taxes = to_float(taxes)
    last_price = hits.get("lastsaleprice") or hits.get("price")
    if isinstance(last_price,dict): last_price = last_price.get("amount")
    last_price = to_float(last_price)
    last_date = hits.get("lastsaledate")
    if isinstance(last_date,str):
        try: last_date = dtparser.parse(last_date).date().isoformat()
        except: pass
    lat = to_float(hits.get("latitude")); lon = to_float(hits.get("longitude"))
    full = ", ".join([s for s in [addr, city, state, zipc] if s])
    return {
        "address_text": full or None,
        "address_parts": {"street":addr, "city":city, "state":state, "zip":zipc},
        "geo": {"lat":lat,"lon":lon},
        "property_details": {
            "beds":beds, "baths":baths, "sqft":sqft, "lot_sqft":lot,
            "year_built":year_built, "property_type":hits.get("propertytype"),
            "hoa_monthly":hoa, "property_tax_annual":taxes,
            "last_sale_price":last_price, "last_sale_date":last_date
        }
    }

def extract_zip_from_any(s: str):
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", s or "")
    return m.group(1) if m else None

def redfin_zip_trend(zip_code: str):
    try:
        df = pd.read_csv(REDFIN_MEDIAN_CSV)
    except Exception as e:
        warn(f"CSV load error: {e}")
        return {"error":"csv_load"}
    if not {"region_type","region","period_end","median_sale_price"}.issubset(df.columns):
        return {"columns": list(df.columns)[:20]}
    z = df[(df.region_type=="zip") & (df.region.astype(str)==str(zip_code))].copy()
    if z.empty:
        warn(f"No ZIP data for {zip_code}")
        return {"zip":zip_code, "found":False}
    z["period_end"]=pd.to_datetime(z["period_end"]); z=z.sort_values("period_end")
    latest=z.iloc[-1]; latest_price=float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
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

def mortgage_pi(price, down, rate_pct, years):
    loan = price - down
    r = rate_pct/100/12
    n = years*12
    pmt = loan * r * (1+r)**n / ((1+r)**n - 1)
    return round(pmt,2)

def analyze(address: str, redfin_url: str|None, price: float, down_pct: float, rate_pct: float, years: int,
            tax_annual: float|None=None, ins_annual: float|None=None, hoa_monthly: float|None=None,
            maint_pct: float=1.0, vacancy_pct: float=5.0, rent_monthly: float|None=None):
    t0=time.time()
    url = redfin_url or redfin_url_via_ddg(address)
    if not url: 
        return {"ok":False, "error":"redfin_url_not_found", "input_address":address}
    prop = parse_property(url)
    z = (prop.get("address_parts",{}) or {}).get("zip") or extract_zip_from_any(prop.get("address_text")) or extract_zip_from_any(address)
    market = redfin_zip_trend(z) if z else {"error":"no_zip"}
    # expenses
    dp = price*down_pct/100
    pi = mortgage_pi(price, dp, rate_pct, years)
    tax_m = (tax_annual/12) if tax_annual is not None else ((prop["property_details"].get("property_tax_annual") or 0)/12)
    ins_m = (ins_annual/12) if ins_annual is not None else 100 # rough default
    hoa_m = hoa_monthly if hoa_monthly is not None else (prop["property_details"].get("hoa_monthly") or 0)
    maint_m = price*(maint_pct/100)/12
    vac_m = (rent_monthly or 0)*(vacancy_pct/100)
    op_ex = round(tax_m + ins_m + hoa_m + maint_m + vac_m, 2)
    # if no rent, leave cashflow incomplete
    cashflow = None; noi=None; cap_rate=None; coc=None
    if rent_monthly is not None:
        cashflow = round(rent_monthly - (pi + op_ex), 2)
        noi = round((rent_monthly - vac_m) * 12 - (tax_m + ins_m + hoa_m + maint_m)*12, 2)
        cap_rate = round(noi/price*100, 2) if price else None
        coc = round((cashflow*12)/(dp) * 100, 2) if dp>0 else None
    return {
        "ok": True,
        "timing_sec": round(time.time()-t0,2),
        "redfin_url": url,
        "input": {
            "address": address, "purchase_price": price, "down_pct": down_pct, "rate_pct": rate_pct, "years": years,
            "tax_annual_override": tax_annual, "ins_annual_override": ins_annual, "hoa_monthly_override": hoa_monthly,
            "maintenance_pct": maint_pct, "vacancy_pct": vacancy_pct, "rent_monthly": rent_monthly
        },
        "property": prop,
        "market_zip": market,
        "finance": {
            "down_payment": round(price*down_pct/100,2),
            "monthly_pi": pi,
            "operating_expenses_monthly": op_ex,
            "cashflow_monthly": cashflow,
            "noi_annual": noi,
            "cap_rate_pct": cap_rate,
            "cash_on_cash_pct": coc
        },
        "notes": [
            "Taxes, HOA from Redfin when available; you can override via CLI args.",
            "Insurance default is 100/month if not provided.",
            "Provide rent_monthly to compute cash flow, cap rate, and CoC."
        ]
    }

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Analyze a property using Redfin + simple ROI math.")
    ap.add_argument("address", help="Street, City, State ZIP")
    ap.add_argument("--redfin-url", help="If you already know it, provide the Redfin property URL.", default=None)
    ap.add_argument("--price", type=float, required=True)
    ap.add_argument("--down-pct", type=float, default=20)
    ap.add_argument("--rate-pct", type=float, default=6.5)
    ap.add_argument("--years", type=int, default=30)
    ap.add_argument("--tax-annual", type=float, default=None)
    ap.add_argument("--ins-annual", type=float, default=None)
    ap.add_argument("--hoa-monthly", type=float, default=None)
    ap.add_argument("--maintenance-pct", type=float, default=1.0)
    ap.add_argument("--vacancy-pct", type=float, default=5.0)
    ap.add_argument("--rent-monthly", type=float, default=None)
    args = ap.parse_args()

    res = analyze(
        address=args.address, redfin_url=args.redfin_url, price=args.price, down_pct=args.down_pct,
        rate_pct=args.rate_pct, years=args.years, tax_annual=args.tax_annual, ins_annual=args.ins_annual,
        hoa_monthly=args.hoa_monthly, maint_pct=args.maintenance_pct, vacancy_pct=args.vacancy_pct,
        rent_monthly=args.rent_monthly
    )
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()