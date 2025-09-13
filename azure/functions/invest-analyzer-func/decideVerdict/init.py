# decideVerdict/__init__.py
from typing import Dict, Any

def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default

def main(payload: dict):
    m = payload["metrics"]
    cap = m["cap_rate"] * 100
    coc = (m["coc"] or 0) * 100
    irr = (m["irr"] or 0) * 100

    verdict = "fail"  # renamed from pass → fail
    if ((cap >= 6 and coc >= 10) or irr >= 13):
        verdict = "buy"
    elif (6 <= coc < 10) or (8 <= irr < 13):
        verdict = "borderline"

    reasons = f"Cap {cap:.1f}%, CoC {coc:.1f}%, IRR {irr:.1f}%."
    return {"verdict": verdict, "reasons": reasons, "metrics": m}