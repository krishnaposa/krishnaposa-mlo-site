import numpy as np
import numpy_financial as npf

def monthly_pi(loan, annual_rate, term_years):
    i = annual_rate/12.0
    n = int(term_years*12)
    if i == 0: return loan / n
    return loan * i * (1+i)**n / ((1+i)**n - 1)

def compute_metrics(price_est, rent_est, taxes_mo, ins_mo, hoa_mo,
                    vacancy_pct, mgmt_pct, maint_pct,
                    rate, term, dp_pct, closing_costs_pct, rehab,
                    hold_years, hpi_growth, sell_costs_pct=0.07, utilities_mo=0.0):
    dp = price_est * (dp_pct/100.0)
    loan = price_est - dp
    pi = monthly_pi(loan, rate/100.0, term)
    egi = rent_est * (1 - vacancy_pct/100.0)
    opex_mo = (taxes_mo + ins_mo + hoa_mo + utilities_mo
               + egi*(mgmt_pct/100.0) + egi*(maint_pct/100.0))
    noi_mo = egi - opex_mo
    cash_flow_mo = noi_mo - pi
    cap_rate = (noi_mo*12.0)/price_est if price_est else 0.0

    cash_in = dp + price_est*(closing_costs_pct/100.0) + rehab

    # IRR: yearly CFs + terminal equity (price growth - remaining balance - selling cost)
    # Approx amortization using numpy_financial pmt/principal schedule is complex; use npf.ipmt/ppmt loop
    months = int(term*12)
    rate_mo = (rate/100.0)/12.0
    bal = loan
    yearly_cfs = [-cash_in]
    for y in range(1, hold_years+1):
        year_cf = 12*cash_flow_mo
        # amortize 12 months of principal
        for m in range(12):
            # interest for current month
            interest = bal*rate_mo
            principal = pi - interest
            bal = max(bal - principal, 0.0)
        yearly_cfs.append(year_cf)
    price_term = price_est * ((1 + hpi_growth)**hold_years)
    net_sale = price_term * (1 - sell_costs_pct) - bal
    yearly_cfs[-1] += net_sale

    irr = npf.irr(yearly_cfs) if len(yearly_cfs) >= 2 else None
    irr10 = float(irr) if irr is not None else None

    return {
        "pi_month": round(float(pi), 2),
        "noi_month": round(float(noi_mo), 2),
        "cash_flow_month": round(float(cash_flow_mo), 2),
        "cap_rate": round(float(cap_rate), 4),
        "coc": round(float((cash_flow_mo*12.0)/cash_in), 4) if cash_in else None,
        "irr_years": hold_years,
        "irr": irr10
    }