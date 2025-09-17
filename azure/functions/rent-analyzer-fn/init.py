import os, json, math, logging
import azure.functions as func
from openai import AzureOpenAI

app = func.FunctionApp()

# =========================
# Settings
# =========================
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# Optional heuristics when we lack a county API:
# If you don’t have a real property-tax provider yet, we’ll estimate:
#   GA-style example: assessed value = 40% of market * millage/1000  (non-homestead)
# Fallback: property_tax_rate_pct of value (annual)
DEFAULT_PROPERTY_TAX_RATE_PCT = float(os.getenv("DEFAULT_PROPERTY_TAX_RATE_PCT", "1.10"))  # % of value per year
GA_ASSESSMENT_RATIO           = float(os.getenv("GA_ASSESSMENT_RATIO", "40.0"))            # %
GA_MILLAGE_PER_1000           = float(os.getenv("GA_MILLAGE_PER_1000", "33.0"))            # e.g., 33 mills
ASSUME_GEORGIA_STYLE          = os.getenv("ASSUME_GEORGIA_STYLE", "0") == "1"

# If you wire a county API later, flip this:
ENABLE_COUNTY_TAX_PROVIDER    = os.getenv("ENABLE_COUNTY_TAX_PROVIDER", "0") == "1"
COUNTY_TAX_API_URL            = os.getenv("COUNTY_TAX_API_URL", "")  # your internal provider endpoint

# =========================
# Small utils
# =========================
def _n(v, d=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def _pmt(rate_pct: float, years: float, loan_amount: float) -> float:
    r = _n(rate_pct) / 100.0 / 12.0
    nper = int(_n(years) * 12.0)
    P = _n(loan_amount)
    if P <= 0 or nper <= 0: return 0.0
    if r == 0: return P / nper
    return P * (r / (1 - (1 + r) ** (-nper)))

def _cors():
    return {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "POST, OPTIONS, GET",
        "access-control-allow-headers": "content-type"
    }

def _bad_request(msg: str) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"ok": False, "error": msg}),
                             status_code=400, mimetype="application/json", headers=_cors())

# =========================
# Optional: county/property providers (stubs)
# =========================
def _fetch_taxes_from_county(inputs: dict) -> dict | None:
    """
    Hook for your real provider (county API, internal DB, etc).
    Expected return:
      {
        "prior_year": 2024,
        "prior_amount": 3896.00,
        "current_year_est": 4020.00,
        "source": "dekalb_api"
      }
    Return None if not available.
    """
    if not ENABLE_COUNTY_TAX_PROVIDER or not COUNTY_TAX_API_URL:
        return None
    try:
        # Example: POST to your internal microservice
        # import requests
        # res = requests.post(COUNTY_TAX_API_URL, json={
        #     "address": inputs.get("address"),
        #     "city": inputs.get("city"),
        #     "state": inputs.get("state"),
        #     "zip": inputs.get("zip")
        # }, timeout=12)
        # if res.ok:
        #     data = res.json()
        #     # normalize keys if needed
        #     return {
        #         "prior_year": int(data["prior_year"]),
        #         "prior_amount": float(data["prior_amount"]),
        #         "current_year_est": float(data["current_year_est"]),
        #         "source": data.get("source", "county_api")
        #     }
        return None  # placeholder
    except Exception as e:
        logging.warning("county tax provider error: %s", e)
        return None

def _estimate_taxes_fallback(inputs: dict) -> dict:
    """
    Heuristics if no county data is available.
    If ASSUME_GEORGIA_STYLE=1: tax = (value * 40%) * (millage/1000)
    Else: tax = DEFAULT_PROPERTY_TAX_RATE_PCT% * value
    Prior year = ~current_est / 1.03 (small inflation/roll)
    """
    value = _n(inputs.get("purchasePrice")) or _n(inputs.get("value")) or _n(inputs.get("homeValue"))
    if value <= 0:
        return {"source": "fallback", "prior_year": None, "prior_amount": None, "current_year_est": None}

    if ASSUME_GEORGIA_STYLE:
        assessed = value * (GA_ASSESSMENT_RATIO / 100.0)
        current_est = assessed * (GA_MILLAGE_PER_1000 / 1000.0)
    else:
        current_est = value * (DEFAULT_PROPERTY_TAX_RATE_PCT / 100.0)

    prior_amount = current_est / 1.03  # simple roll assumption
    now_year = 2025  # or derive from datetime.date.today().year
    return {
        "source": "fallback",
        "prior_year": now_year - 1,
        "prior_amount": round(prior_amount, 2),
        "current_year_est": round(current_est, 2)
    }

# =========================
# Azure OpenAI: Pre-AI for rent + expenses
# =========================
def _aoai_client() -> AzureOpenAI | None:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        return None
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

def _pre_ai_estimate(inputs: dict, tax_block: dict | None) -> dict | None:
    """
    Ask AOAI to estimate rent + expenses given address & basic context,
    and to incorporate any county/fallback tax info we already collected.
    Returns JSON like:
    {
      "rent": {"est": 2084, "low": 1950, "high": 2300, "confidence": "medium", "notes": "..."},
      "expenses": {
        "tax_prior_year": {"year": 2024, "amount": 3896, "source": "dekalb_api"},
        "tax_current_year_est": 4020,
        "insurance_annual_est": 1400,
        "hoa_monthly_est": 0,
        "pm_pct_est": 8,
        "maint_pct_est": 8,
        "utilities_monthly_est": 0,
        "restriction_hint": "Likely no HOA; verify CCRs."
      }
    }
    """
    client = _aoai_client()
    if not client:
        return None

    # Build the input context for the model
    tax_hint = tax_block or {}
    system = (
        "You estimate fair-market long-term monthly rent and typical expense lines for a rental. "
        "Return ONLY JSON. Keep fields numeric where possible; use whole numbers for percents."
    )
    user = {
        "task": "rental_prefetch",
        "address": inputs.get("address"),
        "city": inputs.get("city"),
        "state": inputs.get("state"),
        "zip": inputs.get("zip"),
        "propertyType": inputs.get("propertyType") or "Unknown",
        "units": inputs.get("units") or 1,
        "hints": {
            "price_or_value": inputs.get("purchasePrice") or inputs.get("homeValue"),
            "known_taxes": tax_hint
        },
        "output_format": {
            "type": "object",
            "properties": {
                "rent": {
                    "type": "object",
                    "properties": {
                        "est": {"type": "number"},
                        "low": {"type": "number"},
                        "high": {"type": "number"},
                        "confidence": {"type": "string"},
                        "notes": {"type": "string"}
                    },
                    "required": ["est"]
                },
                "expenses": {
                    "type": "object",
                    "properties": {
                        "tax_prior_year": {
                            "type": "object",
                            "properties": {
                                "year": {"type": "number"},
                                "amount": {"type": "number"},
                                "source": {"type": "string"}
                            }
                        },
                        "tax_current_year_est": {"type": "number"},
                        "insurance_annual_est": {"type": "number"},
                        "hoa_monthly_est": {"type": "number"},
                        "pm_pct_est": {"type": "number"},
                        "maint_pct_est": {"type": "number"},
                        "utilities_monthly_est": {"type": "number"},
                        "restriction_hint": {"type": "string"}
                    },
                    "required": ["tax_current_year_est"]
                }
            },
            "required": ["rent", "expenses"]
        }
    }

    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user)}
            ],
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logging.warning("pre-AI estimate failed: %s", e)
        return None

# =========================
# Step 2: Analysis math (uses prefetch values unless user overrides)
# =========================
def _analyze(inputs: dict) -> dict:
    # rent preference: user input > prefetch.est > 0
    rent = _n(inputs.get("rent"))
    pre = inputs.get("prefetch") or {}
    pre_rent = _n(((pre.get("rent") or {}).get("est")))
    if rent <= 0 and pre_rent > 0:
        rent = pre_rent

    # expenses preferences:
    tax_annual = _n(inputs.get("taxAnnual"))
    if tax_annual <= 0:
        tax_annual = _n((pre.get("expenses") or {}).get("tax_current_year_est"))

    ins_annual = _n(inputs.get("insAnnual"))
    if ins_annual <= 0:
        ins_annual = _n((pre.get("expenses") or {}).get("insurance_annual_est"))

    hoa_monthly = _n(inputs.get("hoaMonthly"))
    if hoa_monthly <= 0:
        hoa_monthly = _n((pre.get("expenses") or {}).get("hoa_monthly_est"))

    pm_pct = _n(inputs.get("pmPct"))
    if pm_pct <= 0:
        pm_pct = _n((pre.get("expenses") or {}).get("pm_pct_est"))

    maint_pct = _n(inputs.get("maintPct"))
    if maint_pct <= 0:
        maint_pct = _n((pre.get("expenses") or {}).get("maint_pct_est"))

    utilities_monthly = _n(inputs.get("utilitiesMonthly"))
    if utilities_monthly <= 0:
        utilities_monthly = _n((pre.get("expenses") or {}).get("utilities_monthly_est"))

    # base numerics
    price         = _n(inputs.get("purchasePrice"))
    down_pct      = _n(inputs.get("downPct"))
    rate          = _n(inputs.get("rate"))
    years         = _n(inputs.get("termYears"))
    closing_costs = _n(inputs.get("closingCosts"))
    points_pct    = _n(inputs.get("pointsPct"))
    other_income  = _n(inputs.get("otherIncome"))
    vacancy_pct   = _n(inputs.get("vacancyPct"), 5.0)

    down_payment  = price * (down_pct / 100.0)
    loan_amount   = max(price - down_payment, 0.0)
    points_cost   = loan_amount * (points_pct / 100.0)
    pi            = _pmt(rate, years, loan_amount)

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
        "explanation": "Uses preflight AI/heuristics for rent & expenses when not overridden."
    }

# =========================
# Routes
# =========================
@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"ok": true}', mimetype="application/json", headers=_cors())

# ---- Step 1: Prefetch (AI + county/fallback) ----
@app.function_name(name="rent_prefetch")
@app.route(route="rent-prefetch", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def rent_prefetch(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        body = req.get_json()
    except ValueError:
        return _bad_request("Invalid JSON body.")

    inputs = (body or {}).get("inputs") or {}
    if not inputs.get("state") and not inputs.get("zip"):
        return _bad_request("Provide at least 'state' or 'zip' for better estimates.")

    # 1) County provider first (if configured). Else heuristic fallback.
    county = _fetch_taxes_from_county(inputs)
    if not county:
        county = _estimate_taxes_fallback(inputs)

    # 2) AOAI pre-estimate (rent + line-item expense estimates)
    ai = _pre_ai_estimate(inputs, county)

    pre = {
        "ok": True,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "taxes": county,          # prior + current est (source: county_api or fallback)
        "ai": ai or None          # rent & expense estimates
    }
    return func.HttpResponse(json.dumps(pre, ensure_ascii=False),
                             mimetype="application/json", headers=_cors())

# ---- Step 2: Analyze (uses preflight if provided) ----
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
    # Expect the front end to pass `prefetch` from step 1 directly, but it’s optional.
    prefetch = (body or {}).get("prefetch") or {}
    # Flatten: make prefetch.ai/expenses/taxes visible to analyzer
    if prefetch:
        ai = prefetch.get("ai") or {}
        # Create a normalized block the analyzer expects
        inputs["prefetch"] = {
            "rent": ai.get("rent") or {},
            "expenses": (ai.get("expenses") or {}) | {
                # Preserve county numbers (they may be better than AI guesses)
                "tax_prior_year": (prefetch.get("taxes") or {}) and {
                    "year": (prefetch["taxes"].get("prior_year")),
                    "amount": (prefetch["taxes"].get("prior_amount")),
                    "source": (prefetch["taxes"].get("source", "unknown"))
                },
                "tax_current_year_est": (prefetch.get("taxes") or {}).get("current_year_est")
            }
        }

    # Minimal sanity: price & rate/term should be present for a mortgage calc
    if not math.isfinite(_n(inputs.get("purchasePrice"))):
        return _bad_request("'purchasePrice' is required.")
    if not math.isfinite(_n(inputs.get("rate"))) or not math.isfinite(_n(inputs.get("termYears"))):
        return _bad_request("'rate' and 'termYears' are required.")

    result = _analyze(inputs)
    # bubble the prefetch back so UI can show what was used
    result["prefetchUsed"] = bool(inputs.get("prefetch"))
    return func.HttpResponse(json.dumps(result, ensure_ascii=False),
                             mimetype="application/json", headers=_cors())