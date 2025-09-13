# Activities/GatherData/__init__.py
from shared import cosmos
from shared.providers import (
    rentcast_property_search, rentcast_rent_estimate, rentcast_avm,
    fhfa_state_cagr, normalize_estimates
)

def main(analysis_id: str):
    doc = cosmos.get_doc(analysis_id)
    a = doc["assumptions"]
    addr = doc["address"]

    # 1) Try RentCast
    prop = {}
    try:
        prop = rentcast_property_search(addr["line1"], addr["city"], addr["state"], addr["zip"])
    except Exception:
        prop = {}

    beds = prop.get("bedrooms")
    baths = prop.get("bathrooms")
    sqft  = prop.get("squareFootage") or prop.get("livingArea")

    rent_resp = {}
    try:
        rent_resp = rentcast_rent_estimate(addr["line1"], addr["city"], addr["state"], addr["zip"], beds, baths, sqft)
    except Exception:
        rent_resp = {}

    value_resp = {}
    try:
        value_resp = rentcast_avm(addr["line1"], addr["city"], addr["state"], addr["zip"])
    except Exception:
        value_resp = {}

    # 2) Normalize + fallbacks (tax/insurance heuristics)
    est = normalize_estimates(addr, rent_resp, value_resp, addr["state"])

    # 3) FHFA HPI CAGR for appreciation (free)
    hpi_growth = fhfa_state_cagr(addr["state"], years=int(a.get("holdYears", 10))) or 0.02
    est["hpi_growth"] = float(hpi_growth)

    pulls = {
        "address": addr,
        "sources": ["rentcast", "fhfa_hpi"],
        "raw": {
            "rentcast_prop": prop,
            "rentcast_rent": rent_resp,
            "rentcast_value": value_resp
        },
        "estimates": est
    }

    # Persist interim
    doc["status"] = "running"
    doc["pulls"] = pulls
    doc["estimates"] = est
    cosmos.upsert_doc(doc)
    return pulls