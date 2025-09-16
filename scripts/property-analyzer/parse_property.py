# parse_property.py
import re, time, random, json
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def _to_float(x):
    try:
        return float(re.sub(r"[^\d.\-]", "", str(x)))
    except:
        return None

def _deep_find_keys(obj, keys_lower:set[str]):
    out = {}
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k,v in cur.items():
                kl = str(k).lower()
                if kl in keys_lower and kl not in out:
                    out[kl] = v
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(cur,list):
            stack.extend(cur)
    return out

def _extract_globals(page):
    keys = ["__NEXT_DATA__", "__REDUX_STATE__", "__APOLLO_STATE__"]
    out = {}
    for k in keys:
        try:
            val = page.evaluate(f"() => window.{k}")
            if val: out[k] = val
        except:
            pass
    return out

def parse_property(url: str, *, headless=True, slow_mo=60, timeout_ms=45000):
    """Scrape Redfin property page and extract core details."""
    captures = {"globals": {}, "dom": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/124.0"),
            locale="en-US"
        )
        context.set_default_timeout(timeout_ms)
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded")

        # cookie banners (best-effort)
        for sel in ["button:has-text('Accept')","button:has-text('I agree')","button[aria-label='Accept all']"]:
            try:
                if page.locator(sel).first.is_visible():
                    page.locator(sel).first.click()
                    break
            except:
                pass

        # scroll a bit to trigger lazy scripts
        for _ in range(3):
            page.mouse.wheel(0, 1800)
            time.sleep(random.uniform(0.3, 0.9))

        captures["globals"] = _extract_globals(page)
        html = page.content()

        browser.close()

    # mine details
    address_parts = {}
    hoa = tax_annual = last_price = None

    wanted = {"address","streetline","city","state","zipcode","zip","postalcode",
              "monthlyhoa","hoadues","propertytax","lastsaleprice","price"}

    for blob in captures["globals"].values():
        hits = _deep_find_keys(blob, wanted)

        if not address_parts:
            addr = hits.get("address") or hits.get("streetline")
            city = hits.get("city"); state = hits.get("state")
            zipc = hits.get("zipcode") or hits.get("zip") or hits.get("postalcode")
            if any([addr, city, state, zipc]):
                address_parts = {"street": addr, "city": city, "state": state, "zip": zipc}

        if hoa is None:
            h = hits.get("monthlyhoa") or hits.get("hoadues")
            hoa = _to_float(h)

        if tax_annual is None:
            t = hits.get("propertytax")
            if isinstance(t, dict):
                for k in ("amount","annual","value"):
                    if k in t: tax_annual = _to_float(t[k]); break
            else:
                tax_annual = _to_float(t)

        if last_price is None:
            p = hits.get("lastsaleprice") or hits.get("price")
            if isinstance(p, dict): p = p.get("amount")
            last_price = _to_float(p)

    return {
        "address_text": ", ".join([s for s in [address_parts.get("street"), address_parts.get("city"),
                                               address_parts.get("state"), address_parts.get("zip")] if s]),
        "address_parts": address_parts,
        "property_details": {
            "hoa_monthly": hoa,
            "property_tax_annual": tax_annual,
            "last_sale_price": last_price
        }
    }