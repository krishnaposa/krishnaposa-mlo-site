"""
Morning PCS execution email — opportunities + open-position lifecycle only.

Scheduled ~10:00 ET. Uses live option chains and current marks so you can trade
the same session.

Env:
  SEND_EMAIL=1, EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO
  PCS_OPPORTUNITIES_ENABLED   default 1
  PCS_LIFECYCLE_ENABLED       default 1
  PCS_MORNING_SUBJECT_PREFIX  default "PCS — today"
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def run_pcs_morning(*, stamp: Optional[str] = None) -> Dict[str, Any]:
    """Run PCS scan + lifecycle review and send the execution email."""
    stamp = stamp or datetime.date.today().strftime("%Y-%m-%d")
    os.environ.setdefault("PCS_SESSION_LABEL", "today's session")

    out: Dict[str, Any] = {
        "stamp": stamp,
        "opportunities": None,
        "lifecycle": None,
        "email_sent": False,
        "email_error": None,
    }

    pcs_opportunities_result: Dict[str, Any] | None = None
    pcs_opportunities_html = ""
    pcs_opportunity_tickers: list[str] = []

    if os.getenv("PCS_OPPORTUNITIES_ENABLED", "1") == "1":
        try:
            from .pcs_opportunities import run_pcs_opportunities

            pcs_opportunities_result = run_pcs_opportunities()
            pcs_opportunities_html = pcs_opportunities_result.get("html") or ""
            pcs_opportunity_tickers = list(pcs_opportunities_result.get("tickers") or [])
        except Exception as e:
            logger.exception("[pcs_morning] opportunities failed")
            pcs_opportunities_result = {
                "rows": [],
                "rows_b": [],
                "rows_c": [],
                "error": str(e),
            }
            pcs_opportunities_html = f"<p><i>PCS opportunities error: {e}</i></p>"

    out["opportunities"] = pcs_opportunities_result

    pcs_lifecycle_result: Dict[str, Any] | None = None
    pcs_lifecycle_html = ""
    pcs_actionable: list[str] = []

    if os.getenv("PCS_LIFECYCLE_ENABLED", "1") == "1":
        try:
            from .pcs_lifecycle import run_pcs_lifecycle

            pcs_lifecycle_result = run_pcs_lifecycle()
            pcs_lifecycle_html = pcs_lifecycle_result.get("html") or ""
            pcs_actionable = list(pcs_lifecycle_result.get("actionable") or [])
        except Exception as e:
            logger.exception("[pcs_morning] lifecycle failed")
            pcs_lifecycle_result = {"swing_rows": [], "pcs_rows": [], "error": str(e)}
            pcs_lifecycle_html = f"<p><i>PCS lifecycle error: {e}</i></p>"

    out["lifecycle"] = pcs_lifecycle_result

    try:
        from .emailer import send_pcs_execution_email

        send_pcs_execution_email(
            stamp=stamp,
            pcs_opportunities_section_html=pcs_opportunities_html,
            pcs_opportunity_tickers=pcs_opportunity_tickers,
            pcs_lifecycle_section_html=pcs_lifecycle_html,
            pcs_actionable_tickers=pcs_actionable,
            pcs_opportunities_result=pcs_opportunities_result,
            pcs_lifecycle_result=pcs_lifecycle_result,
            subj_prefix=os.getenv("PCS_MORNING_SUBJECT_PREFIX", "PCS — today"),
        )

        out["email_sent"] = os.getenv("SEND_EMAIL", "0") == "1"

    except Exception as e:
        logger.exception("[pcs_morning] email failed")
        out["email_sent"] = False
        out["email_error"] = str(e)

    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import pprint

    pprint.pprint(run_pcs_morning())