#!/usr/bin/env python3
# redfin_property_analyzer.py
import time, json

from resolver import resolve_redfin_url
from parse_property import parse_property
from trends import redfin_zip_trend
from finance import mortgage_pi
from utils import extract_zip_from_any

def analyze(address: str, redfin_url_cli: str|None, price: float, down_pct: float,
            rate_pct: float, years: int, tax_annual: float|None=None,
            ins_annual: float|None=None, hoa_monthly: float|None=None,
            maint_pct: float=1.0, vacancy_pct: float=5.0, rent_monthly: float|None=None,
            *, headless=True):
    t0=time.time()

    url = resolve_redfin_url(address, redfin_url_cli)
    if not url:
        return {"ok":False, "error":"redfin_url_not_found",
                "hint":"Provide --redfin-url with a property link.",
                "input_address":address}

    prop = parse_property(url, headless=headless)
    prop_details = (prop.get("property_details") if isinstance(prop, dict) else None) or {}
    parts = (prop.get("address_parts") if isinstance(prop, dict) else None) or {}

    z = parts.get("zip") or extract_zip_from_any(prop.get("address_text")) or extract_zip_from_any(address)
    market = redfin_zip_trend(z) if z else {"error":"no_zip"}

    dp = price*down_pct/100
    pi = mortgage_pi(price, dp, rate_pct, years)

    tax_m = (tax_annual/12) if tax_annual is not None else ((prop_details.get("property_tax_annual") or 0)/12)
    ins_m = (ins_annual/12) if ins_annual is not None else 100
    hoa_m = hoa_monthly if hoa_monthly is not None else (prop_details.get("hoa_monthly") or 0)
    maint_m = price*(maint_pct/100)/12

    rent_used = rent_monthly if rent_monthly is not None else prop_details.get("rent_monthly_est")
    vac_m = (rent_used or 0)*(vacancy_pct/100)

    op_ex = round(tax_m + ins_m + hoa_m + maint_m + vac_m, 2)

    cashflow = noi = cap_rate = coc = None
    if rent_used is not None:
        cashflow = round(rent_used - (pi + op_ex), 2)
        noi = round((rent_used - (rent_used*(vacancy_pct/100))) * 12 - (tax_m + ins_m + hoa_m + maint_m)*12, 2)
        cap_rate = round(noi/price*100, 2) if price else None
        coc = round((cashflow*12)/dp * 100, 2) if dp>0 else None

    return {
        "ok": True,
        "timing_sec": round(time.time()-t0,2),
        "redfin_url": url,
        "input": {
            "address": address, "purchase_price": price, "down_pct": down_pct, "rate_pct": rate_pct, "years": years,
            "tax_annual_override": tax_annual, "ins_annual_override": ins_annual, "hoa_monthly_override": hoa_monthly,
            "maintenance_pct": maint_pct, "vacancy_pct": vacancy_pct, "rent_monthly": rent_monthly
        },
        "property": prop,
        "market_zip": market,
        "finance": {
            "down_payment": round(price*down_pct/100,2),
            "monthly_pi": pi,
            "operating_expenses_monthly": op_ex,
            "cashflow_monthly": cashflow,
            "noi_annual": noi,
            "cap_rate_pct": cap_rate,
            "cash_on_cash_pct": coc
        },
        "notes": [
            "Resolver: --redfin-url → DuckDuckGo → Redfin Autocomplete JSON.",
            "Scrape: window globals + network JSON + DOM heuristics (JSON blobs dumped to ./rf_dumps/).",
            "Comparable rent range parsed from Stingray payload URL when present.",
            "Math is defensive; fields default to 0 unless overridden.",
            "Insurance defaults to $100/mo if not provided."
        ]
    }

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Redfin analyzer (modular).")
    ap.add_argument("address", help="Street, City, State ZIP")
    ap.add_argument("--redfin-url", default=None, help="Known Redfin property URL to skip search.")
    ap.add_argument("--price", type=float, required=True)
    ap.add_argument("--down-pct", type=float, default=20)
    ap.add_argument("--rate-pct", type=float, default=6.5)
    ap.add_argument("--years", type=int, default=30)
    ap.add_argument("--tax-annual", type=float, default=None)
    ap.add_argument("--ins-annual", type=float, default=None)
    ap.add_argument("--hoa-monthly", type=float, default=None)
    ap.add_argument("--maintenance-pct", type=float, default=1.0)
    ap.add_argument("--vacancy-pct", type=float, default=5.0)
    ap.add_argument("--rent-monthly", type=float, default=None)
    ap.add_argument("--headful", action="store_true", help="Show browser when scraping the property page.")
    args = ap.parse_args()

    res = analyze(
        address=args.address, redfin_url_cli=args.redfin_url, price=args.price, down_pct=args.down_pct,
        rate_pct=args.rate_pct, years=args.years, tax_annual=args.tax_annual, ins_annual=args.ins_annual,
        hoa_monthly=args.hoa_monthly, maint_pct=args.maintenance_pct, vacancy_pct=args.vacancy_pct,
        rent_monthly=args.rent_monthly, headless=not args.headful
    )
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()