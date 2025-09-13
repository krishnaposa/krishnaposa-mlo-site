# decideVerdict/__init__.py
from typing import Dict, Any

def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default

def main(payload: Dict[str, Any]):
    # payload is expected to contain {"metrics": {...}}
    m = (payload or {}).get("metrics", {}) or {}

    cap = _f(m.get("cap_rate"))   # e.g., 0.065
    coc = _f(m.get("coc"))        # e.g., 0.11
    irr = _f(m.get("irr"))        # e.g., 0.13

    # Decide using fractions
    verdict = "pass"
    if (cap >= 0.06 and coc >= 0.10) or irr >= 0.13:
        verdict = "buy"
    elif (0.06 <= coc < 0.10) or (0.08 <= irr < 0.13):
        verdict = "borderline"

    # Human-readable reasons
    reasons = f"Cap {cap*100:.1f}%, CoC {coc*100:.1f}%, IRR {irr*100:.1f}%."

    return {
        "verdict": verdict,
        "reasons": reasons,
        "metrics": {"cap_rate": cap, "coc": coc, "irr": irr}
    }