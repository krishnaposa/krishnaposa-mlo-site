# RentAI/__init__.py
import os, json, math, logging
import azure.functions as func
import requests
from openai import AzureOpenAI

app = func.FunctionApp()

# ---------- Settings ----------
# Optional: simple rate buydown heuristic (bps per point). Set 0 to disable.
RATE_BUYDOWN_BPS_PER_POINT = float(os.getenv("RATE_BUYDOWN_BPS_PER_POINT", "0"))  # e.g., "25" = 0.25% per point

# Azure OpenAI (optional)
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# ---------- Small utils ----------
def _n(v, d=0.0):
    try:
        x = float(v)
        if math.isfinite(x):
            return x
        return d
    except Exception:
        return d

def _pct_str(x, digits=2):
    try:
        return f"{float(x):.{digits}f}%"
    except Exception:
        return "0%"

def _cors():
    return {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "POST, OPTIONS, GET",
        "access-control-allow-headers": "content-type"
    }

def _bad_request(msg: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"ok": False, "error": msg}),
        status_code=400,
        mimetype="application/json",
        headers=_cors()
    )

def _pmt(rate_pct: float, years: float, loan_amount: float) -> float:
    """Monthly principal+interest payment (standard amortization)."""
    r = _n(rate_pct) / 100.0 / 12.0
    nper = int(_n(years) * 12.0)
    P = _n(loan_amount)
    if P <= 0 or nper <= 0:
        return 0.0
    if r == 0:
        return P / nper
    return P * (r / (1 - (1 + r) ** (-nper)))

# ---------- Core analysis ----------
def _analyze(inputs: dict) -> dict:
    # normalize numerics
    price            = _n(inputs.get("purchasePrice"))
    down_pct         = _n(inputs.get("downPct"))
    raw_rate         = _n(inputs.get("rate"))
    years            = _n(inputs.get("termYears"))
    closing_costs    = _n(inputs.get("closingCosts"))
    points_pct       = _n(inputs.get("pointsPct"))

    rent             = _n(inputs.get("rent"))
    other_income     = _n(inputs.get("otherIncome"))
    vacancy_pct      = _n(inputs.get("vacancyPct"), 5.0)

    tax_annual       = _n(inputs.get("taxAnnual"))
    ins_annual       = _n(inputs.get("insAnnual"))
    hoa_monthly      = _n(inputs.get("hoaMonthly"))
    pm_pct           = _n(inputs.get("pmPct"))
    maint_pct        = _n(inputs.get("maintPct"))
    utilities_monthly= _n(inputs.get("utilitiesMonthly"))

    # Optional: simple rate buydown via points
    eff_rate = raw_rate
    if RATE_BUYDOWN_BPS_PER_POINT > 0 and points_pct > 0:
        eff_rate = max(0.0, raw_rate - (points_pct * RATE_BUYDOWN_BPS_PER_POINT / 100.0))

    # loan + upfront
    down_payment     = price * (down_pct / 100.0)
    loan_amount      = max(price - down_payment, 0.0)
    # Commonly points priced on loan amount; if you prefer price-based, swap to price * points_pct/100
    points_cost      = loan_amount * (points_pct / 100.0)
    pi               = _pmt(eff_rate, years, loan_amount)

    # income
    gross_income     = rent + other_income
    vacancy          = gross_income * (vacancy_pct / 100.0)
    effective_income = gross_income - vacancy

    # expenses (mgmt/maint as % of RENT; switch to effective_income if you prefer)
    management       = rent * (pm_pct / 100.0)
    maintenance      = rent * (maint_pct / 100.0)

    monthly_taxes    = tax_annual / 12.0
    monthly_ins      = ins_annual / 12.0

    fixed_exp        = monthly_taxes + monthly_ins + hoa_monthly + utilities_monthly
    variable_exp     = management + maintenance
    op_ex_monthly    = fixed_exp + variable_exp

    noi_monthly      = effective_income - op_ex_monthly
    noi_annual       = noi_monthly * 12.0

    debt_service_mo  = pi
    debt_service_yr  = pi * 12.0

    cashflow_monthly = effective_income - (op_ex_monthly + debt_service_mo)
    cashflow_annual  = cashflow_monthly * 12.0

    cap_rate         = (noi_annual / price * 100.0) if price > 0 else 0.0

    total_cash_close = down_payment + closing_costs + points_cost
    cash_on_cash     = (cashflow_annual / total_cash_close * 100.0) if total_cash_close > 0 else 0.0

    dscr             = (noi_monthly / debt_service_mo) if debt_service_mo > 0 else 0.0

    # sensitivity ±$100 rent
    sensitivity = []
    for delta in (-100, 0, 100):
        r2     = max(0.0, rent + delta)
        g2     = r2 + other_income
        vac2   = g2 * (vacancy_pct / 100.0)
        eff2   = g2 - vac2
        mgmt2  = r2 * (pm_pct / 100.0)
        maint2 = r2 * (maint_pct / 100.0)
        opx2   = fixed_exp + mgmt2 + maint2
        noi2   = eff2 - opx2
        cf2    = eff2 - (opx2 + debt_service_mo)
        dscr2  = (noi2 / debt_service_mo) if debt_service_mo > 0 else 0.0
        sensitivity.append({
            "rent": r2,
            "cashFlowMonthly": cf2,
            "dscr": dscr2
        })

    address = ", ".join([s for s in [
        inputs.get("address"), inputs.get("city"),
        inputs.get("state"), inputs.get("zip")
    ] if s])

    return {
        "address": address,
        "inputs": inputs,
        "metrics": {
            "price": price,
            "downPayment": down_payment,
            "loanAmount": loan_amount,
            "effectiveRatePct": eff_rate,
            "piMonthly": debt_service_mo,
            "monthlyIncome": effective_income,
            "monthlyExpenses": {
                "vacancy": vacancy,
                "taxes": monthly_taxes,
                "insurance": monthly_ins,
                "hoa": hoa_monthly,
                "management": management,
                "maintenance": maintenance,
                "utilities": utilities_monthly,
                "pi": debt_service_mo
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
            "totalCashToClose": total_cash_close,
            "debtServiceAnnual": debt_service_yr
        },
        "sensitivity": sensitivity,
        "rentalRestrictions": {
            "hasHoa": hoa_monthly > 0,
            "notes": inputs.get("rentalRules") or "Unknown"
        },
        "explanation": "Calculated from provided inputs. Educational estimate only."
    }

# ---------- Optional Azure OpenAI narrative ----------
def _annotate_with_aoai(analysis: dict) -> str | None:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        return None
    try:
        client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VER,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )
        prompt = (
            "You are a concise rental investment analyst. Using the JSON below, write an 80–120 word note "
            "covering strengths, risks, and roughly what rent level makes it cash-flow positive. Avoid hype.\n\n"
            + json.dumps({
                "address": analysis.get("address"),
                "metrics": analysis.get("metrics"),
                "sensitivity": analysis.get("sensitivity"),
                "hoaNotes": analysis.get("rentalRestrictions", {}).get("notes", "Unknown")
            })
        )
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.3,
            response_format={"type": "text"},
            messages=[
                {"role": "system", "content": "Be factual and concise. Avoid promises or guarantees."},
                {"role": "user", "content": prompt}
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception as e:
        logging.warning("AOAI annotation failed: %s", e)
        return None

# ---------- Health ----------
@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"ok": true}', mimetype="application/json", headers=_cors())

# ---------- Main: rent-analyze ----------
@app.function_name(name="rent_analyze")
@app.route(route="rent-analyze", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def rent_analyze(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        body = req.get_json()
    except ValueError:
        return _bad_request("Invalid JSON body.")

    inputs = (body or {}).get("inputs") or {}
    # minimal validation
    if not math.isfinite(_n(inputs.get("purchasePrice"))) or not math.isfinite(_n(inputs.get("rent"))):
        return _bad_request("Missing or invalid inputs: 'purchasePrice' and 'rent' are required numbers.")

    # compute metrics
    analysis = _analyze(inputs)

    # optional AOAI explanation
    note = _annotate_with_aoai(analysis)
    if note:
        analysis["explanation"] = note

    return func.HttpResponse(
        json.dumps(analysis, ensure_ascii=False),
        mimetype="application/json",
        headers=_cors()
    )