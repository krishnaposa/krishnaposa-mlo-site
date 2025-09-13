# Activities/computeMetrics/__init__.py
from math import isfinite

try:
    from shared import cosmos
except Exception:
    cosmos = None


def _mortgage_pi(loan, annual_rate, years):
    """Monthly principal+interest payment for a fully amortizing fixed loan."""
    n = int(years) * 12
    r = float(annual_rate) / 100.0 / 12.0
    if n <= 0:
        return 0.0
    if r <= 0:
        return loan / n
    num = loan * r * (1 + r) ** n
    den = (1 + r) ** n - 1
    return num / den if den else 0.0


def _remaining_balance(loan, annual_rate, years, months_elapsed):
    """Remaining principal after `months_elapsed` payments."""
    n = int(years) * 12
    r = float(annual_rate) / 100.0 / 12.0
    m = int(months_elapsed)
    if n <= 0:
        return 0.0
    if r <= 0:
        # straight-line payoff
        paid = (loan / n) * m
        return max(loan - paid, 0.0)
    pmt = _mortgage_pi(loan, annual_rate, years)
    # Standard amortization closed-form
    return loan * ((1 + r) ** n - (1 + r) ** m) / (((1 + r) ** n) - 1)


def _irr_bisection(cfs, lo=-0.99, hi=0.8, iters=80):
    """Very simple IRR solver on annual cash flows; returns None when not solvable."""
    def npv(rate):
        t = 0
        s = 0.0
        for cf in cfs:
            s += cf / ((1 + rate) ** t)
            t += 1
        return s

    try:
        f_lo, f_hi = npv(lo), npv(hi)
        # Require a sign change
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


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if isfinite(x) else d
    except Exception:
        return d


def main(pulls: dict):
    if not pulls or "estimates" not in pulls:
        return {"metrics": {}, "estimates": {}, "error": "missing pulls/estimates"}

    est = pulls.get("estimates", {})
    analysis_id = pulls.get("id")

    # Load assumptions
    a = {}
    if cosmos and analysis_id:
        doc = cosmos.get_doc(analysis_id) or {}
        a = (doc.get("assumptions") or {})

    # Assumptions (with safe defaults)
    dpPct      = _f(a.get("dpPct"), 20)
    rate       = _f(a.get("rate"), 6.75)
    term       = int(_f(a.get("term"), 30))
    vacancyPct = _f(a.get("vacancyPct"), 5)
    mgmtPct    = _f(a.get("mgmtPct"), 8)
    maintPct   = _f(a.get("maintPct"), 5)
    rehab      = _f(a.get("rehab"), 0)
    closingPct = _f(a.get("closingPct"), 2)
    hold       = max(1, int(_f(a.get("holdYears"), 10)))  # at least 1 year

    # Merge rule: user value if >0, else estimate
    def pick(user_val, est_val):
        uv = _f(user_val, 0)
        ev = _f(est_val, 0)
        return uv if uv > 0 else ev

    price_est = max(0.0, pick(a.get("price_est"), est.get("price_est")))
    rent_est  = max(0.0, pick(a.get("rent_est"),  est.get("rent_est")))
    taxes_mo  = max(0.0, pick(a.get("taxes"),     est.get("taxes_month")))
    ins_mo    = max(0.0, pick(a.get("insurance"), est.get("ins_month")))
    hoa_mo    = max(0.0, pick(a.get("hoa"),       est.get("hoa_month")))
    appr      = _f(est.get("hpi_growth"), 0.02)  # CAGR fraction

    # Operating expenses (monthly)
    vac_mo   = rent_est * (vacancyPct / 100.0)
    mgmt_mo  = rent_est * (mgmtPct / 100.0)
    maint_mo = rent_est * (maintPct / 100.0)
    opex_mo  = taxes_mo + ins_mo + hoa_mo + vac_mo + mgmt_mo + maint_mo

    # Mortgage
    down_payment = price_est * (dpPct / 100.0)
    loan_amt     = max(price_est - down_payment, 0.0)
    pi_mo        = _mortgage_pi(loan_amt, rate, term)

    # NOI & cash flow
    noi_mo       = max(rent_est - opex_mo, 0.0)
    cash_flow_mo = noi_mo - pi_mo

    # Core metrics
    cap = (noi_mo * 12.0) / price_est if price_est > 1e-6 else 0.0
    cash_invested = max(0.0, down_payment + rehab + (closingPct / 100.0) * price_est)
    coc = (cash_flow_mo * 12.0) / cash_invested if cash_invested > 1e-6 else 0.0

    # Sale & payoff for IRR
    sale_price = price_est * ((1 + appr) ** hold)
    selling_costs = sale_price * 0.06  # 6% broker + misc; adjust if you like
    rem_balance = _remaining_balance(loan_amt, rate, term, months_elapsed=hold * 12)
    net_sale = max(sale_price - selling_costs - rem_balance, 0.0)

    # Annual cash flows: t0 outflow, hold-1 years of annual CF, then final year + net sale
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
        # Optional extra: DSCR (can be useful)
        "dscr": float(noi_mo / pi_mo) if pi_mo > 0 else None,
        "loan_amount": round(loan_amt, 2),
        "down_payment": round(down_payment, 2),
        "selling_costs": round(selling_costs, 2),
        "remaining_balance_at_sale": round(rem_balance, 2),
        "net_sale_proceeds": round(net_sale, 2),
    }

    # Return merged estimates too (what UI shows)
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