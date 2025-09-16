# capture.py
import time, random, json, re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from constants import UA_STR
from utils import (
    log, warn, normalize_hoa, to_float, deep_find_keys, clean_str,
    dump_json_blob, dump_index, rent_from_payload_url,
)

# -------- helpers to extract window globals / DOM -------
def _extract_globals(page):
    keys = [
        "__NEXT_DATA__", "__REDUX_STATE__", "__APOLLO_STATE__",
        "__PREFETCHED_QUERIES__", "__RF_PAGE_DATA__", "__INITIAL_STATE__",
    ]
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
    if next_data:
        log("Found embedded __NEXT_DATA__ in DOM.")

    text = soup.get_text(" ", strip=True)
    hoa = None
    tax_annual = None

    m = re.search(r"\bHOA[^$]*\$\s*([0-9,]+)\s*(?:/mo|per month|monthly)?", text, re.I)
    if m:
        hoa = normalize_hoa(m.group(1))
        if hoa is not None:
            log(f"Heuristic HOA parsed from DOM: {hoa}")

    m = re.search(r"(?:Property\s+tax(?:es)?|Annual\s+tax)[^$]*\$\s*([0-9,]+)", text, re.I)
    if m:
        tax_annual = to_float(m.group(1))
        if tax_annual is not None:
            log(f"Heuristic property tax parsed from DOM: {tax_annual}")

    return {"__NEXT_DATA__": next_data, "heuristic": {"hoa": hoa, "tax_annual": tax_annual}}


# -------- core capture ----------
def fetch_redfin_data_smart(url: str, *, headless=True, slow_mo=0, timeout_ms=45000, dump_blobs=True):
    """
    Loads a Redfin property page and captures:
      - window globals
      - JSON network responses (GraphQL / stingray / api)
      - DOM heuristics (HOA / taxes)
    Also parses rent range from Stingray comparable rentals responses.
    """
    caps = {"globals": {}, "network_json": [], "dom": None}
    log(f"Loading property page: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=UA_STR,
            locale="en-US",
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
                    # Some endpoints prefix JSON with )]}'
                    try:
                        j = resp.json()
                    except Exception:
                        txt = resp.text()
                        jtxt = re.sub(r"^\)\]\}'\s*", "", txt or "")
                        j = json.loads(jtxt)
                    if isinstance(j, (dict, list)):
                        caps["network_json"].append({"url": resp.url, "json": j})
                        idx = len(caps["network_json"])
                        log(f"Captured JSON response #{idx}: {resp.url}")
                        if dump_blobs:
                            dump_json_blob(idx, resp.url, j)
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded")

        for _ in range(3):
            page.mouse.wheel(0, 1500)
            time.sleep(random.uniform(0.2, 0.5))

        caps["globals"] = _extract_globals(page)
        if dump_blobs and caps["globals"]:
            for i, (k, v) in enumerate(caps["globals"].items(), start=1):
                dump_json_blob(100 + i, f"window.{k}", v)

        caps["dom"] = _extract_from_dom(page.content())

        try:
            page.screenshot(path="redfin_debug.png", full_page=True)
            log("Saved screenshot: redfin_debug.png")
        except Exception:
            pass

        browser.close()

    if dump_blobs:
        dump_index({
            "url": url,
            "globals_dumped": list((caps["globals"] or {}).keys()),
            "network_blob_count": len(caps["network_json"]),
            "have_dom_next_data": bool(caps["dom"] and caps["dom"].get("__NEXT_DATA__")),
        })

    # -------- Mine values --------
    address_parts = {}
    hoa = None
    tax_annual = None
    list_price = None
    last_sale_price = None
    rent_lo = None
    rent_hi = None

    # Expand the vocabulary we search for across Apollo/Redux payloads
    wanted = {
        # address variants
        "address", "streetline", "streetline1", "line1", "street", "streetaddress",
        "city", "state", "zipcode", "zip", "postalcode",
        # HOA variants
        "hoa", "monthlyhoa", "hoadues", "monthlyhoafee", "hoafees", "homeownersassociationdues",
        # tax variants
        "propertytax", "annualtax", "tax", "taxamount", "propertytaxes",
        # price variants
        "listprice", "price", "lastsaleprice", "lastsoldprice", "amount", "priceinfo",
    }

    # JSON sources: globals → DOM __NEXT_DATA__ → network blobs
    candidates = []
    for v in (caps["globals"] or {}).values():
        if v:
            candidates.append(v)
    if caps["dom"] and caps["dom"].get("__NEXT_DATA__"):
        candidates.append(caps["dom"]["__NEXT_DATA__"])
    for it in caps["network_json"]:
        candidates.append(it["json"])

    log(f"Mining {len(candidates)} JSON blob(s) for keys…")
    for blob in candidates:
        try:
            hits = deep_find_keys(blob, wanted)

            # Address
            street = (clean_str(hits.get("streetline")) or clean_str(hits.get("streetline1"))
                      or clean_str(hits.get("line1")) or clean_str(hits.get("street"))
                      or clean_str(hits.get("streetaddress")) or clean_str(hits.get("address")))
            city = clean_str(hits.get("city"))
            state = clean_str(hits.get("state"))
            zipc = clean_str(hits.get("zipcode") or hits.get("zip") or hits.get("postalcode"))
            if any([street, city, state, zipc]) and not address_parts:
                address_parts = {"street": street, "city": city, "state": state, "zip": zipc}
                log(f"Address parsed: {address_parts}")

            # HOA
            if hoa is None:
                hoa_raw = (hits.get("hoa") or hits.get("monthlyhoa") or hits.get("hoadues")
                           or hits.get("monthlyhoafee") or hits.get("hoafees")
                           or hits.get("homeownersassociationdues"))
                hoa = normalize_hoa(hoa_raw)
                if hoa is not None:
                    log(f"HOA (from JSON): {hoa}")

            # Taxes
            if tax_annual is None:
                t = (hits.get("propertytax") or hits.get("annualtax") or hits.get("tax")
                     or hits.get("taxamount") or hits.get("propertytaxes"))
                if isinstance(t, dict):
                    for k in ("amount", "annual", "value"):
                        if k in t:
                            tax_annual = to_float(t[k])
                            break
                else:
                    tv = to_float(t)
                    if tv is not None:
                        tax_annual = tv
                if tax_annual is not None:
                    log(f"Property tax (from JSON): {tax_annual}")

            # Prices
            if list_price is None:
                p = hits.get("listprice") or hits.get("price") or hits.get("priceinfo")
                if isinstance(p, dict) and "amount" in p:
                    list_price = to_float(p["amount"])
                else:
                    pv = to_float(p)
                    if pv is not None:
                        list_price = pv
                if list_price is not None:
                    log(f"List price (from JSON): {list_price}")

            if last_sale_price is None:
                sp = hits.get("lastsaleprice") or hits.get("lastsoldprice")
                if isinstance(sp, dict) and "amount" in sp:
                    last_sale_price = to_float(sp["amount"])
                else:
                    sv = to_float(sp)
                    if sv is not None:
                        last_sale_price = sv
        except Exception:
            continue

    # Comparable rentals rent range via payload URL
    for item in caps["network_json"]:
        try:
            src = (item.get("url") or "").lower()
            j = item.get("json")
            if not isinstance(j, dict):
                continue
            if "stingray/api/comparablerentals" in src and "payload" in j:
                payload = j.get("payload") or []
                if payload and isinstance(payload, list):
                    pl_url = payload[0].get("url")
                    lo, hi = rent_from_payload_url(pl_url)
                    if lo or hi:
                        rent_lo = lo or rent_lo
                        rent_hi = hi or rent_hi
                        log(f"Rent range from payload: min={rent_lo} max={rent_hi}")
                        break
        except Exception:
            continue

    # DOM fallbacks
    heur = (caps["dom"] or {}).get("heuristic") or {}
    if hoa is None and heur.get("hoa") is not None:
        hoa = heur["hoa"]; log(f"HOA (heuristic fallback): {hoa}")
    if tax_annual is None and heur.get("tax_annual") is not None:
        tax_annual = heur["tax_annual"]; log(f"Property tax (heuristic fallback): {tax_annual}")

    # Rent estimate
    rent_est = None
    if rent_lo and rent_hi:
        rent_est = round((rent_lo + rent_hi) / 2.0, 2)
    elif rent_lo:
        rent_est = rent_lo
    elif rent_hi:
        rent_est = rent_hi

    # Choose a single “suggested price”: prefer list price; fall back to last sale
    suggested_price = list_price if list_price is not None else last_sale_price

    estimates = {
        "hoa_monthly": hoa if hoa is not None else None,
        "property_tax_annual": tax_annual if tax_annual is not None else None,
        "suggested_price": suggested_price,
        "last_sale_price": last_sale_price,
        "list_price": list_price,
        "insurance_monthly": 100,
        "rent_monthly_est": rent_est,
        "rent_range": [rent_lo, rent_hi],
    }

    ok = bool(address_parts) or any([hoa, tax_annual, suggested_price, rent_est])

    log(
        f"Capture summary → globals:{len([v for v in (caps['globals'] or {}).values() if v])} "
        f"network_json:{len(caps['network_json'])} ok:{ok}"
    )

    return {
        "ok": ok,
        "url": url,
        "address_parts": address_parts,
        "estimates": estimates,
    }