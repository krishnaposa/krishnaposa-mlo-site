from shared import cosmos

# TODO: replace heuristics with real API calls (RentCast/RapidAPI/ATTOM/etc.)
def main(id: str):
    doc = cosmos.get_doc(id)
    a = doc["assumptions"]
    addr = doc["address"]

    # Heuristic placeholders (wire real APIs here)
    rent_est = 2000.0
    price_est = 320000.0
    taxes_month = a.get("taxes", 0) or 320.0
    ins_month = a.get("insurance", 0) or 140.0
    hoa_month = a.get("hoa", 0) or 0.0
    hpi_growth = 0.028  # 2.8% annual

    pulls = {
        "address": addr,
        "sources": ["heuristic"],  # put raw API payloads here when integrated
        "estimates": {
            "rent_est": rent_est,
            "price_est": price_est,
            "taxes_month": taxes_month,
            "ins_month": ins_month,
            "hoa_month": hoa_month,
            "hpi_growth": hpi_growth
        }
    }
    # optional: save interim
    doc["status"] = "running"
    doc["pulls"] = pulls
    cosmos.upsert_doc(doc)
    return pulls