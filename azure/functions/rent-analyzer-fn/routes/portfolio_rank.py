# routes/portfolio_rank.py
import os
import json
import logging
from typing import Any, Dict, List, Optional
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put
from openai import AzureOpenAI

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://stocks-ai.openai.azure.com/")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VER = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

CACHE_GROUP = "portfolio-rank"
CACHE_TTL_SEC = int(os.getenv("PORTFOLIO_RANK_TTL_SEC", "21600"))  # 6h


def _client() -> Optional[AzureOpenAI]:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        return None
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
    )


def _compact_item(x: Dict[str, Any], idx: int) -> Dict[str, Any]:
    m = (x or {}).get("metrics") or {}
    pre = (x or {}).get("prefetch") or {}
    ai = (pre.get("ai") or {})
    hoa_hint = (ai.get("expenses") or {}).get("restriction_hint")
    return {
        "idx": idx,
        "address": x.get("address")
        or ", ".join(
            [
                s
                for s in [
                    (x.get("inputs") or {}).get("address"),
                    (x.get("inputs") or {}).get("city"),
                    (x.get("inputs") or {}).get("state"),
                    (x.get("inputs") or {}).get("zip"),
                ]
                if s
            ]
        ),
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
    client = _client()
    if not client:
        raise RuntimeError("Azure OpenAI not configured")

    system = (
        "You are an investment analyst for residential rentals. "
        "Rank by attractiveness: positive monthly cash flow, higher cash-on-cash, DSCR>=1.20 (warn <1.0), "
        "5-year total return (cash flow + appreciation), reasonableness vs price. "
        "Penalize serious HOA rental restrictions; do not penalize STR bans for long-term. "
        "Return ONLY JSON per schema."
    )

    schema = {
        "type": "object",
        "properties": {
            "order": {"type": "array", "items": {"type": "integer"}},
            "ranked": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "idx": {"type": "integer"},
                        "rank": {"type": "integer"},
                        "score": {"type": "number"},
                        "rationale": {"type": "string"},
                        "pros": {"type": "array", "items": {"type": "string"}},
                        "cons": {"type": "array", "items": {"type": "string"}},
                        "flags": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["order", "ranked"],
    }

    user = {
        "task": "rank_rentals",
        "schema": schema,
        "items": items,
        "notes": [
            "Use cash-on-cash to break ties among positive DSCR properties.",
            "If DSCR < 1.0, mark weak unless exceptional factors.",
            "Cap pros/cons at 3 each, concise.",
            "Scores 0–100: 60+ investable, 80+ strong.",
        ],
    }

    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)},
        ],
    )

    return json.loads(resp.choices[0].message.content)


def run_portfolio_rank(items_raw: List[Dict[str, Any]]) -> Dict[str, Any]:
    compact = [_compact_item(x, i) for i, x in enumerate(items_raw)]
    cache_key = make_cache_key({"items": compact}, version="ranker-v2")
    cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    if cached:
        return cached

    try:
        ranked = _rank_with_ai(compact)
        order = [
            i
            for i in ranked.get("order", [])
            if isinstance(i, int) and 0 <= i < len(compact)
        ]
        if not order:
            order = list(range(len(compact)))
            order.sort(
                key=lambda i: (
                    float(compact[i].get("cash_on_cash") or 0.0),
                    float(compact[i].get("cash_flow_monthly") or 0.0),
                ),
                reverse=True,
            )
        out = {
            "ok": True,
            "order": order,
            "ranked": ranked.get("ranked", []),
            "summary": ranked.get("summary", ""),
            "items": compact,
        }
        blob_cache_put(CACHE_GROUP, cache_key, out)
        return out
    except Exception as e:
        logging.exception("portfolio-rank error")
        order = list(range(len(compact)))
        order.sort(
            key=lambda i: (
                float(compact[i].get("cash_on_cash") or 0.0),
                float(compact[i].get("cash_flow_monthly") or 0.0),
            ),
            reverse=True,
        )
        out = {
            "ok": False,
            "error": str(e),
            "order": order,
            "ranked": [],
            "summary": "",
            "items": compact,
        }
        blob_cache_put(CACHE_GROUP, cache_key, out)
        return out