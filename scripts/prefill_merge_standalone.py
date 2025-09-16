#!/usr/bin/env python3
"""
prefill_merge_standalone.py
---------------------------------
Standalone local tool to fetch Zillow + Redfin for a given address,
then merge estimates with clear precedence and provenance.

Outputs a single JSON object to stdout:
{
  "ok": true/false,
  "address_text": "...",
  "address_parts": {street, city, state, zip},
  "estimates": {
    "hoa_monthly", "property_tax_annual", "tax_monthly",
    "insurance_monthly", "suggested_price", "rent_monthly",
    "zestimate"
  },
  "sources": { per-field provenance },
  "links":   { "redfin": url-or-null, "zillow": url-or-null },
  "debug":   { minimal breadcrumbs }
}
"""

import re, json, time, random, argparse, sys
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from playwright.sync_api import sync_playwright
from urllib.parse import unquote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import time, random, re

def redfin_url_via_site(address: str, *, headless: bool = True, slow_mo: int = 50, timeout_ms: int = 45000) -> str | None:
    """
    Drive redfin.com to resolve a property page for the given address.
    Returns a URL like .../home/######## or None.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/124.0"),
            locale="en-US"
        )
        page = ctx.new_page()
        try:
            page.goto("https://www.redfin.com/", wait_until="domcontentloaded", timeout=timeout_ms)

            # cookie banner best-effort
            for sel in ["button:has-text('Accept')", "button:has-text('I agree')", "button[aria-label='Accept all']"]:
                try:
                    if page.locator(sel).first.is_visible():
                        page.locator(sel).first.click(); break
                except Exception:
                    pass

            # search input (Redfin uses #search-box-input on home)
            box = page.locator("#search-box-input")
            box.fill(address)
            time.sleep(random.uniform(0.2, 0.6))

            # pick the first autocomplete row if it appears; otherwise press Enter
            row = page.locator(".autoCompleteRow").first
            try:
                row.wait_for(state="visible", timeout=3000)
                row.click()
            except PWTimeout:
                box.press("Enter")

            # wait for property page URL
            page.wait_for_url(re.compile(r".*/home/\d+.*"), timeout=timeout_ms)
            url = page.url
            return url
        except Exception:
            return None
        finally:
            browser.close()

def zillow_url_via_site(address: str, *, headless: bool = True, slow_mo: int = 50, timeout_ms: int = 45000) -> str | None:
    """
    Drive zillow.com to resolve a property page for the given address.
    Returns a URL like .../homedetails/.../_zpid/ or None.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/124.0"),
            locale="en-US"
        )
        page = ctx.new_page()
        try:
            page.goto("https://www.zillow.com/", wait_until="domcontentloaded", timeout=timeout_ms)

            # cookie banner best-effort
            for sel in ["button:has-text('Accept')", "button:has-text('I agree')", "button[aria-label='Accept all']"]:
                try:
                    if page.locator(sel).first.is_visible():
                        page.locator(sel).first.click(); break
                except Exception:
                    pass

            # search input can be #search-box-input or aria-label based
            box = page.locator("input#search-box-input, input[aria-label*='Enter an address']").first
            box.fill(address)
            time.sleep(random.uniform(0.2, 0.6))

            # try autocomplete
            opt = page.locator("[data-testid='search-suggestion'], li[role='option']").first
            try:
                opt.wait_for(state="visible", timeout=3000)
                opt.click()
            except PWTimeout:
                box.press("Enter")

            # Wait for a homedetails page (ideally with _zpid)
            try:
                page.wait_for_url(re.compile(r".*/homedetails/.*?_zpid/?$"), timeout=timeout_ms)
            except PWTimeout:
                # fall back to any homedetails (we can still scrape network JSON)
                page.wait_for_url(re.compile(r".*/homedetails/.*"), timeout=timeout_ms)

            return page.url
        except Exception:
            return None
        finally:
            browser.close()
# ---------- basic log helpers ----------
def log(s):  print(f"[INFO] {s}", flush=True)
def warn(s): print(f"[WARN] {s}", flush=True)

def normalize_hoa(val):
    if not val:
        return None
    try:
        v = float(val)
        # sanity check: discard insane values
        if v > 5000:  # monthly HOA rarely exceeds $5k
            return None
        return v
    except:
        return None
# ---------- tiny utils ----------
def _num(x):
    if x is None: return None
    try:
        return float(re.sub(r"[^\d.\-]", "", str(x)))
    except Exception:
        return None

def _deep_find_keys(obj, keys_lower:set[str]):
    out={}; stack=[obj]
    while stack:
        cur=stack.pop()
        if isinstance(cur, dict):
            for k,v in cur.items():
                kl=str(k).lower()
                if kl in keys_lower and kl not in out:
                    out[kl]=v
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return out

def _clean_str(x):
    if x is None: return None
    s=str(x).strip()
    return s or None

def _norm_addr(parts):
    parts = parts or {}
    return {
        "street": _clean_str(parts.get("street") or parts.get("address") or parts.get("line")),
        "city":   _clean_str(parts.get("city")),
        "state":  _clean_str(parts.get("state")),
        "zip":    _clean_str(str(parts.get("zip")) if parts.get("zip") is not None else None),
    }

def _first_non_null(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

# ---------- DDG URL finders ----------
_DDG_ENDPOINTS = (
    "https://duckduckgo.com/html/",
    "https://duckduckgo.com/lite/",
)

# --- generic DDG fetch that returns a list of unwrapped links ---
def _ddg_links(query: str, max_results: int = 10) -> list[str]:
    ua = "Mozilla/5.0"
    out: list[str] = []
    for ep in _DDG_ENDPOINTS:
        try:
            r = requests.get(
                ep,
                params={"q": query, "kl": "us-en"},
                headers={"User-Agent": ua},
                timeout=20,
            )
            r.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        # both html and lite layouts expose anchors; grab generously
        for a in soup.select("a"):
            href = a.get("href") or ""
            if not href:
                continue
            # unwrap /l/?…&uddg=<encoded>
            m = re.search(r"[?&]uddg=([^&]+)", href)
            if m:
                href = unquote(m.group(1))
            out.append(href)

        if out:
            break

    # keep uniques, preserve order
    seen = set()
    uniq = []
    for u in out:
        if u in seen: 
            continue
        seen.add(u)
        uniq.append(u)
    return uniq[:max_results]

# --- validators (robust) ---
_REDFIN_PATTERNS = [
    re.compile(r"^https?://(?:www|m)\.redfin\.com/.+/home/\d+", re.I),
    re.compile(r"^https?://(?:www|m)\.redfin\.com/address/.+", re.I),
]
_ZILLOW_PATTERNS = [
    re.compile(r"^https?://(?:www|m)\.zillow\.com/homedetails/.+?/\d+_zpid/?$", re.I),
    re.compile(r"^https?://(?:www|m)\.zillow\.com/homedetails/.+?$", re.I),  # fallback if _zpid missing
]

def _first_match(links: list[str], patterns: list[re.Pattern]) -> str | None:
    for u in links:
        low = u.lower()
        # quick host filter for speed
        if "redfin" in low or "zillow" in low:
            for p in patterns:
                if p.match(u):
                    return u
    return None

# --- public resolvers you can call ---
def redfin_url_via_ddg(address: str) -> str | None:
    # Try several query phrasings; DDG can be fickle
    queries = [
        f"site:redfin.com {address} home",
        f"{address} site:redfin.com/home",
        f"{address} Redfin home details",
        f"site:redfin.com address {address}",
    ]
    for q in queries:
        log(f"DDG query: {q}")
        links = _ddg_links(q)
        url = _first_match(links, _REDFIN_PATTERNS)
        if url:
            log(f"DDG found Redfin: {url}")
            return url
    warn("No Redfin property URL found via DDG.")
    return None

def zillow_url_via_ddg(address: str) -> str | None:
    queries = [
        f"site:zillow.com homedetails {address} _zpid",
        f"site:zillow.com {address} _zpid",
        f"{address} Zillow _zpid",
        f"site:zillow.com homedetails {address}",
    ]
    for q in queries:
        log(f"DDG query: {q}")
        links = _ddg_links(q)
        url = _first_match(links, _ZILLOW_PATTERNS)
        if url:
            log(f"DDG found Zillow: {url}")
            return url
    warn("No Zillow property URL found via DDG.")
    return None
# ---------- common Playwright helpers ----------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/124.0")

def _extract_globals(page, keys):
    out={}
    for k in keys:
        try:
            val = page.evaluate(f"() => window.{k}")
            if val: out[k]=val
        except Exception:
            pass
    return out

def _extract_from_dom(html, site="redfin"):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id":"__NEXT_DATA__"})
    next_data = json.loads(tag.string) if tag and tag.string else None

    # crummy but useful fallbacks
    text = soup.get_text(" ", strip=True)
    hoa=None; tax_annual=None; zestimate=None; rent_zest=None; price=None

    m = re.search(r"\bHOA[^$]*\$\s*([0-9,]+)\s*(?:/mo|per month|monthly)?", text, re.I)
    if m: hoa = _num(m.group(1))
    m = re.search(r"(?:Property\s+tax(?:es)?|Annual\s+tax)[^$]*\$\s*([0-9,]+)", text, re.I)
    if m: tax_annual = _num(m.group(1))
    if site == "zillow":
        m = re.search(r"Zestimate[^$]*\$\s*([0-9,]+)", text, re.I)
        if m: zestimate = _num(m.group(1))
        m = re.search(r"Rent Zestimate[^$]*\$\s*([0-9,]+)", text, re.I)
        if m: rent_zest = _num(m.group(1))
        m = re.search(r"Price[^$]*\$\s*([0-9,]+)", text, re.I)
        if m: price = _num(m.group(1))

    return {
        "__NEXT_DATA__": next_data,
        "heuristic": {
            "hoa": hoa, "tax_annual": tax_annual,
            "zestimate": zestimate, "rent_zestimate": rent_zest, "price": price
        }
    }

def _playwright_fetch(url: str, site: str, headless: bool, slow_mo: int, timeout_ms: int):
    caps = {"globals":{}, "network_json":[], "dom":None}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = browser.new_context(
            viewport={"width":1366,"height":900},
            user_agent=UA, locale="en-US"
        )
        context.set_default_timeout(timeout_ms)
        page = context.new_page()

        # capture JSON responses (GraphQL/API)
        def on_response(resp):
            try:
                ct = resp.headers.get("content-type","")
                if "application/json" not in ct: return
                u = resp.url.lower()
                hostok = (site in u) or ("graphql" in u) or ("stingray" in u) or ("api" in u)
                if hostok:
                    j = resp.json()
                    if isinstance(j,(dict,list)):
                        caps["network_json"].append({"url": resp.url, "json": j})
            except Exception:
                pass
        page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded")

        # cookie banners (best-effort)
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
            page.mouse.wheel(0, 1600); time.sleep(random.uniform(0.3,0.9))

        # globals
        if site == "redfin":
            keys = ["__NEXT_DATA__", "__REDUX_STATE__", "__APOLLO_STATE__", "__PREFETCHED_QUERIES__", "__RF_PAGE_DATA__", "__INITIAL_STATE__"]
        else:
            keys = ["__NEXT_DATA__", "hdpApolloPreloadedData", "hdpData", "__APOLLO_STATE__", "__REDUX_STATE__", "__ZSG_GLOBALS__"]
        caps["globals"] = _extract_globals(page, keys)

        html = page.content()
        caps["dom"] = _extract_from_dom(html, site=site)

        try:
            page.screenshot(path=f"{site}_debug.png", full_page=True)
        except Exception:
            pass

        browser.close()
    return caps

# ---------- Redfin fetch ----------
def fetch_redfin_data_smart(url: str, *, headless=False, slow_mo=60, timeout_ms=45000):
    if not url:
        return {"ok": False, "url": None, "address_parts": {}, "estimates": {}, "captures": {}}
    caps = _playwright_fetch(url, site="redfin", headless=headless, slow_mo=slow_mo, timeout_ms=timeout_ms)

    address_parts = {}
    hoa=None; tax_annual=None; last_price=None

    wanted = {
        "address","streetline","city","state","zipcode","zip","postalcode",
        "monthlyhoa","hoadues","propertytax","lastsaleprice","price"
    }
    candidates = []
    for v in (caps["globals"] or {}).values():
        if v: candidates.append(v)
    if caps["dom"] and caps["dom"].get("__NEXT_DATA__"):
        candidates.append(caps["dom"]["__NEXT_DATA__"])
    for it in caps["network_json"]:
        candidates.append(it["json"])

    for blob in candidates:
        try:
            hits = _deep_find_keys(blob, wanted)
            street = hits.get("address") or hits.get("streetline")
            city, state = hits.get("city"), hits.get("state")
            zipc = hits.get("zipcode") or hits.get("zip") or hits.get("postalcode")
            if any([street,city,state,zipc]) and not address_parts:
                address_parts = {"street":street,"city":city,"state":state,"zip":zipc}
            if hoa is None:
                h = hits.get("monthlyhoa") or hits.get("hoadues")
                h = normalize_hoa(h)
                hv = _num(h); 
                if hv is not None: hoa = hv
            if tax_annual is None:
                t = hits.get("propertytax")
                if isinstance(t, dict):
                    for k in ("amount","annual","value"):
                        if k in t:
                            tax_annual = _num(t[k]); break
                else:
                    tv = _num(t)
                    if tv is not None: tax_annual = tv
            if last_price is None:
                p = hits.get("lastsaleprice") or hits.get("price")
                if isinstance(p, dict) and "amount" in p:
                    last_price = _num(p["amount"])
                else:
                    pv = _num(p)
                    if pv is not None: last_price = pv
        except Exception:
            continue

    heur = (caps["dom"] or {}).get("heuristic") or {}
    if hoa is None and heur.get("hoa") is not None: hoa = heur["hoa"]
    if tax_annual is None and heur.get("tax_annual") is not None: tax_annual = heur["tax_annual"]

    estimates = {
        "hoa_monthly": hoa,
        "property_tax_annual": tax_annual,
        "suggested_price": last_price,
        "insurance_monthly": 100
    }
    ok = bool(address_parts) or any([hoa, tax_annual, last_price])
    return {"ok": ok, "url": url, "address_parts": address_parts, "estimates": estimates, "captures": {"counts": {
        "globals": len(caps["globals"]), "network_json": len(caps["network_json"])
    }}}

# ---------- Zillow fetch ----------
def fetch_zillow_data_smart(url: str, *, headless=False, slow_mo=60, timeout_ms=45000):
    if not url:
        return {"ok": False, "url": None, "address_parts": {}, "estimates": {}, "captures": {}}
    caps = _playwright_fetch(url, site="zillow", headless=headless, slow_mo=slow_mo, timeout_ms=timeout_ms)

    address_parts = {}
    hoa=None; tax_annual=None; price=None; zestimate=None; rent_zest=None

    wanted = {
        "streetaddress","streetline","address","city","state","zipcode","zip","postalcode",
        "monthlyhoafee","hoadues","hoafee","hoa",
        "taxannualamount","propertytax","taxes",
        "zestimate","rentzestimate","price","unformattedprice","pricevalue","homeprice"
    }
    candidates = []
    for v in (caps["globals"] or {}).values():
        if v: candidates.append(v)
    if caps["dom"] and caps["dom"].get("__NEXT_DATA__"):
        candidates.append(caps["dom"]["__NEXT_DATA__"])
    for it in caps["network_json"]:
        candidates.append(it["json"])

    for blob in candidates:
        try:
            hits = _deep_find_keys(blob, wanted)
            street = hits.get("streetaddress") or hits.get("streetline") or hits.get("address")
            city, state = hits.get("city"), hits.get("state")
            zipc = hits.get("zipcode") or hits.get("zip") or hits.get("postalcode")
            if any([street,city,state,zipc]) and not address_parts:
                address_parts = {"street":street,"city":city,"state":state,"zip":zipc}
            for k in ("monthlyhoafee","hoadues","hoafee","hoa"):
                if hoa is None and k in hits:
                    hoa = _num(hits[k])
            for k in ("taxannualamount","propertytax","taxes"):
                if tax_annual is None and k in hits:
                    v = hits[k]
                    if isinstance(v, dict):
                        for kk in ("amount","annual","value"):
                            if kk in v: tax_annual = _num(v[kk]); break
                    else:
                        tax_annual = _num(v)
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

    heur = (caps["dom"] or {}).get("heuristic") or {}
    if hoa is None and heur.get("hoa") is not None: hoa = heur["hoa"]
    if tax_annual is None and heur.get("tax_annual") is not None: tax_annual = heur["tax_annual"]
    if price is None and heur.get("price") is not None: price = heur["price"]
    if zestimate is None and heur.get("zestimate") is not None: zestimate = heur["zestimate"]
    if rent_zest is None and heur.get("rent_zestimate") is not None: rent_zest = heur["rent_zestimate"]

    estimates = {
        "hoa_monthly": hoa,
        "property_tax_annual": tax_annual,
        "suggested_price": price or zestimate,
        "zestimate": zestimate,
        "rent_zestimate": rent_zest
    }
    ok = bool(address_parts) or any([hoa, tax_annual, price, zestimate, rent_zest])
    return {"ok": ok, "url": url, "address_parts": address_parts, "estimates": estimates, "captures": {"counts": {
        "globals": len(caps["globals"]), "network_json": len(caps["network_json"])
    }}}

# ---------- merge (with provenance) ----------
def _derive_tax_monthly(annual):
    return round(float(annual)/12.0, 2) if (annual is not None) else None

def choose_address_parts(redfin, zillow):
    rf = _norm_addr((redfin or {}).get("address_parts"))
    zf = _norm_addr((zillow or {}).get("address_parts"))
    return {
        "street": _first_non_null(rf.get("street"), zf.get("street")),
        "city":   _first_non_null(rf.get("city"),   zf.get("city")),
        "state":  _first_non_null(rf.get("state"),  zf.get("state")),
        "zip":    _first_non_null(rf.get("zip"),    zf.get("zip")),
    }

def merge_estimates(redfin, zillow, prefer=None):
    prefer = prefer or {}
    rfe = ((redfin or {}).get("estimates") or {})
    zfe = ((zillow or {}).get("estimates") or {})

    rf_hoa   = _num(rfe.get("hoa_monthly"))
    zf_hoa   = _num(zfe.get("hoa_monthly"))

    rf_tax_a = _num(rfe.get("property_tax_annual"))
    zf_tax_a = _num(zfe.get("property_tax_annual"))

    rf_price = _num(rfe.get("suggested_price"))
    zf_price = _num(zfe.get("suggested_price"))
    zf_zest  = _num(zfe.get("zestimate"))

    rf_rent  = _num(rfe.get("rent_monthly"))
    zf_rent  = _num(zfe.get("rent_zestimate"))

    rf_ins   = _num(rfe.get("insurance_monthly"))
    baseline_ins = 100.0

    src = {}

    # HOA
    if prefer.get("hoa_monthly") == "zillow":
        hoa = _first_non_null(zf_hoa, rf_hoa)
        src["hoa_monthly"] = "Zillow" if zf_hoa is not None else ("Redfin" if rf_hoa is not None else None)
    else:
        hoa = _first_non_null(rf_hoa, zf_hoa)
        src["hoa_monthly"] = "Redfin" if rf_hoa is not None else ("Zillow" if zf_hoa is not None else None)

    # Taxes (annual)
    if prefer.get("property_tax_annual") == "zillow":
        tax_a = _first_non_null(zf_tax_a, rf_tax_a)
        src["property_tax_annual"] = "Zillow" if zf_tax_a is not None else ("Redfin" if rf_tax_a is not None else None)
    else:
        tax_a = _first_non_null(rf_tax_a, zf_tax_a)
        src["property_tax_annual"] = "Redfin" if rf_tax_a is not None else ("Zillow" if zf_tax_a is not None else None)

    # Suggested price
    if prefer.get("suggested_price") == "zillow":
        suggested_price = _first_non_null(zf_price, rf_price, zf_zest)
        if zf_price is not None:   src["suggested_price"] = "Zillow"
        elif rf_price is not None: src["suggested_price"] = "Redfin"
        elif zf_zest is not None:  src["suggested_price"] = "Zillow (Zestimate)"
        else:                      src["suggested_price"] = None
    else:
        suggested_price = _first_non_null(rf_price, zf_price, zf_zest)
        if rf_price is not None:   src["suggested_price"] = "Redfin"
        elif zf_price is not None: src["suggested_price"] = "Zillow"
        elif zf_zest is not None:  src["suggested_price"] = "Zillow (Zestimate)"
        else:                      src["suggested_price"] = None

    # Rent
    if prefer.get("rent_monthly") == "redfin":
        rent = _first_non_null(rf_rent, zf_rent)
        src["rent_monthly"] = "Redfin" if rf_rent is not None else ("Zillow (Rent Zestimate)" if zf_rent is not None else None)
    else:
        rent = _first_non_null(zf_rent, rf_rent)
        src["rent_monthly"] = "Zillow (Rent Zestimate)" if zf_rent is not None else ("Redfin" if rf_rent is not None else None)

    # Insurance
    if prefer.get("insurance_monthly") == "zillow":
        ins = _first_non_null(zfe.get("insurance_monthly"), rf_ins, baseline_ins)
        src["insurance_monthly"] = ("Zillow" if zfe.get("insurance_monthly") is not None
                                    else ("Redfin" if rf_ins is not None else "Baseline"))
    else:
        ins = _first_non_null(rf_ins, zfe.get("insurance_monthly"), baseline_ins)
        src["insurance_monthly"] = ("Redfin" if rf_ins is not None
                                    else ("Zillow" if zfe.get("insurance_monthly") is not None else "Baseline"))

    tax_m = _derive_tax_monthly(tax_a)
    return {
        "estimates": {
            "hoa_monthly": hoa,
            "property_tax_annual": tax_a,
            "tax_monthly": tax_m,
            "insurance_monthly": ins,
            "suggested_price": suggested_price,
            "rent_monthly": rent,
            "zestimate": zf_zest
        },
        "sources": src
    }

def merge_prefill_result(redfin, zillow, prefer=None):
    addr = choose_address_parts(redfin, zillow)
    merged = merge_estimates(redfin, zillow, prefer=prefer or {})
    address_text = ", ".join([s for s in [addr.get("street"), addr.get("city"), addr.get("state"), addr.get("zip")] if s])
    return {
        "ok": True if any(merged["estimates"].values()) or any(addr.values()) else False,
        "address_parts": addr,
        "address_text": address_text or None,
        "estimates": merged["estimates"],
        "sources": merged["sources"],
        "links": {
            "redfin": (redfin or {}).get("url"),
            "zillow": (zillow or {}).get("url")
        }
    }

# ---------- main CLI ----------
def main():
    ap = argparse.ArgumentParser(description="Standalone Zillow+Redfin prefill merge.")
    ap.add_argument("address", help='One-line address, e.g. "123 Main St, City, ST 12345"')
    ap.add_argument("--headful", action="store_true", help="Run with visible browser (default is headless).")
    ap.add_argument("--prefer", action="append", default=[],
                    help="Override precedence per field, e.g. --prefer suggested_price=zillow "
                         "(fields: hoa_monthly, property_tax_annual, suggested_price, rent_monthly, insurance_monthly)")
    args = ap.parse_args()

    # parse prefer flags
    prefer = {}
    for item in args.prefer:
        m = re.match(r"^([a-z_]+)=(redfin|zillow)$", item.strip(), re.I)
        if not m:
            warn(f"Ignoring malformed --prefer '{item}'")
            continue
        prefer[m.group(1).lower()] = m.group(2).lower()

    headless = not args.headful

    # Resolve URLs
    rf_url = redfin_url_via_ddg(args.address) or redfin_url_via_site(address, headless=False)
    zf_url = zillow_url_via_ddg(args.address) or zillow_url_via_site(address, headless=False)

    # Fetch (sequential; you can parallelize if you want)
    redfin = fetch_redfin_data_smart(rf_url, headless=headless) if rf_url else None
    zillow = fetch_zillow_data_smart(zf_url, headless=headless) if zf_url else None

    # Merge + print
    merged = merge_prefill_result(redfin, zillow, prefer=prefer)
    print(json.dumps({"ok": merged["ok"], **merged}, indent=2))

if __name__ == "__main__":
    main()