# parse_property.py
from capture import fetch_redfin_data_smart

def parse_property(url: str, *, headless=True):
    smart = fetch_redfin_data_smart(url, headless=headless, dump_blobs=True)
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
            "rent_monthly_est": est.get("rent_monthly_est"),
            "rent_range": est.get("rent_range"),
        }
    }