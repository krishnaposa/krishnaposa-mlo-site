# shared/redfin_enricher.py
import re, json, time, random
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dateutil import parser as dtparser

def _extract_next_data(html: str):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    return json.loads(tag.string) if tag and tag.string else None

def _to_float(x):
    try: return float(x)
    except: return None

def _deep_find_keys(obj, wanted:set[str]):
    out={}; stack=[obj]
    while stack:
        cur=stack.pop()
        if isinstance(cur, dict):
            for k,v in cur.items():
                kl=str(k).lower()
                if kl in wanted and kl not in out:
                    out[kl]=v
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return out

def redfin_url_via_ddg(address: str) -> str | None:
    q = f"site:redfin.com {address}"
    r = requests.get("https://duckduckgo.com/html/", params={"q": q},
                     headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.result__a"):
        url = a.get("href") or ""
        if "redfin.com" in url and "/home/" in url: return url
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            from urllib.parse import unquote
            real = unquote(m.group(1))
            if "redfin.com" in real and "/home/" in real: return real
    return None

def fetch_redfin_json_playwright(url: str) -> dict | None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/124.0"),
            locale="en-US"
        )
        context.set_default_timeout(45000)
        page = context.new_page()
        time.sleep(random.uniform(0.2, 0.9))
        page.goto(url, wait_until="domcontentloaded")
        for _ in range(2):
            page.mouse.wheel(0, 1200); time.sleep(0.3)
        page.wait_for_selector("script#__NEXT_DATA__", timeout=45000)
        html = page.content()
        browser.close()
    return _extract_next_data(html)

def extract_basic_estimates(next_data: dict) -> dict:
    wanted = {
        "address","streetline","city","state","zipcode","zip","postalcode",
        "monthlyhoa","hoadues","propertytax","lastsaleprice","price"
    }
    hits = _deep_find_keys(next_data, wanted)
    addr = hits.get("address") or hits.get("streetline")
    city = hits.get("city"); state = hits.get("state")
    zipc = hits.get("zipcode") or hits.get("zip") or hits.get("postalcode")

    hoa = hits.get("monthlyhoa") or hits.get("hoadues")
    hoa = _to_float(hoa) if hoa is not None else None

    taxes = hits.get("propertytax")
    if isinstance(taxes, dict):
        for k in ("amount","annual","value"):
            if k in taxes:
                taxes = taxes[k]; break
    taxes = _to_float(taxes)

    last_price = hits.get("lastsaleprice") or hits.get("price")
    if isinstance(last_price, dict): last_price = last_price.get("amount")
    last_price = _to_float(last_price)

    return {
        "address_parts": {"street": addr, "city": city, "state": state, "zip": zipc},
        "estimates": {
            "hoa_monthly": hoa if hoa is not None else None,
            "tax_monthly": round((taxes or 0)/12, 2) if taxes else None,
            "insurance_monthly": 100,        # baseline, refine per state if you wish
            "suggested_price": last_price,   # best-effort
            "rent_monthly": None             # plug a rent source later
        }
    }

def prefill_from_address(one_line: str) -> dict:
    url = redfin_url_via_ddg(one_line)
    if not url:
        return {"ok": False, "error": "redfin_url_not_found"}
    data = fetch_redfin_json_playwright(url)
    if not data:
        return {"ok": False, "error": "redfin_json_not_found", "redfin_url": url}
    basics = extract_basic_estimates(data)
    return {"ok": True, "redfin_url": url, **basics}