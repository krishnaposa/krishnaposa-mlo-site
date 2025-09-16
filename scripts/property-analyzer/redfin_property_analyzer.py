#!/usr/bin/env python3
# redfin_property_analyzer.py
# Clean main entry: resolve → scrape → trends → finance (no debug dumps)

import time, json

from resolver import resolve_redfin_url
from parse_property import parse_property
from trends import redfin_zip_trend
from finance import mortgage_pi
from utils import extract_zip_from_any

def log(m):  print(f"[INFO] {m}", flush=True)
def warn(m): print(f"[WARN] {m}", flush=True)

def analyze(address: str,
            redfin_url_cli: str | None,
            price: float,
            down_pct: float,
            rate_pct: float,
            years: int,
            tax_annual: float | None = None,
            ins_annual: float | None = None,
            hoa_monthly: float | None = None,
            maint_pct: float = 1.0,
            vacancy_pct: float = 5.0,
            rent_monthly: float | None = None,
            *,
            headless: bool = True):
    t0 = time.time()

    # ---------- Resolve URL ----------
    log(f"Address input: {address}")
    url = resolve_redfin_url(address, redfin_url_cli)
    if not url:
        return {
            "ok": False,
            "error": "redfin_url_not_found",
            "hint": "Pass --redfin-url with a property link to skip search.",
            "input_address": address,
        }
    log(f"Resolved Redfin URL: {url}")

    # ---------- Scrape property ----------
    log("Scraping Redfin page for details …")
    prop = parse_property(url, headless=headless)
    if not isinstance(prop, dict):
        warn("Property scrape returned non-dict; continuing with safe defaults.")
        prop = {}

    parts = prop.get("address_parts") or {}
    details = prop.get("property_details") or {}

    # ---------- Trends (ZIP-level) ----------
    zip_guess = (
        parts.get("zip")
        or extract_zip_from_any(prop.get("address_text"))
        or extract_zip_from_any(address)
    )
    if zip_guess:
        log(f"Looking up ZIP trends for {zip_guess} …")
        market = redfin_zip_trend(zip_guess)
    else:
        warn("Could not infer ZIP for trends lookup.")
        market = {"error": "no_zip"}

    # ---------- Finance math ----------
    dp = price * down_pct / 100.0
    pi = mortgage_pi(price, dp, rate_pct, years)

    # monthly expenses (use overrides if provided; otherwise scraped; otherwise baseline)
    tax_m = (tax_annual / 12.0) if tax_annual is not None else ((details.get("property_tax_annual") or 0.0) / 12.0)
    ins_m = (ins_annual / 12.0) if ins_annual is not None else 100.0   # baseline if unknown
    hoa_m = hoa_monthly if hoa_monthly is not None else (details.get("hoa_monthly") or 0.0)
    maint_m = price * (maint_pct / 100.0) / 12.0

    # choose rent: CLI override first, else scraped estimate if you add it later
    rent_used = rent_monthly if rent_monthly is not None else details.get("rent_monthly_est")
    vac_m = (rent_used or 0.0) * (vacancy_pct / 100.0)

    op_ex = round(tax_m + ins_m + hoa_m + maint_m + vac_m, 2)

    cashflow = noi = cap_rate = coc = None
    if rent_used is not None:
        cashflow = round(rent_used - (pi + op_ex), 2)
        noi = round(((rent_used - vac_m) * 12.0) - ((tax_m + ins_m + hoa_m + maint_m) * 12.0), 2)
        cap_rate = round((noi / price) * 100.0, 2) if price else None
        coc = round(((cashflow * 12.0) / dp) * 100.0, 2) if dp > 0 else None

    # ---------- Assemble result ----------
    out = {
        "ok": True,
        "timing_sec": round(time.time() - t0, 2),
        "redfin_url": url,
        "input": {
            "address": address,
            "purchase_price": price,
            "down_pct": down_pct,
            "rate_pct": rate_pct,
            "years": years,
            "tax_annual_override": tax_annual,
            "ins_annual_override": ins_annual,
            "hoa_monthly_override": hoa_monthly,
            "maintenance_pct": maint_pct,
            "vacancy_pct": vacancy_pct,
            "rent_monthly": rent_monthly,
        },
        "property": prop,
        "market_zip": market,
        "finance": {
            "down_payment": round(dp, 2),
            "monthly_pi": round(pi, 2),
            "operating_expenses_monthly": op_ex,
            "cashflow_monthly": cashflow,
            "noi_annual": noi,
            "cap_rate_pct": cap_rate,
            "cash_on_cash_pct": coc,
        },
        "notes": [
            "Resolver order: --redfin-url → search/autocomplete.",
            "Scrape pulls values from Redfin page (globals/DOM).",
            "ZIP trends sourced via Kaggle CSV in trends.py.",
            "Insurance defaults to $100/mo if not provided.",
            "Provide rent_monthly (or add a rent scraper) to compute cash flow/ROI.",
        ],
    }
    log("Analysis complete.")
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Redfin property analyzer (clean, no debug dumps).")
    ap.add_argument("address", help="Street, City, State ZIP")
    ap.add_argument("--redfin-url", default=None, help="Known Redfin property URL to skip search.")
    ap.add_argument("--price", type=float, required=True, help="Purchase price")
    ap.add_argument("--down-pct", type=float, default=20.0)
    ap.add_argument("--rate-pct", type=float, default=6.5)
    ap.add_argument("--years", type=int, default=30)
    ap.add_argument("--tax-annual", type=float, default=None)
    ap.add_argument("--ins-annual", type=float, default=None)
    ap.add_argument("--hoa-monthly", type=float, default=None)
    ap.add_argument("--maintenance-pct", type=float, default=1.0)
    ap.add_argument("--vacancy-pct", type=float, default=5.0)
    ap.add_argument("--rent-monthly", type=float, default=None)
    ap.add_argument("--headful", action="store_true", help="Show browser while scraping.")
    args = ap.parse_args()

    res = analyze(
        address=args.address,
        redfin_url_cli=args.redfin_url,
        price=args.price,
        down_pct=args.down_pct,
        rate_pct=args.rate_pct,
        years=args.years,
        tax_annual=args.tax_annual,
        ins_annual=args.ins_annual,
        hoa_monthly=args.hoa_monthly,
        maint_pct=args.maintenance_pct,
        vacancy_pct=args.vacancy_pct,
        rent_monthly=args.rent_monthly,
        headless=not args.headful,
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()