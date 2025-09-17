# routes/portfolio_rank.py
from app import app
import azure.functions as func
import json, os, logging
from typing import Any, Dict, List, Optional
from openai import AzureOpenAI

from utils.common import cors_headers, bad_request
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put, cache_headers

AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# Cache settings
CACHE_GROUP = "portfolio-rank"
CACHE_TTL_SEC = int(os.getenv("PORTFOLIO_RANK_TTL_SEC", "21600"))  # 6h

def _client() -> Optional[AzureOpenAI]:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        logging.warning("AOAI env not configured; ranker unavailable.")
        return None
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

def _compact_item(x: Dict[str, Any], idx: int) -> Dict[str, Any]:
    m = (x or {}).get("metrics") or {}
    pre = (x or {}).get("prefetch") or {}
    ai = (pre.get("ai") or {})
    hoa_hint = (ai.get("expenses") or {}).get("restriction_hint")
    return {
        "idx": idx,
        "address": x.get("address") or ", ".join([s for s in [
            (x.get("inputs") or {}).get("address"),
            (x.get("inputs") or {}).get("city"),
            (x.get("inputs") or {}).get("state"),
            (x.get("inputs") or {}).get("zip"),
        ] if s]),
        "price": m.get("price"),
        "rent": (x.get("inputs") or {}).get("rent") or ((ai.get("rent") or {}).get("est")),
        "cash_flow_monthly": m.get("cashFlowMonthly"),
        "cap_rate": m.get("capRate"),
        "cash_on_cash": m.get("cashOnCash"),
        "dscr": m.get("dscr"),
        "total_cash_to_close": m.get("totalCashToClose"),
        "total_return_pct_5y": m.get("totalReturnPctProjected"),
        "appreciation_pct": m.get("appreciationPct"),
        "hoa_restriction_hint": hoa_hint,
        "notes": (x or {}).get("explanation")
    }

def _rank_with_ai(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    client = _client()
    if not client:
        raise RuntimeError("Azure OpenAI not configured")

    system = (
        "You are an investment analyst for residential rentals. "
        "Rank the properties by expected investment attractiveness for a long-term buy-and-hold investor. "
        "Prioritize: (1) positive monthly cash flow, (2) higher cash-on-cash, (3) DSCR >= 1.20 preferred; warn if < 1.0, "
        "(4) 5-year total return if available (cash flow + appreciation), (5) reasonableness vs price. "
        "Penalize serious HOA rental restrictions; do not penalize STR bans for long-term rentals. "
        "Return ONLY JSON per schema."
    )
    schema = {
        "type":"object",
        "properties":{
            "order":{"type":"array","items":{"type":"integer"}},
            "ranked":{"type":"array","items":{"type":"object","properties":{
                "idx":{"type":"integer"},
                "rank":{"type":"integer"},
                "score":{"type":"number"},
                "rationale":{"type":"string"},
                "pros":{"type":"array","items":{"type":"string"}},
                "cons":{"type":"array","items":{"type":"string"}},
                "flags":{"type":"string"}
            }}}},
            "summary":{"type":"string"}
        },
        "required":["order","ranked"]
    }
    user = {
        "task":"rank_rentals",
        "schema": schema,
        "items": items,
        "notes": [
            "Use cash-on-cash as the key tie-breaker among positive DSCR properties.",
            "If DSCR < 1.0, mark as weak unless exceptional other factors.",
            "Cap pros/cons at 3 each; be concise.",
            "Scores 0–100: 60+ investable, 80+ strong."
        ]
    }
    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        temperature=0.1,
        response_format={"type":"json_object"},
        messages=[{"role":"system","content":system},
                  {"role":"user","content":json.dumps(user)}],
    )
    return json.loads(resp.choices[0].message.content)

@app.function_name(name="portfolio_rank")
@app.route(route="portfolio-rank", methods=["POST","OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def portfolio_rank(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers())

    try:
        body = req.get_json()
    except ValueError:
        return bad_request("Invalid JSON body.")

    items_raw = (body or {}).get("items") or []
    if not items_raw:
        return bad_request("Provide 'items': array of rent-analyze outputs.")

    compact = [_compact_item(x, i) for i, x in enumerate(items_raw)]

    # ---------- CACHE LOOKUP ----------
    cache_key = make_cache_key({"items": compact}, version="ranker-v2")
    cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    if cached:
        hdrs = {**cors_headers(), **cache_headers(True)}
        return func.HttpResponse(json.dumps(cached, ensure_ascii=False),
                                 mimetype="application/json", headers=hdrs)

    # ---------- COMPUTE THEN STORE ----------
    try:
        ranked = _rank_with_ai(compact)
        order = [i for i in ranked.get("order", []) if isinstance(i, int) and 0 <= i < len(compact)]
        if not order:
            order = list(range(len(compact)))
            order.sort(key=lambda i: (float(compact[i].get("cash_on_cash") or 0.0),
                                      float(compact[i].get("cash_flow_monthly") or 0.0)), reverse=True)

        out = {
            "ok": True,
            "order": order,
            "ranked": ranked.get("ranked", []),
            "summary": ranked.get("summary", ""),
            "items": compact
        }
        blob_cache_put(CACHE_GROUP, cache_key, out)
        hdrs = {**cors_headers(), **cache_headers(False)}
        return func.HttpResponse(json.dumps(out, ensure_ascii=False),
                                 mimetype="application/json", headers=hdrs)
    except Exception as e:
        logging.exception("portfolio-rank error")
        order = list(range(len(compact)))
        order.sort(key=lambda i: (float(compact[i].get("cash_on_cash") or 0.0),
                                  float(compact[i].get("cash_flow_monthly") or 0.0)), reverse=True)
        out = {"ok": False, "error": str(e), "order": order, "ranked": [], "summary":"", "items": compact}
        # Even on failure we can cache briefly to dampen hot loops (optional):
        blob_cache_put(CACHE_GROUP, cache_key, out)
        hdrs = {**cors_headers(), **cache_headers(False)}
        return func.HttpResponse(json.dumps(out, ensure_ascii=False),
                                 status_code=200, mimetype="application/json", headers=hdrs)