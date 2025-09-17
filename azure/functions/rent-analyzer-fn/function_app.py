# function_app.py (root, next to host.json)
import json, logging
import azure.functions as func

# One FunctionApp so discovery never fails
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ---- Small helpers (or swap these with utils.common) ----
def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }

def _ok(payload: dict, status: int = 200):
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False),
        status_code=status, mimetype="application/json", headers=_cors_headers()
    )

def _err(msg: str, status: int = 400):
    return _ok({"ok": False, "error": msg}, status=status)

def _get_json(req: func.HttpRequest):
    try:
        return req.get_json()
    except ValueError:
        return None

# =========================================================
# HEALTH
# =========================================================
@app.function_name(name="health")
@app.route(route="health", methods=["GET","OPTIONS"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors_headers())
    return _ok({"ok": True})

# =========================================================
# ALL-EXPENSE  -> routes/all_expense.py : run_all_expense(inputs) -> dict
# =========================================================
@app.function_name(name="all_expense")
@app.route(route="all-expense", methods=["POST","OPTIONS"])
def all_expense(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors_headers())

    body = _get_json(req)
    if body is None:
        return _err("Invalid JSON body.")
    inputs = (body or {}).get("inputs") or {}

    try:
        from routes.all_expense import run_all_expense
        out = run_all_expense(inputs)  # returns dict
        return _ok(out)
    except Exception as e:
        logging.exception("all-expense error")
        return _err(str(e), status=500)

# =========================================================
# RENT-PREFETCH  -> routes/rent_prefetch.py : run_rent_prefetch(inputs) -> dict
# =========================================================
@app.function_name(name="rent_prefetch")
@app.route(route="rent-prefetch", methods=["POST","OPTIONS"])
def rent_prefetch(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors_headers())

    body = _get_json(req)
    if body is None:
        return _err("Invalid JSON body.")
    inputs = (body or {}).get("inputs") or {}

    try:
        from routes.rent_prefetch import run_rent_prefetch
        out = run_rent_prefetch(inputs)
        return _ok(out)
    except Exception as e:
        logging.exception("rent-prefetch error")
        return _err(str(e), status=500)

# =========================================================
# RENT-ANALYZE  -> routes/rent_analyze.py : run_rent_analyze(inputs, prefetch) -> dict
# =========================================================
@app.function_name(name="rent_analyze")
@app.route(route="rent-analyze", methods=["POST","OPTIONS"])
def rent_analyze(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors_headers())

    body = _get_json(req)
    if body is None:
        return _err("Invalid JSON body.")
    inputs   = (body or {}).get("inputs") or {}
    prefetch = (body or {}).get("prefetch") or {}

    try:
        from routes.rent_analyze import run_rent_analyze
        out = run_rent_analyze(inputs, prefetch)
        return _ok(out)
    except Exception as e:
        logging.exception("rent-analyze error")
        return _err(str(e), status=500)

# =========================================================
# PORTFOLIO-RANK  -> routes/portfolio_rank.py : run_portfolio_rank(items) -> dict
# =========================================================
@app.function_name(name="portfolio_rank")
@app.route(route="portfolio-rank", methods=["POST","OPTIONS"])
def portfolio_rank(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors_headers())

    body = _get_json(req)
    if body is None:
        return _err("Invalid JSON body.")
    items = (body or {}).get("items") or []
    if not isinstance(items, list) or not items:
        return _err("Provide 'items': array of rent-analyze outputs.")

    try:
        from routes.portfolio_rank import run_portfolio_rank
        out = run_portfolio_rank(items)
        return _ok(out)
    except Exception as e:
        logging.exception("portfolio-rank error")
        return _err(str(e), status=500)

# =========================================================
# TAX-ESTIMATE (AI route) -> routes/tax_estimate.py : run_tax_estimate(inputs) -> dict
# =========================================================
@app.function_name(name="tax_estimate")
@app.route(route="tax-estimate", methods=["POST","OPTIONS"])
def tax_estimate(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors_headers())

    body = _get_json(req)
    if body is None:
        return _err("Invalid JSON body.")
    inputs = (body or {}).get("inputs") or {}

    try:
        from routes.tax_estimate import run_tax_estimate
        out = run_tax_estimate(inputs)
        return _ok(out)
    except Exception as e:
        logging.exception("tax-estimate error")
        return _err(str(e), status=500)