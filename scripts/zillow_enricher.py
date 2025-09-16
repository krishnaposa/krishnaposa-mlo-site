# zillow_enricher.py
import re, json, time, random
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

def _num(x):
    if x is None: return None
    try:
        return float(re.sub(r"[^\d.\-]", "", str(x)))
    except:
        return None

def _deep_find_keys(obj, keys_lower:set[str]) -> Dict[str, Any]:
    out={}; stack=[obj]
    while stack:
        cur=stack.pop()
        if isinstance(cur, dict):
            for k,v in cur.items():
                kl=str(k).lower()
                if kl in keys_lower and kl not in out: out[kl]=v
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return out

def _extract_globals(page):
    keys = [
        "__NEXT_DATA__", "hdpApolloPreloadedData", "hdpData",
        "__APOLLO_STATE__", "__REDUX_STATE__", "__ZSG_GLOBALS__"
    ]
    out={}
    for k in keys:
        try:
            val = page.evaluate(f"() => window.{k}")
            if val: out[k]=val
        except Exception:
            pass
    return out

def _extract_from_dom(html: str):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id":"__NEXT_DATA__"})
    next_data = json.loads(tag.string) if tag and tag.string else None

    # crummy fallback from visible text
    text = soup.get_text(" ", strip=True)
    hoa = None; tax_annual = None; zestimate=None; rent_zest=None; price=None
    m = re.search(r"\bHOA[^$]*\$\s*([0-9,]+)\s*(?:/mo|per month|monthly)?", text, re.I)
    if m: hoa = _num(m.group(1))
    m = re.search(r"(?:Property\s+tax(?:es)?|Annual\s+tax)[^$]*\$\s*([0-9,]+)", text, re.I)
    if m: tax_annual = _num(m.group(1))
    m = re.search(r"Zestimate[^$]*\$\s*([0-9,]+)", text, re.I)
    if m: zestimate = _num(m.group(1))
    m = re.search(r"Rent Zestimate[^$]*\$\s*([0-9,]+)", text, re.I)
    if m: rent_zest = _num(m.group(1))
    m = re.search(r"Price[^$]*\$\s*([0-9,]+)", text, re.I)
    if m: price = _num(m.group(1))

    return {"__NEXT_DATA__": next_data,
            "heuristic": {"hoa": hoa, "tax_annual": tax_annual, "zestimate": zestimate,
                          "rent_zestimate": rent_zest, "price": price}}

def zillow_url_via_ddg(one_line_addr: str) -> Optional[str]:
    q = f"site:zillow.com homedetails {one_line_addr}"
    r = requests.get("https://duckduckgo.com/html/", params={"q": q},
                     headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href") or ""
        # unwrap uddg redirect if present
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote
            href = unquote(m.group(1))
        if "zillow.com" in href and "/homedetails/" in href:
            return href
    return None

def fetch_zillow_data_smart(url: str, *, headless=False, slow_mo=80, timeout_ms=45000):
    captures = {"globals":{}, "network_json":[], "dom":None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = browser.new_context(
            viewport={"width":1366,"height":900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/124.0"),
            locale="en-US"
        )
        context.set_default_timeout(timeout_ms)
        page = context.new_page()

        # capture JSON responses (GraphQL/API)
        def on_response(resp):
            try:
                ct = resp.headers.get("content-type","")
                if "application/json" not in ct: return
                u = resp.url.lower()
                if "zillow.com" in u or "graphql" in u or "api" in u:
                    j = resp.json()
                    if isinstance(j,(dict,list)):
                        captures["network_json"].append({"url": resp.url, "json": j})
            except Exception:
                pass
        page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded")

        # cookie banners
        for sel in [
          "button:has-text('Accept')","button:has-text('I agree')",
          "button[aria-label='Accept all']","button:has-text('Got it')",
        ]:
            try:
                if page.locator(sel).first.is_visible():
                    page.locator(sel).first.click(); break
            except Exception:
                pass

        for _ in range(3):
            page.mouse.wheel(0, 1600); time.sleep(random.uniform(0.3, 0.9))

        captures["globals"] = _extract_globals(page)
        html = page.content()
        captures["dom"] = _extract_from_dom(html)

        try: page.screenshot(path="zillow_debug.png", full_page=True)
        except Exception: pass

        browser.close()

    # mine fields from candidates
    address_parts = {}
    hoa=None; tax_annual=None; price=None; zestimate=None; rent_zest=None

    wanted = {
        "streetaddress","streetline","address","city","state","zipcode","zip","postalcode",
        "monthlyhoafee","hoadues","hoafee","hoa",
        "taxannualamount","propertytax","taxes",
        "zestimate","rentzestimate","price","unformattedprice","pricevalue","homeprice"
    }

    candidates = []
    for v in (captures["globals"] or {}).values():
        if v: candidates.append(v)
    if captures["dom"] and captures["dom"].get("__NEXT_DATA__"):
        candidates.append(captures["dom"]["__NEXT_DATA__"])
    for it in captures["network_json"]:
        candidates.append(it["json"])

    for blob in candidates:
        try:
            hits = _deep_find_keys(blob, wanted)
            # address
            street = hits.get("streetaddress") or hits.get("streetline") or hits.get("address")
            city = hits.get("city"); state = hits.get("state")
            zipc = hits.get("zipcode") or hits.get("zip") or hits.get("postalcode")
            if any([street,city,state,zipc]) and not address_parts:
                address_parts = {"street":street,"city":city,"state":state,"zip":zipc}
            # HOA
            for k in ("monthlyhoafee","hoadues","hoafee","hoa"):
                if hoa is None and k in hits:
                    hoa = _num(hits[k])
            # Taxes
            for k in ("taxannualamount","propertytax","taxes"):
                if tax_annual is None and k in hits:
                    v = hits[k]
                    if isinstance(v, dict):
                        for kk in ("amount","annual","value"): 
                            if kk in v: tax_annual = _num(v[kk]); break
                    else:
                        tax_annual = _num(v)
            # Prices
            for k in ("unformattedprice","pricevalue","homeprice","price"):
                if price is None and k in hits:
                    vv = hits[k]
                    if isinstance(vv, dict) and "amount" in vv:
                        price = _num(vv["amount"])
                    else:
                        price = _num(vv)
            if zestimate is None and "zestimate" in hits:
                zv = hits["zestimate"]
                if isinstance(zv, dict) and "amount" in zv:
                    zestimate = _num(zv["amount"])
                else:
                    zestimate = _num(zv)
            if rent_zest is None and "rentzestimate" in hits:
                rz = hits["rentzestimate"]
                if isinstance(rz, dict) and "amount" in rz:
                    rent_zest = _num(rz["amount"])
                else:
                    rent_zest = _num(rz)
        except Exception:
            continue

    # DOM fallbacks
    heur = (captures["dom"] or {}).get("heuristic") or {}
    if hoa is None and heur.get("hoa") is not None: hoa = heur["hoa"]
    if tax_annual is None and heur.get("tax_annual") is not None: tax_annual = heur["tax_annual"]
    if price is None and heur.get("price") is not None: price = heur["price"]
    if zestimate is None and heur.get("zestimate") is not None: zestimate = heur["zestimate"]
    if rent_zest is None and heur.get("rent_zestimate") is not None: rent_zest = heur["rent_zestimate"]

    estimates = {
        "hoa_monthly": hoa if hoa is not None else None,
        "property_tax_annual": tax_annual if tax_annual is not None else None,
        "suggested_price": price or zestimate,  # prefer price; fall back to zestimate
        "zestimate": zestimate,
        "rent_zestimate": rent_zest
    }
    ok = bool(address_parts) or any([hoa, tax_annual, price, zestimate, rent_zest])
    return {"ok": ok, "url": url, "address_parts": address_parts, "estimates": estimates, "captures": captures}