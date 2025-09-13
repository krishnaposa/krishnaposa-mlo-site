# Activities/gatherData/__init__.py
from shared import cosmos
from shared.providers import (
    rentcast_property_search, rentcast_rent_estimate, rentcast_avm,
    fhfa_state_cagr, normalize_estimates, get_zillow_hoa_by_address
)

def main(analysis_id: str):
    doc = cosmos.get_doc(analysis_id)
    a = doc["assumptions"]
    addr = doc["address"]

    debug = {"rentcast_prop": {}, "rentcast_rent": {}, "rentcast_value": {}, "zillow": {}, "notes": []}

    # 1) RentCast property profile (beds/baths/sqft)
    prop = {}
    try:
        prop = rentcast_property_search(addr["line1"], addr["city"], addr["state"], addr["zip"])
        debug["rentcast_prop"] = {"ok": True, "keys": list(prop.keys())}
    except Exception as e:
        debug["rentcast_prop"] = {"ok": False, "error": str(e)}
        debug["notes"].append("property_search_failed")

    beds = prop.get("bedrooms")
    baths = prop.get("bathrooms")
    sqft  = prop.get("squareFootage") or prop.get("livingArea")

    # 2) RentCast rent + value
    rent_resp = {}
    try:
        rent_resp = rentcast_rent_estimate(addr["line1"], addr["city"], addr["state"], addr["zip"], beds, baths, sqft)
        debug["rentcast_rent"] = {"ok": True, "keys": list(rent_resp.keys())}
    except Exception as e:
        debug["rentcast_rent"] = {"ok": False, "error": str(e)}
        debug["notes"].append("rent_estimate_failed")

    value_resp = {}
    try:
        value_resp = rentcast_avm(addr["line1"], addr["city"], addr["state"], addr["zip"])
        debug["rentcast_value"] = {"ok": True, "keys": list(value_resp.keys())}
    except Exception as e:
        debug["rentcast_value"] = {"ok": False, "error": str(e)}
        debug["notes"].append("avm_failed")

    # 3) Normalize + fallbacks (price/rent/tax/ins)
    est = normalize_estimates(addr, rent_resp, value_resp, addr["state"])

    # 4) HOA via Zillow (RapidAPI), if available
    hoa_val = 0.0
    try:
        hoa_val = get_zillow_hoa_by_address(addr["line1"], addr["city"], addr["state"], addr["zip"])
        debug["zillow"] = {"ok": True, "hoa": hoa_val}
    except Exception as e:
        debug["zillow"] = {"ok": False, "error": str(e)}
        debug["notes"].append("zillow_failed")
    if hoa_val and hoa_val > 0:
        est["hoa_month"] = float(hoa_val)

    # 5) FHFA/FRED HPI CAGR for appreciation
    try:
        hpi_growth = fhfa_state_cagr(addr["state"], years=int(a.get("holdYears", 10))) or 0.02
        est["hpi_growth"] = float(hpi_growth)
    except Exception as e:
        est["hpi_growth"] = 0.02
        debug["notes"].append(f"hpi_fallback:{e}")

    pulls = {
        "id": analysis_id,
        "address": addr,
        "sources": ["rentcast", "fhfa_hpi", "zillow"],
        "raw": {
            "rentcast_prop": prop,
            "rentcast_rent": rent_resp,
            "rentcast_value": value_resp
        },
        "debug": debug,
        "estimates": est
    }

    # Persist interim for status page
    doc["status"] = "running"
    doc["pulls"] = pulls
    doc["estimates"] = est
    cosmos.upsert_doc(doc)
    return pulls