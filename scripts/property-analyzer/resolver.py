# resolver.py
import re, json, requests
from bs4 import BeautifulSoup

from constants import UA_STR, UA_HDRS
from utils import log, warn

def _redfin_strip_json_prefix(text: str) -> str:
    return re.sub(r"^\)\]\}'\s*", "", text or "")

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

def redfin_url_via_autocomplete(address: str) -> str | None:
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