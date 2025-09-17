# routes/portfolio_rank.py
import os
import json
import logging
import traceback
from typing import Any, Dict, List, Optional
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put
from openai import AzureOpenAI

# --- AOAI config (do not default to someone else's endpoint) ---
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# --- Caching ---
CACHE_GROUP   = "portfolio-rank"
CACHE_TTL_SEC = int(os.getenv("PORTFOLIO_RANK_TTL_SEC", "21600"))  # 6h


def _client() -> AzureOpenAI:
    """
    Create an AOAI client or raise with a clear message if misconfigured.
    """
    missing = [k for k, v in {
        "AZURE_OPENAI_ENDPOINT": AZURE_OPENAI_ENDPOINT,
        "AZURE_OPENAI_API_KEY": AZURE_OPENAI_API_KEY,
        "AZURE_OPENAI_DEPLOYMENT": AZURE_OPENAI_DEPLOYMENT
    }.items() if not v]
    if missing:
        raise RuntimeError(f"AOAI env missing: {', '.join(missing)}")
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
    )


def _compact_item(x: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """
    Normalize incoming items for the ranker prompt. Keeps only the fields
    that the AI needs and our fallback sorter can use.
    """
    m = (x or {}).get("metrics") or {}
    pre = (x or {}).get("prefetch") or {}
    ai = (pre.get("ai") or {})
    hoa_hint = (ai.get("expenses") or {}).get("restriction_hint")
    return {
        "idx": idx,
        "address": x.get("address") or ", ".join([
            s for s in [
                (x.get("inputs") or {}).get("address"),
                (x.get("inputs") or {}).get("city"),
                (x.get("inputs") or {}).get("state"),
                (x.get("inputs") or {}).get("zip"),
            ] if s
        ]),
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
        "notes": (x or {}).get("explanation"),
    }


def _rank_with_ai(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Call AOAI to obtain a ranked order and rationales.
    Raises on any error so caller can decide fallback vs. error out.
    """
    client = _client()
    system = (
        "You are an investment analyst for residential rentals. "
        "Rank the properties by expected investment attractiveness for a long-term buy-and-hold investor. "
        "Prioritize: (1) positive monthly cash flow, (2) higher cash-on-cash, (3) DSCR >= 1.20 (warn if < 1.0), "
        "(4) 5-year total return if available (cash flow + appreciation), (5) reasonableness vs price. "
        "Penalize serious HOA rental restrictions; do not penalize STR bans for long-term rentals. "
        "Return ONLY JSON per schema."
    )
    schema = {
        "type": "object",
        "properties": {
            "order":  {"type": "array", "items": {"type": "integer"}},
            "ranked": {"type": "array", "items": {"type": "object", "properties": {
                "idx": {"type": "integer"},
                "rank": {"type": "integer"},
                "score": {"type": "number"},
                "rationale": {"type": "string"},
                "pros": {"type": "array", "items": {"type": "string"}},
                "cons": {"type": "array", "items": {"type": "string"}},
                "flags": {"type": "string"}
            }}}},
            "summary": {"type": "string"}
        },
        "required": ["order", "ranked"]
    }
    user = {
        "task": "rank_rentals",
        "schema": schema,
        "items": items,
        "notes": [
            "Use cash-on-cash to break ties among positive DSCR properties.",
            "If DSCR < 1.0, mark weak unless exceptional factors.",
            "Cap pros/cons at 3 each; be concise.",
            "Scores 0–100: 60+ investable, 80+ strong."
        ]
    }
    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,  # deployment name
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": json.dumps(user)},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def _fallback_order(compact: List[Dict[str, Any]]) -> List[int]:
    """
    Deterministic order when AI is disabled/unavailable:
    sort by cash_on_cash then cash_flow_monthly (desc).
    """
    order = list(range(len(compact)))
    order.sort(
        key=lambda i: (
            float(compact[i].get("cash_on_cash") or 0.0),
            float(compact[i].get("cash_flow_monthly") or 0.0),
        ),
        reverse=True,
    )
    return order


def run_portfolio_rank(items_raw: List[Dict[str, Any]], ai_mode: str = "auto") -> Dict[str, Any]:
    """
    Rank a set of rental deals.
      - ai_mode="auto"     : try AI first; on failure use fallback (default)
      - ai_mode="required" : must use AI; return error if AI fails
      - ai_mode="off"      : never call AI; use fallback
    """
    ai_mode = (ai_mode or "auto").lower().strip()
    compact = [_compact_item(x, i) for i, x in enumerate(items_raw)]

    # Cache key includes ai_mode so you can compare behaviors easily.
    cache_key = make_cache_key({"items": compact, "mode": ai_mode}, version="ranker-v3")

    # Best-effort cache GET
    try:
        cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    except Exception as e:
        logging.warning("[portfolio-rank] cache get failed: %s", e)
        cached = None
    if cached:
        return cached

    # OFF: skip AI altogether
    if ai_mode == "off":
        order = _fallback_order(compact)
        out = {"ok": True, "mode": "off", "order": order, "ranked": [], "summary": "", "items": compact}
        try:
            blob_cache_put(CACHE_GROUP, cache_key, out)
        except Exception as e:
            logging.warning("[portfolio-rank] cache put failed: %s", e)
        return out

    # AUTO / REQUIRED: try AI
    try:
        ranked = _rank_with_ai(compact)
        order = [i for i in ranked.get("order", []) if isinstance(i, int) and 0 <= i < len(compact)]
        if not order:
            order = _fallback_order(compact)
        out = {
            "ok": True,
            "mode": "ai",
            "order": order,
            "ranked": ranked.get("ranked", []),
            "summary": ranked.get("summary", ""),
            "items": compact
        }
        try:
            blob_cache_put(CACHE_GROUP, cache_key, out)
        except Exception as e:
            logging.warning("[portfolio-rank] cache put failed: %s", e)
        return out

    except Exception as e:
        logging.exception("portfolio-rank AI error")
        if ai_mode == "required":
            # Fail fast: do NOT fallback
            return {
                "ok": False,
                "mode": "required",
                "error": str(e),
                "items": compact,
                "debug": {
                    "endpoint_set": bool(AZURE_OPENAI_ENDPOINT),
                    "deployment_set": bool(AZURE_OPENAI_DEPLOYMENT),
                    "has_key": bool(AZURE_OPENAI_API_KEY),
                    "api_version": AZURE_OPENAI_API_VER,
                    "trace_tail": traceback.format_exc()[-800:]
                }
            }

        # AUTO: fallback order
        order = _fallback_order(compact)
        out = {
            "ok": True,
            "mode": "fallback",
            "order": order,
            "ranked": [],
            "summary": "",
            "items": compact,
            "debug": {
                "ai_failed": True,
                "error": str(e)
            }
        }
        try:
            blob_cache_put(CACHE_GROUP, cache_key, out)
        except Exception as e2:
            logging.warning("[portfolio-rank] cache put (fallback) failed: %s", e2)
        return out