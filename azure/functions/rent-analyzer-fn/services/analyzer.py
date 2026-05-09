# services/analyzer.py
from utils.common import n, pmt

def analyze(inputs: dict) -> dict:
    # Prefer user inputs, then prefetch (AI/county) values
    pre = inputs.get("prefetch") or {}
    pre_rent = n(((pre.get("rent") or {}).get("est")))
    rent = n(inputs.get("rent")) or pre_rent

    tax_annual = n(inputs.get("taxAnnual")) or n((pre.get("expenses") or {}).get("tax_current_year_est"))
    ins_annual = n(inputs.get("insAnnual")) or n((pre.get("expenses") or {}).get("insurance_annual_est"))
    hoa_monthly = n(inputs.get("hoaMonthly")) or n((pre.get("expenses") or {}).get("hoa_monthly_est"))
    pm_pct = n(inputs.get("pmPct")) or n((pre.get("expenses") or {}).get("pm_pct_est"))
    maint_pct = n(inputs.get("maintPct")) or n((pre.get("expenses") or {}).get("maint_pct_est"))
    utilities_monthly = n(inputs.get("utilitiesMonthly")) or n((pre.get("expenses") or {}).get("utilities_monthly_est"))

    price         = n(inputs.get("purchasePrice"))
    down_pct      = n(inputs.get("downPct"))
    rate          = n(inputs.get("rate"))
    years         = n(inputs.get("termYears"))
    closing_costs = n(inputs.get("closingCosts"))
    points_pct    = n(inputs.get("pointsPct"))
    other_income  = n(inputs.get("otherIncome"))
    vacancy_pct   = n(inputs.get("vacancyPct"), 5.0)

    down_payment  = price * (down_pct / 100.0)
    loan_amount   = max(price - down_payment, 0.0)
    points_cost   = loan_amount * (points_pct / 100.0)
    pi            = pmt(rate, years, loan_amount)

    gross_income     = rent + other_income
    vacancy          = gross_income * (vacancy_pct / 100.0)
    effective_income = gross_income - vacancy

    management       = rent * (pm_pct / 100.0)
    maintenance      = rent * (maint_pct / 100.0)
    monthly_taxes    = tax_annual / 12.0
    monthly_ins      = ins_annual / 12.0

    fixed_exp        = monthly_taxes + monthly_ins + hoa_monthly + utilities_monthly
    variable_exp     = management + maintenance
    op_ex_monthly    = fixed_exp + variable_exp

    noi_monthly      = effective_income - op_ex_monthly
    noi_annual       = noi_monthly * 12.0

    cashflow_monthly = effective_income - (op_ex_monthly + pi)
    cashflow_annual  = cashflow_monthly * 12.0
    cap_rate         = (noi_annual / price * 100.0) if price > 0 else 0.0
    total_cash_close = down_payment + closing_costs + points_cost
    cash_on_cash     = (cashflow_annual / total_cash_close * 100.0) if total_cash_close > 0 else 0.0
    dscr             = (noi_monthly / pi) if pi > 0 else 0.0

    address = ", ".join([s for s in [
        inputs.get("address"), inputs.get("city"), inputs.get("state"), inputs.get("zip")
    ] if s])

    return {
        "address": address,
        "inputs": inputs,
        "metrics": {
            "price": price,
            "downPayment": down_payment,
            "loanAmount": loan_amount,
            "piMonthly": pi,
            "monthlyIncome": effective_income,
            "monthlyExpenses": {
                "vacancy": vacancy,
                "taxes": monthly_taxes,
                "insurance": monthly_ins,
                "hoa": hoa_monthly,
                "management": management,
                "maintenance": maintenance,
                "utilities": utilities_monthly,
                "pi": pi
            },
            "noiMonthly": noi_monthly,
            "noiAnnual": noi_annual,
            "cashFlowMonthly": cashflow_monthly,
            "cashFlowAnnual": cashflow_annual,
            "capRate": cap_rate,
            "cashOnCash": cash_on_cash,
            "dscr": dscr,
            "pointsCost": points_cost,
            "closingCosts": closing_costs,
            "totalCashToClose": total_cash_close
        },
        "explanation": "Uses prefetch (AI/county) for rent & expenses when not overridden."
    }