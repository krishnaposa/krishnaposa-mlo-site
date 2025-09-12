from shared import cosmos, roi

def main(pulls: dict):
    # You could lookup the doc by id if you prefer; here pulls carry estimates
    est = pulls["estimates"]
    # Fetch assumptions from Cosmos:
    # (Assumes GatherData already persisted doc with ID)
    # but to keep it stateless, read assumptions now
    # We'll pass the ID in pulls if you prefer; for brevity, use a light pattern:
    # NOTE: For production, pass the analysis id and read the doc fresh.

    # Dummy assumptions (you should read from Cosmos by ID instead)
    dpPct=20; rate=6.75; term=30; rehab=0; vacancyPct=5; mgmtPct=8; holdYears=10; closingPct=2; maintPct=5

    metrics = roi.compute_metrics(
        price_est=est["price_est"],
        rent_est=est["rent_est"],
        taxes_mo=est["taxes_month"],
        ins_mo=est["ins_month"],
        hoa_mo=est["hoa_month"],
        vacancy_pct=vacancyPct,
        mgmt_pct=mgmtPct,
        maint_pct=maintPct,
        rate=rate,
        term=term,
        dp_pct=dpPct,
        closing_costs_pct=closingPct,
        rehab=rehab,
        hold_years=holdYears,
        hpi_growth=est["hpi_growth"]
    )
    return {"estimates": est, "metrics": metrics}