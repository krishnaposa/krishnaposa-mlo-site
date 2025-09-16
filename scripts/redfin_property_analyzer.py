#!/usr/bin/env python3
"""
Redfin-only analyzer
- URL resolution order: --redfin-url → DuckDuckGo → Redfin Autocomplete JSON
- No homepage automation (avoids "Oops!" popup)
- Scrapes property page: window globals + JSON network calls + DOM heuristics
- Defensive math when scrape fails
"""

import re, json, time, random
import requests
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/124.0")
UA_HDRS = {"User-Agent": UA_STR, "Accept-Language": "en-US,en;q=0.9"}
REDFIN_MEDIAN_CSV = "https://redfin-public-data.s3.us-west-2.amazonaws.com/housing-market-data/market-tracker/median_sale_price.csv"

# ---------------- logging ----------------
def log(s):  print(f"[INFO] {s}", flush=True)
def warn(s): print(f"[WARN] {s}", flush=True)

# ---------------- utils ----------------
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
    # sanity: monthly HOA rarely exceeds $5000; ignore zeros / negatives / absurd
    if v <= 0 or v > 5000:
        return None
    return v

# ---------------- URL resolution ----------------
def redfin_url_via_ddg(address: str) -> str | None:
    """Try DuckDuckGo; unwrap uddg redirect; return first /home/<id> link."""
    queries = [
        f"site:redfin.com {address} home",
        f"{address} site:redfin.com/home",
        f"{address} Redfin home details",
        f"site:redfin.com address {address}",
    ]
    for q in queries:
        log(f"DDG query: {q}")
        try:
            r = requests.get(
                "https://duckduckgo.com/html/",
                params={"q": q, "kl": "us-en"},
                headers={"User-Agent": UA_STR},
                timeout=20
            )
            r.raise_for_status()
        except Exception as e:
            warn(f"DDG error: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a"):
            href = a.get("href") or ""
            m = re.search(r"[?&]uddg=([^&]+)", href)
            if m:
                from urllib.parse import unquote
                href = unquote(m.group(1))
            if re.match(r"^https?://(?:www|m)\.redfin\.com/.+/home/\d+", href, re.I):
                log(f"DDG found Redfin property URL: {href}")
                return href

    warn("DDG did not return a Redfin property link.")
    return None

def _redfin_strip_json_prefix(text: str) -> str:
    # Redfin JSON often starts with )]}'
    return re.sub(r"^\)\]\}'\s*", "", text or "")

def redfin_url_via_autocomplete(address: str) -> str | None:
    """
    Call Redfin's public autocomplete JSON to get a property link.
    This avoids UI and 'Oops!' modal.
    """
    ep = "https://www.redfin.com/stingray/do/location-autocomplete"
    params = {"location": address, "v": 2, "market": "true"}
    log(f"Autocomplete: GET {ep} …")
    try:
        r = requests.get(ep, params=params, headers=UA_HDRS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        warn(f"Autocomplete HTTP error: {e}")
        return None

    txt = _redfin_strip_json_prefix(r.text)
    try:
        j = json.loads(txt)
    except Exception as e:
        warn(f"Autocomplete JSON parse error: {e}")
        return None

    # Walk response to find URLs
    def _walk_urls(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() == "url" and isinstance(v, str):
                    yield v
                else:
                    yield from _walk_urls(v)
        elif isinstance(node, list):
            for it in node:
                yield from _walk_urls(it)

    for url in _walk_urls(j):
        if "/home/" in url:
            full = url if url.startswith("http") else ("https://www.redfin.com" + url)
            log(f"Autocomplete found property URL: {full}")
            return full

    warn("Autocomplete returned no property URL.")
    return None

def resolve_redfin_url(address: str, redfin_url_cli: str | None) -> str | None:
    if redfin_url_cli:
        log("Using --redfin-url (skipping search).")
        return redfin_url_cli
    url = redfin_url_via_ddg(address)
    if url: return url
    log("Falling back to Redfin autocomplete…")
    return redfin_url_via_autocomplete(address)

# ---------------- property page capture ----------------
def _extract_globals(page):
    keys = ["__NEXT_DATA__", "__REDUX_STATE__", "__APOLLO_STATE__",
            "__PREFETCHED_QUERIES__", "__RF_PAGE_DATA__", "__INITIAL_STATE__"]
    out = {}
    for k in keys:
        try:
            val = page.evaluate(f"() => window.{k}")
            if val:
                out[k] = val
                log(f"Captured window global: {k}")
        except Exception:
            pass
    return out

def _extract_from_dom(html):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    next_data = json.loads(tag.string) if tag and tag.string else None
    if next_data: log("Found embedded __NEXT_DATA__ in DOM.")

    text = soup.get_text(" ", strip=True)
    hoa = None
    tax_annual = None

    m = re.search(r"\bHOA[^$]*\$\s*([0-9,]+)\s*(?:/mo|per month|monthly)?", text, re.I)
    if m:
        hoa = normalize_hoa(m.group(1))
        if hoa is not None: log(f"Heuristic HOA parsed from DOM: {hoa}")

    m = re.search(r"(?:Property\s+tax(?:es)?|Annual\s+tax)[^$]*\$\s*([0-9,]+)", text, re.I)
    if m:
        tax_annual = _to_float(m.group(1))
        if tax_annual is not None: log(f"Heuristic property tax parsed from DOM: {tax_annual}")

    return {"__NEXT_DATA__": next_data, "heuristic": {"hoa": hoa, "tax_annual": tax_annual}}

def fetch_redfin_data_smart(url: str, *, headless=True, slow_mo=0, timeout_ms=45000):
    """
    Loads a *property page* and captures:
      - window globals
      - JSON network responses (GraphQL / stingray / api)
      - DOM heuristics (HOA / taxes)
    """
    caps = {"globals": {}, "network_json": [], "dom": None}
    log(f"Loading property page: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = browser.new_context(
            viewport={"width":1366,"height":900},
            user_agent=UA_STR,
            locale="en-US"
        )
        ctx.set_default_timeout(timeout_ms)
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "")
                if "application/json" not in ct:
                    return
                ul = resp.url.lower()
                if "redfin.com" in ul or "graphql" in ul or "stingray" in ul or "api" in ul:
                    j = resp.json()
                    if isinstance(j, (dict, list)):
                        caps["network_json"].append({"url": resp.url, "json": j})
                        if len(caps["network_json"]) <= 3:
                            log(f"Captured JSON response: {resp.url}")
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded")

        # Nudge lazy data
        for _ in range(3):
            page.mouse.wheel(0, 1500)
            time.sleep(random.uniform(0.2, 0.5))

        caps["globals"] = _extract_globals(page)
        caps["dom"]     = _extract_from_dom(page.content())

        try:
            page.screenshot(path="redfin_debug.png", full_page=True)
            log("Saved screenshot: redfin_debug.png")
        except Exception:
            pass

        browser.close()

    # ---- Mine values ----
    address_parts = {}
    hoa=None; tax_annual=None; last_price=None

    wanted = {
        # address variants
        "address","streetline","streetline1","line1","street","streetaddress",
        "city","state","zipcode","zip","postalcode",
        # fields
        "monthlyhoa","hoadues","propertytax","lastsaleprice","price"
    }

    candidates = []
    for v in (caps["globals"] or {}).values():
        if v: candidates.append(v)
    if caps["dom"] and caps["dom"].get("__NEXT_DATA__"):
        candidates.append(caps["dom"]["__NEXT_DATA__"])
    for it in caps["network_json"]:
        candidates.append(it["json"])

    log(f"Mining {len(candidates)} JSON blob(s) for keys…")
    for blob in candidates:
        try:
            hits = _deep_find_keys(blob, wanted)

            # Address
            street = (_clean_str(hits.get("streetline")) or _clean_str(hits.get("streetline1"))
                      or _clean_str(hits.get("line1")) or _clean_str(hits.get("street"))
                      or _clean_str(hits.get("streetaddress")) or _clean_str(hits.get("address")))
            city   = _clean_str(hits.get("city"))
            state  = _clean_str(hits.get("state"))
            zipc   = _clean_str(hits.get("zipcode") or hits.get("zip") or hits.get("postalcode"))
            if any([street,city,state,zipc]) and not address_parts:
                address_parts = {"street": street, "city": city, "state": state, "zip": zipc}
                log(f"Address parsed: {address_parts}")

            # HOA
            if hoa is None:
                hoa = normalize_hoa(hits.get("monthlyhoa") or hits.get("hoadues"))
                if hoa is not None: log(f"HOA (from JSON): {hoa}")

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
                if tax_annual is not None: log(f"Property tax (from JSON): {tax_annual}")

            # Price
            if last_price is None:
                p = hits.get("lastsaleprice") or hits.get("price")
                if isinstance(p, dict) and "amount" in p:
                    last_price = _to_float(p["amount"])
                else:
                    pv = _to_float(p)
                    if pv is not None: last_price = pv
                if last_price is not None: log(f"Price (from JSON): {last_price}")
        except Exception:
            continue

    heur = (caps["dom"] or {}).get("heuristic") or {}
    if hoa is None and heur.get("hoa") is not None:
        hoa = heur["hoa"]; log(f"HOA (heuristic fallback): {hoa}")
    if tax_annual is None and heur.get("tax_annual") is not None:
        tax_annual = heur["tax_annual"]; log(f"Property tax (heuristic fallback): {tax_annual}")

    estimates = {
        "hoa_monthly": hoa if hoa is not None else None,
        "property_tax_annual": tax_annual if tax_annual is not None else None,
        "suggested_price": last_price,
        "insurance_monthly": 100  # baseline
    }
    ok = bool(address_parts) or any([hoa, tax_annual, last_price])

    log(f"Capture summary → globals:{len([v for v in (caps['globals'] or {}).values() if v])} "
        f"network_json:{len(caps['network_json'])} ok:{ok}")

    return {"ok": ok, "url": url, "address_parts": address_parts, "estimates": estimates}

# ---------------- top-level parse ----------------
def parse_property(url: str, *, headless=True):
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

# ---------------- misc ----------------
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

# ---------------- main analysis ----------------
def analyze(address: str, redfin_url_cli: str|None, price: float, down_pct: float, rate_pct: float, years: int,
            tax_annual: float|None=None, ins_annual: float|None=None, hoa_monthly: float|None=None,
            maint_pct: float=1.0, vacancy_pct: float=5.0, rent_monthly: float|None=None,
            *, headless=True):
    t0=time.time()

    url = resolve_redfin_url(address, redfin_url_cli)
    if not url:
        return {"ok":False, "error":"redfin_url_not_found",
                "hint":"Provide --redfin-url with a property link.",
                "input_address":address}

    prop = parse_property(url, headless=headless)

    # Defensive: property_details may not exist if scraping failed
    prop_details = (prop.get("property_details") if isinstance(prop, dict) else None) or {}
    parts = (prop.get("address_parts") if isinstance(prop, dict) else None) or {}

    z = parts.get("zip") or extract_zip_from_any(prop.get("address_text")) or extract_zip_from_any(address)
    market = redfin_zip_trend(z) if z else {"error":"no_zip"}

    # Expenses (defensive fallbacks)
    dp = price*down_pct/100
    pi = mortgage_pi(price, dp, rate_pct, years)
    tax_m = (tax_annual/12) if tax_annual is not None else ((prop_details.get("property_tax_annual") or 0)/12)
    ins_m = (ins_annual/12) if ins_annual is not None else 100
    hoa_m = hoa_monthly if hoa_monthly is not None else (prop_details.get("hoa_monthly") or 0)
    maint_m = price*(maint_pct/100)/12
    vac_m = (rent_monthly or 0)*(vacancy_pct/100)
    op_ex = round(tax_m + ins_m + hoa_m + maint_m + vac_m, 2)

    cashflow = noi = cap_rate = coc = None
    if rent_monthly is not None:
        cashflow = round(rent_monthly - (pi + op_ex), 2)
        noi = round((rent_monthly - vac_m) * 12 - (tax_m + ins_m + hoa_m + maint_m)*12, 2)
        cap_rate = round(noi/price*100, 2) if price else None
        coc = round((cashflow*12)/dp * 100, 2) if dp>0 else None

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
            "Resolver order: --redfin-url → DuckDuckGo → Redfin Autocomplete JSON.",
            "Property page scraped via globals + network JSON + DOM heuristics.",
            "Math is defensive if scrape fails (fields default to 0 unless overridden).",
            "Insurance defaults to $100/mo if not provided.",
            "Provide rent_monthly to compute cash flow, cap rate, and CoC."
        ]
    }

# ---------------- CLI ----------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Redfin-only analyzer with DDG + Autocomplete fallback and verbose logging.")
    ap.add_argument("address", help="Street, City, State ZIP")
    ap.add_argument("--redfin-url", default=None, help="Known Redfin property URL to skip search.")
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
    ap.add_argument("--headful", action="store_true", help="Show browser when scraping the property page.")
    args = ap.parse_args()

    res = analyze(
        address=args.address, redfin_url_cli=args.redfin_url, price=args.price, down_pct=args.down_pct,
        rate_pct=args.rate_pct, years=args.years, tax_annual=args.tax_annual, ins_annual=args.ins_annual,
        hoa_monthly=args.hoa_monthly, maint_pct=args.maintenance_pct, vacancy_pct=args.vacancy_pct,
        rent_monthly=args.rent_monthly, headless=not args.headful
    )
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()