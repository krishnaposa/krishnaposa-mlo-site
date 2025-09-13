from math import isfinite

try:
    from shared import cosmos
except Exception:
    cosmos = None

def _mortgage_pi(loan, annual_rate, years):
    n = int(years) * 12
    r = float(annual_rate) / 100.0 / 12.0
    if n <= 0:
        return 0.0
    if r <= 0:
        return loan / n
    num = loan * r * (1 + r) ** n
    den = (1 + r) ** n - 1
    return num / den if den else 0.0

def _irr_bisection(cfs, lo=-0.99, hi=0.8, iters=60):
    # Very simple IRR solver; returns None if not solvable
    def npv(rate):
        t = 0
        s = 0.0
        for cf in cfs:
            s += cf / ((1 + rate) ** t)
            t += 1
        return s
    try:
        f_lo, f_hi = npv(lo), npv(hi)
        if (f_lo > 0 and f_hi > 0) or (f_lo < 0 and f_hi < 0):
            return None
        for _ in range(iters):
            mid = (lo + hi) / 2
            f_mid = npv(mid)
            if abs(f_mid) < 1e-6:
                return mid
            if (f_lo > 0 and f_mid > 0) or (f_lo < 0 and f_mid < 0):
                lo, f_lo = mid, f_mid
            else:
                hi, f_hi = mid, f_mid
        return (lo + hi) / 2
    except Exception:
        return None

def main(pulls: dict):
    # pulls must include id + estimates from gatherData
    if not pulls or "estimates" not in pulls:
        return {"metrics": {}, "estimates": {}, "error": "missing pulls/estimates"}

    est = pulls.get("estimates", {})
    analysis_id = pulls.get("id")

    # Load assumptions from Cosmos
    a = {}
    if cosmos and analysis_id:
        doc = cosmos.get_doc(analysis_id) or {}
        a = (doc.get("assumptions") or {})
    # Assumptions (with safe defaults)
    dpPct      = float(a.get("dpPct", 20))
    rate       = float(a.get("rate", 6.75))
    term       = int(a.get("term", 30))
    vacancyPct = float(a.get("vacancyPct", 5))
    mgmtPct    = float(a.get("mgmtPct", 8))
    maintPct   = float(a.get("maintPct", 5))
    rehab      = float(a.get("rehab", 0))
    closingPct = float(a.get("closingPct", 2))

    # Merge rule: user value if > 0 else estimate
    def pick(user_val, est_val):
        try:
            uv = float(user_val or 0)
        except Exception:
            uv = 0.0
        return uv if uv > 0 else float(est_val or 0)

    price_est = pick(a.get("price_est"), est.get("price_est"))
    rent_est  = pick(a.get("rent_est"),  est.get("rent_est"))

    taxes_mo  = pick(a.get("taxes"),     est.get("taxes_month"))
    ins_mo    = pick(a.get("insurance"), est.get("ins_month"))
    hoa_mo    = pick(a.get("hoa"),       est.get("hoa_month"))
    appr      = float(est.get("hpi_growth") or 0.02)  # CAGR as fraction

    # Operating expenses (monthly)
    vac_mo  = rent_est * (vacancyPct / 100.0)
    mgmt_mo = rent_est * (mgmtPct / 100.0)
    maint_mo= rent_est * (maintPct / 100.0)
    opex_mo = taxes_mo + ins_mo + hoa_mo + vac_mo + mgmt_mo + maint_mo

    # Mortgage — down payment and loan
    down_payment = price_est * (dpPct / 100.0)
    loan_amt = max(price_est - down_payment, 0.0)
    pi_mo = _mortgage_pi(loan_amt, rate, term)

    # NOI and cash flow
    noi_mo = max(rent_est - opex_mo, 0.0)
    cash_flow_mo = noi_mo - pi_mo

    # Cap rate, CoC
    cap = (noi_mo * 12.0) / price_est if price_est > 0 else 0.0
    cash_invested = down_payment + rehab + (closingPct / 100.0) * price_est
    coc = (cash_flow_mo * 12.0) / cash_invested if cash_invested > 0 else 0.0

    # Simple IRR model (annual cfs): years of cash flow + sale at end of hold
    hold = int(a.get("holdYears", 10))
    sale_price = price_est * ((1 + appr) ** hold)
    # assume 6% selling costs
    net_sale = sale_price * 0.94 - (0)  # ignore loan payoff realism for a quick estimate
    # upfront outflow at t0
    c0 = -(cash_invested)
    annual_cf = cash_flow_mo * 12.0
    cfs = [c0] + [annual_cf] * (hold - 1) + [annual_cf + net_sale]
    irr = _irr_bisection(cfs)

    metrics = {
        "noi_month": round(noi_mo, 2),
        "cap_rate": float(cap),
        "pi_month": round(pi_mo, 2),
        "cash_flow_month": round(cash_flow_mo, 2),
        "coc": float(coc),
        "irr_years": hold,
        "irr": float(irr) if (irr is not None and isfinite(irr)) else None,
    }

    # Return both — orchestrator passes this to decideVerdict
    return {
        "metrics": metrics,
        "estimates": {
            "rent_est": rent_est,
            "price_est": price_est,
            "taxes_month": taxes_mo,
            "ins_month": ins_mo,
            "hoa_month": hoa_mo,
            "hpi_growth": appr
        }
    }