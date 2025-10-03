# ai_utils.py
import os, json, logging
from typing import List, Dict, Any
import pandas as pd

try:
    from openai import AzureOpenAI
except Exception:
    AzureOpenAI = None  # type: ignore

logger = logging.getLogger(__name__)

# ---- Env ----
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

def _require_creds():
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        raise RuntimeError("Azure OpenAI settings missing (endpoint/key/deployment).")

def _make_prompt(tickers: List[str], strategy: str, horizon_text: str | None = None):
    system = (
        "You are an equity analyst. Return ONLY JSON.\n"
        "Rank the provided tickers for the chosen strategy with concise reasoning.\n"
        "Scores should be on a 0–10 scale (higher is better)."
    )

    strat = {
        "leaps": "Suitability for long-dated call options (LEAPS): durable uptrend, 6–18m catalysts, IV/liquidity, risk.",
        "debit_call_spread": (
            "30–40 day debit call spread: directional edge with controlled risk. "
            "Favor clear uptrends, catalysts within ~1 month, liquid options (tight spreads/high OI), "
            "reasonable IV (not extremely elevated pre-event), identifiable resistance for target strikes."
        ),
        "short_term_options": "1–8 week options setups: near-term catalysts, IV crush risk, liquidity, technicals."
    }
    instruction = strat.get(strategy, f"Evaluate '{strategy}' with clear, investable reasoning.")
    if horizon_text:
        instruction = f"{instruction} Horizon: {horizon_text}."

    schema_props = {
        "strategy": {"type": "string"},
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "score": {"type": "number"},
                    "thesis": {"type": "string"},
                    "risks": {"type": "string"},
                    "suggested_action": {"type": "string"}
                },
                "required": ["ticker", "score", "thesis"]
            }
        },
        "notes": {"type": "string"}
    }
    req = ["strategy", "ranked"]
    if horizon_text:
        schema_props["horizon"] = {"type": "string"}
        req.append("horizon")

    user = {
        "strategy": strategy,
        "tickers": tickers,
        "instructions": instruction,
        "output_format": {"type": "object", "properties": schema_props, "required": req},
        "scoring_guidance": {
            "scale": "0-10",
            "rough_buckets": {"excellent": "8-10", "good": "6-7.9", "ok": "4-5.9", "weak": "<4"}
        },
        "format_expectations": "Return valid JSON that matches the schema. Keep theses/risks concise (1-3 lines)."
    }
    if horizon_text:
        user["horizon"] = horizon_text
    return system, user

def score_with_azure_openai(tickers: List[str], strategy: str, horizon_text: str | None = None) -> Dict[str, Any]:
    _require_creds()
    if AzureOpenAI is None:
        raise RuntimeError("openai SDK not available in this environment")

    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    system, user = _make_prompt(tickers, strategy, horizon_text)
    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": json.dumps(user)}],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)

def ai_rank_tickers(tickers: List[str], strategy: str, horizon_text: str | None = None, top_k: int = 10) -> pd.DataFrame:
    """Return DataFrame: ticker, ai_score, thesis, risks, suggested_action (sorted, head top_k)."""
    tickers = [str(t).upper().strip() for t in (tickers or []) if str(t).strip()]
    if not tickers:
        return pd.DataFrame(columns=["ticker","ai_score","thesis","risks","suggested_action"])

    try:
        result = score_with_azure_openai(tickers, strategy=strategy, horizon_text=horizon_text)
        ranked = (result or {}).get("ranked", [])
        rows = [{
            "ticker": str(it.get("ticker","")).upper().strip(),
            "ai_score": float(it.get("score", 0.0)),
            "thesis": it.get("thesis",""),
            "risks": it.get("risks",""),
            "suggested_action": it.get("suggested_action","")
        } for it in ranked]
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("ai_score", ascending=False).head(top_k).reset_index(drop=True)
        return df
    except Exception as e:
        logger.warning(f"[ai_rank_tickers] AI ranking failed: {e}")
        return pd.DataFrame(columns=["ticker","ai_score","thesis","risks","suggested_action"])