#!/usr/bin/env python3
"""
Redfin-only analyzer (robust)
- Resolve property URL: DDG -> on-site search (Playwright) fallback
- Scrape: window globals, network JSON, DOM heuristics
- Normalize HOA & taxes; compute simple ROI metrics
"""

import os, re, json, sys, time, random
import requests
import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/124.0")
UA_HDRS = {"User-Agent": UA_STR, "Accept-Language":"en-US,en;q=0.9"}
REDFIN_MEDIAN_CSV = "https://redfin-public-data.s3.us-west-2.amazonaws.com/housing-market-data/market-tracker/median_sale_price.csv"

# ---------- logging ----------
def log(s):  print(f"[INFO] {s}", flush=True)
def warn(s): print(f"[WARN] {s}", flush=True)

# ---------- utils ----------
def _to_float(x):
    if x is None: return None
    try:
        return float(re.sub(r"[^\d.\-]", "", str(x)))
    except Exception:
        return None

def _clean_str(x):
    if x is None: return None
    s = str(x).strip()
    return s or None

def _deep_find_keys(obj, keys_lower:set[str]):
    out = {}
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                kl = str(k).lower()
                if kl in keys_lower and kl not in out:
                    out[kl] = v
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return out

def normalize_hoa(val):
    v = _to_float(val)
    if v is None: return None
    # sanity: monthly HOA rarely exceeds $1500; ignore insane values or zeros
    if v <= 0 or v > 5000: 
        return None
    return v

# ---------- DDG resolver (first try) ----------
def redfin_url_via_ddg(address: str) -> str | None:
    queries = [
        f"site:redfin.com {address} home",
        f"{address} site:redfin.com/home",
        f"{address} Redfin home details",
        f"site:redfin.com address {address}",
    ]
    for q in queries:
        log(f"DDG query: {q}")
        try:
            r = requests.get("https://duckduckgo.com/html/", params={"q": q, "kl":"us-en"},
                             headers={"User-Agent": UA_STR}, timeout=20)
            r.raise_for_status()
        except Exception as e:
            warn(f"DDG error: {e}"); continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a"):
            href = a.get("href") or ""
            m = re.search(r"[?&]uddg=([^&]+)", href)
            if m:
                from urllib.parse import unquote
                href = unquote(m.group(1))
            if re.match(r"^https?://(?:www|m)\.redfin\.com/.+/home/\d+", href, re.I):
                log(f"DDG found: {href}")
                return href
    warn("No Redfin property URL found via DDG.")
    return None

# ---------- on-site resolver (fallback / most reliable) ----------

def redfin_url_via_site(address: str, *, headless=True, slow_mo=50, timeout_ms=45000) -> str | None:
    """
    Drive redfin.com to resolve a property page for the given address.
    - Types into the homepage search
    - If we land on a results page, click the first card that links to /home/
    - Returns final property URL or None
    """
    import re, time, random
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = browser.new_context(
            viewport={"width":1366,"height":900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/124.0"),
            locale="en-US"
        )
        page = ctx.new_page()
        try:
            page.goto("https://www.redfin.com/", wait_until="domcontentloaded", timeout=timeout_ms)

            # dismiss cookie banners (best effort)
            for sel in ["button:has-text('Accept')","button:has-text('I agree')",
                        "button[aria-label='Accept all']","button:has-text('Got it')"]:
                try:
                    if page.locator(sel).first.is_visible():
                        page.locator(sel).first.click()
                        break
                except Exception:
                    pass

            # homepage search box (avoid strict-mode violation by picking .first)
            box = page.locator("input#search-box-input").first
            box.fill(address)
            time.sleep(random.uniform(0.25, 0.6))

            # try autocomplete; if none, press Enter
            ac = page.locator(".autoCompleteRow").first
            try:
                ac.wait_for(state="visible", timeout=3000)
                ac.click()
            except PWTimeout:
                box.press("Enter")

            # 1) happy path: we land directly on a property page
            try:
                page.wait_for_url(re.compile(r".*/home/\d+.*"), timeout=timeout_ms)
                return page.url
            except PWTimeout:
                pass  # probably on a results page

            # 2) results page: click the first card that links to /home/
            # try a few common link patterns new/old UI
            selectors = [
                "a[href*='/home/']",
                "a.HomeCardContainer, a.coverAll",
                "[data-rf-test-id='home-card'] a[href*='/home/']",
            ]
            for sel in selectors:
                try:
                    link = page.locator(sel).first
                    link.wait_for(state="visible", timeout=6000)
                    # ensure the href really points to a property
                    href = link.get_attribute("href") or ""
                    if "/home/" not in href:
                        link.click()  # may still navigate to details
                    else:
                        page.goto(href, wait_until="domcontentloaded")
                    page.wait_for_url(re.compile(r".*/home/\d+.*"), timeout=timeout_ms)
                    return page.url
                except PWTimeout:
                    continue
                except Exception:
                    continue

            # 3) last chance: if any /home/ link exists, navigate to it directly
            try:
                hrefs = page.eval_on_selector_all("a[href*='/home/']", "els => els.map(e => e.href)")
                for u in hrefs or []:
                    if re.search(r"/home/\d+", u):
                        page.goto(u, wait_until="domcontentloaded")
                        page.wait_for_url(re.compile(r".*/home/\d+.*"), timeout=timeout_ms)
                        return page.url
            except Exception:
                pass

            return None
        except Exception as e:
            warn(f"Site resolver failed: {e}")
            return None
        finally:
            browser.close()
# ---------- page capture ----------
def _extract_globals(page):
    keys = ["__NEXT_DATA__", "__REDUX_STATE__", "__APOLLO_STATE__", "__PREFETCHED_QUERIES__", "__RF_PAGE_DATA__", "__INITIAL_STATE__"]
    out={}
    for k in keys:
        try:
            val = page.evaluate(f"() => window.{k}")
            if val: out[k]=val
        except Exception:
            pass
    return out

def _extract_from_dom(html):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id":"__NEXT_DATA__"})
    next_data = json.loads(tag.string) if tag and tag.string else None

    text = soup.get_text(" ", strip=True)
    hoa=None; tax_annual=None
    m = re.search(r"\bHOA[^$]*\$\s*([0-9,]+)\s*(?:/mo|per month|monthly)?", text, re.I)
    if m: hoa = normalize_hoa(m.group(1))
    m = re.search(r"(?:Property\s+tax(?:es)?|Annual\s+tax)[^$]*\$\s*([0-9,]+)", text, re.I)
    if m: tax_annual = _to_float(m.group(1))
    return {"__NEXT_DATA__": next_data, "heuristic": {"hoa": hoa, "tax_annual": tax_annual}}

def fetch_redfin_data_smart(url: str, *, headless=False, slow_mo=60, timeout_ms=45000):
    caps = {"globals":{}, "network_json":[], "dom":None}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = browser.new_context(viewport={"width":1366,"height":900}, user_agent=UA_STR, locale="en-US")
        ctx.set_default_timeout(timeout_ms)
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type","")
                if "application/json" not in ct: return
                u = resp.url.lower()
                if "redfin.com" in u or "graphql" in u or "stingray" in u or "api" in u:
                    j = resp.json()
                    if isinstance(j,(dict,list)):
                        caps["network_json"].append({"url":resp.url,"json":j})
            except Exception:
                pass
        page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded")

        for sel in ["button:has-text('Accept')","button:has-text('I agree')","button[aria-label='Accept all']","button:has-text('Got it')"]:
            try:
                if page.locator(sel).first.is_visible():
                    page.locator(sel).first.click(); time.sleep(0.3); break
            except Exception:
                pass

        for _ in range(3):
            page.mouse.wheel(0, 1700); time.sleep(random.uniform(0.25,0.6))

        caps["globals"] = _extract_globals(page)
        caps["dom"]     = _extract_from_dom(page.content())
        try: page.screenshot(path="redfin_debug.png", full_page=True)
        except Exception: pass
        browser.close()

    # Mine values from all blobs
    address_parts = {}
    hoa=None; tax_annual=None; last_price=None

    wanted = {
        # address variants
        "address","streetline","streetline1","line1","street","streetaddress",
        "city","state","zipcode","zip","postalcode",
        # fields
        "monthlyhoa","hoadues","propertytax","lastsaleprice","price"
    }
    candidates=[]
    for v in (caps["globals"] or {}).values():
        if v: candidates.append(v)
    if caps["dom"] and caps["dom"].get("__NEXT_DATA__"):
        candidates.append(caps["dom"]["__NEXT_DATA__"])
    for it in caps["network_json"]:
        candidates.append(it["json"])

    for blob in candidates:
        try:
            hits = _deep_find_keys(blob, wanted)
            # Address
            street = (_clean_str(hits.get("streetline")) or _clean_str(hits.get("streetline1"))
                      or _clean_str(hits.get("line1")) or _clean_str(hits.get("street"))
                      or _clean_str(hits.get("streetaddress")) or _clean_str(hits.get("address")))
            city = _clean_str(hits.get("city"))
            state = _clean_str(hits.get("state"))
            zipc = _clean_str(hits.get("zipcode") or hits.get("zip") or hits.get("postalcode"))
            if any([street,city,state,zipc]) and not address_parts:
                address_parts = {"street": street, "city": city, "state": state, "zip": zipc}

            # HOA
            if hoa is None:
                hoa = normalize_hoa(hits.get("monthlyhoa") or hits.get("hoadues"))

            # Taxes
            if tax_annual is None:
                t = hits.get("propertytax")
                if isinstance(t, dict):
                    for k in ("amount","annual","value"):
                        if k in t:
                            tax_annual = _to_float(t[k]); break
                else:
                    tv = _to_float(t)
                    if tv is not None: tax_annual = tv

            # Price
            if last_price is None:
                p = hits.get("lastsaleprice") or hits.get("price")
                if isinstance(p, dict) and "amount" in p:
                    last_price = _to_float(p["amount"])
                else:
                    pv = _to_float(p)
                    if pv is not None: last_price = pv
        except Exception:
            continue

    # DOM fallbacks
    heur = (caps["dom"] or {}).get("heuristic") or {}
    if hoa is None and heur.get("hoa") is not None: hoa = heur["hoa"]
    if tax_annual is None and heur.get("tax_annual") is not None: tax_annual = heur["tax_annual"]

    estimates = {
        "hoa_monthly": hoa if hoa is not None else None,
        "property_tax_annual": tax_annual if tax_annual is not None else None,
        "suggested_price": last_price,
        "insurance_monthly": 100  # baseline; tune per state if desired
    }
    ok = bool(address_parts) or any([hoa, tax_annual, last_price])
    return {"ok": ok, "url": url, "address_parts": address_parts, "estimates": estimates, "captures": {"counts": {
        "globals": len([v for v in (caps["globals"] or {}).values() if v]),
        "network_json": len(caps["network_json"])
    }}}

# ---------- top-level parse ----------
def parse_property(url: str, *, headless=False):
    smart = fetch_redfin_data_smart(url, headless=headless)
    if not smart.get("ok"):
        return {"error":"no_data_from_redfin", "redfin_url": url}
    parts = smart.get("address_parts") or {}
    est   = smart.get("estimates") or {}
    full = ", ".join([s for s in [parts.get("street"), parts.get("city"), parts.get("state"), parts.get("zip")] if s])
    return {
        "address_text": full or None,
        "address_parts": parts,
        "geo": {},
        "property_details": {
            "hoa_monthly": est.get("hoa_monthly"),
            "property_tax_annual": est.get("property_tax_annual"),
            "last_sale_price": est.get("suggested_price"),
        }
    }

# ---------- misc ----------
def extract_zip_from_any(s: str):
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", s or "")
    return m.group(1) if m else None

def redfin_zip_trend(zip_code: str):
    try:
        df = pd.read_csv(REDFIN_MEDIAN_CSV)
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

def mortgage_pi(price, down, rate_pct, years):
    loan = price - down
    r = rate_pct/100/12
    n = years*12
    pmt = loan * r * (1+r)**n / ((1+r)**n - 1)
    return round(pmt,2)

# ---------- main analysis ----------
def analyze(address: str, redfin_url: str|None, price: float, down_pct: float, rate_pct: float, years: int,
            tax_annual: float|None=None, ins_annual: float|None=None, hoa_monthly: float|None=None,
            maint_pct: float=1.0, vacancy_pct: float=5.0, rent_monthly: float|None=None,
            *, headless=False):
    t0=time.time()
    url = redfin_url or redfin_url_via_ddg(address) or redfin_url_via_site(address, headless=headless)
    if not url:
        return {"ok":False, "error":"redfin_url_not_found", "input_address":address}

    prop = parse_property(url, headless=headless)
    parts = prop.get("address_parts") or {}
    z = parts.get("zip") or extract_zip_from_any(prop.get("address_text")) or extract_zip_from_any(address)
    market = redfin_zip_trend(z) if z else {"error":"no_zip"}

    # expenses
    dp = price*down_pct/100
    pi = mortgage_pi(price, dp, rate_pct, years)
    tax_m = (tax_annual/12) if tax_annual is not None else ((prop["property_details"].get("property_tax_annual") or 0)/12)
    ins_m = (ins_annual/12) if ins_annual is not None else 100
    hoa_m = hoa_monthly if hoa_monthly is not None else (prop["property_details"].get("hoa_monthly") or 0)
    maint_m = price*(maint_pct/100)/12
    vac_m = (rent_monthly or 0)*(vacancy_pct/100)
    op_ex = round(tax_m + ins_m + hoa_m + maint_m + vac_m, 2)

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
            "URL resolution: DDG -> on-site Redfin search fallback.",
            "Scrape uses window globals + network JSON + DOM heuristics.",
            "Insurance defaults to $100/mo if not provided.",
            "Provide rent_monthly to compute cash flow, cap rate, and CoC."
        ]
    }

# ---------- CLI ----------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Redfin-only analyzer with robust scraping.")
    ap.add_argument("address", help="Street, City, State ZIP")
    ap.add_argument("--redfin-url", default=None, help="Pass a known Redfin property URL to skip search.")
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
    ap.add_argument("--headful", action="store_true", help="Show browser (debug). Default is headless.")
    args = ap.parse_args()

    res = analyze(
        address=args.address, redfin_url=args.redfin_url, price=args.price, down_pct=args.down_pct,
        rate_pct=args.rate_pct, years=args.years, tax_annual=args.tax_annual, ins_annual=args.ins_annual,
        hoa_monthly=args.hoa_monthly, maint_pct=args.maintenance_pct, vacancy_pct=args.vacancy_pct,
        rent_monthly=args.rent_monthly, headless=not args.headful
    )
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()