# utils/common.py
import math, json
import azure.functions as func

def n(v, d=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def pmt(rate_pct: float, years: float, loan_amount: float) -> float:
    r = n(rate_pct) / 100.0 / 12.0
    nper = int(n(years) * 12.0)
    P = n(loan_amount)
    if P <= 0 or nper <= 0: return 0.0
    if r == 0: return P / nper
    return P * (r / (1 - (1 + r) ** (-nper)))

def cors_headers():
    return {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "POST, OPTIONS, GET",
        "access-control-allow-headers": "content-type"
    }

def bad_request(msg: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"ok": False, "error": msg}),
        status_code=400,
        mimetype="application/json",
        headers=cors_headers()
    )