#!/usr/bin/env python3
# redfin_property_analyzer.py

import time, json

# --- project modules ---
from resolver import resolve_redfin_url
from parse_property import parse_property
from trends import redfin_zip_trend           # <- Kaggle-only trends() you set up
from finance import mortgage_pi
from utils import extract_zip_from_any

# Optional: use shared log/warn if you have them; otherwise define light fallbacks
try:
    from utils import log, warn
except Exception:  # fallbacks
    def log(msg: str):  print(f"[INFO] {msg}", flush=True)
    def warn(msg: str): print(f"[WARN] {msg}", flush=True)


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
    log("===== Property Analyzer (Redfin + Kaggle ZIP trends) =====")
    log(f"Address input: {address}")
    log(f"Financing: price={price}, down_pct={down_pct}%, rate={rate_pct}%, years={years}")
    log(f"Overrides: tax_annual={tax_annual}, ins_annual={ins_annual}, hoa_monthly={hoa_monthly}, "
        f"maint_pct={maint_pct}%, vacancy_pct={vacancy_pct}%, rent_monthly={rent_monthly}")
    log(f"Scrape mode: {'headless' if headless else 'headful'}")

    # -------- 1) Resolve Redfin URL --------
    url = resolve_redfin_url(address, redfin_url_cli)
    if not url:
        warn("Could not resolve a Redfin property URL.")
        return {
            "ok": False,
            "error": "redfin_url_not_found",
            "hint": "Provide --redfin-url with a property link.",
            "input_address": address
        }
    log(f"Resolved Redfin URL: {url}")

    # -------- 2) Scrape property page --------
    log("Scraping Redfin page for details (globals + network JSON + DOM heuristics)…")
    prop = parse_property(url, headless=headless)

    # Keep these robust against partial/None values
    if isinstance(prop, dict):
        prop_details = prop.get("property_details") or {}
        parts = prop.get("address_parts") or {}
        addr_text = prop.get("address_text")
    else:
        prop_details, parts, addr_text = {}, {}, None

    log(f"Scrape summary: HOA=${prop_details.get('hoa_monthly')}, "
        f"Taxes/yr={prop_details.get('property_tax_annual')}, "
        f"List/Last price={prop_details.get('list_price') or prop_details.get('last_sale_price')}, "
        f"Rent est={prop_details.get('rent_monthly_est')}")

    # -------- 3) ZIP trends (Kaggle-only) --------
    z = parts.get("zip") or extract_zip_from_any(addr_text) or extract_zip_from_any(address)
    if z:
        log(f"Fetching ZIP-level trend metrics via Kaggle dataset for ZIP {z}…")
        market = redfin_zip_trend(z)
        if "error" in (market or {}):
            warn(f"ZIP trend lookup error: {market.get('error')}")
    else:
        warn("Could not infer ZIP from page/address; skipping ZIP trend lookup.")
        market = {"error": "no_zip"}

    # -------- 4) Finance math --------
    dp = round(price * down_pct / 100.0, 2)
    pi = mortgage_pi(price, dp, rate_pct, years)

    # taxes / insurance / HOA precedence: user override → scraped → default
    tax_m = (tax_annual / 12.0) if tax_annual is not None else ((prop_details.get("property_tax_annual") or 0) / 12.0)
    ins_m = (ins_annual / 12.0) if ins_annual is not None else 100.0  # baseline monthly
    hoa_m = hoa_monthly if hoa_monthly is not None else (prop_details.get("hoa_monthly") or 0.0)
    maint_m = price * (maint_pct / 100.0) / 12.0

    # prefer user-specified rent, then scraped rent estimate if present
    rent_used = rent_monthly if rent_monthly is not None else prop_details.get("rent_monthly_est")
    vac_m = (rent_used or 0.0) * (vacancy_pct / 100.0)

    op_ex = round(tax_m + ins_m + hoa_m + maint_m + vac_m, 2)
    log(f"Monthly costs: tax={round(tax_m,2)}, ins={round(ins_m,2)}, hoa={round(hoa_m,2)}, "
        f"maint={round(maint_m,2)}, vacancy={round(vac_m,2)} → Opex={op_ex}")
    log(f"P&I monthly: {pi}")

    cashflow = noi = cap_rate = coc = None
    if rent_used is not None:
        cashflow = round(rent_used - (pi + op_ex), 2)
        noi = round((rent_used - vac_m) * 12.0 - (tax_m + ins_m + hoa_m + maint_m) * 12.0, 2)
        cap_rate = round(noi / price * 100.0, 2) if price else None
        coc = round((cashflow * 12.0) / dp * 100.0, 2) if dp > 0 else None
        log(f"Income math: rent={rent_used} ⇒ cashflow/mo={cashflow}, NOI/yr={noi}, "
            f"CapRate={cap_rate}%, CoC={coc}%")
    else:
        warn("No rent provided or scraped; cash flow & ROI metrics will be null.")

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
            "down_payment": dp,
            "monthly_pi": pi,
            "operating_expenses_monthly": op_ex,
            "cashflow_monthly": cashflow,
            "noi_annual": noi,
            "cap_rate_pct": cap_rate,
            "cash_on_cash_pct": coc,
        },
        "notes": [
            "Resolver order: --redfin-url → DuckDuckGo → Redfin Autocomplete JSON.",
            "Scrape: window globals + network JSON + DOM heuristics (JSON blobs dumped to ./rf_dumps/).",
            "Comparable rent range parsed from Redfin stingray payload URL when present.",
            "ZIP trends fetched from Kaggle (dataset: redfin/usa-housing-market).",
            "Math is defensive; fields default to 0 unless overridden.",
            "Insurance defaults to $100/mo if not provided.",
        ],
    }

    log(f"Finished in {out['timing_sec']}s.")
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Redfin analyzer (modular + Kaggle ZIP trends).")
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