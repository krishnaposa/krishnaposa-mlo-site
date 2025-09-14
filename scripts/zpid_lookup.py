"""
zpid_lookup.py
Find a Zillow Property ID (ZPID) from a street address.

Usage:
    python zpid_lookup.py "2450 Clairview St, Alpharetta, GA 30009"
or from code:
    from zpid_lookup import find_zpid
    zpid = find_zpid("2450 Clairview St, Alpharetta, GA 30009")
"""

import re
import sys
import json
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

ZILLOW_HOME = "https://www.zillow.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def _extract_zpids_from_next_data(html: str) -> list[str]:
    """
    Parse __NEXT_DATA__ JSON blobs that Zillow embeds and return any ZPIDs found.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Newer Zillow pages often use id="__NEXT_DATA__"
    scripts = soup.find_all("script", id="__NEXT_DATA__")
    candidates: list[str] = []

    for tag in scripts:
        try:
            data = json.loads(tag.string or "{}")
        except Exception:
            continue

        # Walk JSON looking for keys named zpid or <something>_zpid
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                for k, v in cur.items():
                    if k.lower() == "zpid" and isinstance(v, (int, str)):
                        candidates.append(str(v))
                    elif isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(cur, list):
                stack.extend(cur)

    # As a fallback, try to regex any pattern like 12345678_zpid in the page
    if not candidates:
        for m in re.finditer(r"/(\d+)_zpid/", html):
            candidates.append(m.group(1))

    # De-dupe while preserving order
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            uniq.append(c)
            seen.add(c)
    return uniq

def search_zpid_via_address(address: str) -> Optional[str]:
    """
    Try Zillow's search results for the address and pull ZPIDs from embedded JSON.
    This usually returns the target ZPID as the first one if the address matches well.
    """
    # Build a search URL like:
    # https://www.zillow.com/homes/<urlencoded address>_rb/
    slug = urllib.parse.quote(address)
    url = f"{ZILLOW_HOME}/homes/{slug}_rb/"

    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None

    zpids = _extract_zpids_from_next_data(r.text)
    return zpids[0] if zpids else None

def extract_zpid_from_property_url(url: str) -> Optional[str]:
    """
    If you already have a property URL, pull the ZPID from URL or page JSON.
    """
    # Try to read from URL like .../12345678_zpid/
    m = re.search(r"/(\d+)_zpid/", url)
    if m:
        return m.group(1)

    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None

    zpids = _extract_zpids_from_next_data(r.text)
    return zpids[0] if zpids else None

def find_zpid(address: str) -> Optional[str]:
    """
    High level entry point.
    First try the search page JSON method.
    Optionally you can add a Playwright fallback if you hit JS-only flows.
    """
    # 1) Fast path via search page
    zpid = search_zpid_via_address(address)
    if zpid:
        return zpid

    # 2) Optional: Playwright fallback
    # Uncomment to use if needed
    # try:
    #     from playwright.sync_api import sync_playwright
    #     with sync_playwright() as p:
        #     browser = p.chromium.launch(headless=True)
        #     page = browser.new_page()
        #     page.goto(f"{ZILLOW_HOME}/homes/{urllib.parse.quote(address)}_rb/", wait_until="domcontentloaded")
        #     html = page.content()
        #     browser.close()
        #     zpids = _extract_zpids_from_next_data(html)
        #     return zpids[0] if zpids else None
    # except Exception:
    #     return None

    return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python zpid_lookup.py '2450 Clairview St, Alpharetta, GA 30009'")
        sys.exit(1)
    addr = " ".join(sys.argv[1:])
    z = find_zpid(addr)
    print(json.dumps({"address": addr, "zpid": z}, indent=2))