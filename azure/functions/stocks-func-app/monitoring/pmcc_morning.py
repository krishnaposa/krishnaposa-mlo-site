"""
Morning PMCC email — screening ideas + open-position lifecycle.

Env:
  SEND_EMAIL=1, EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO
  PMCC_OPPORTUNITIES_ENABLED=1
  PMCC_LIFECYCLE_ENABLED=1
  PMCC_MORNING_SUBJECT_PREFIX=PMCC — today
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def run_pmcc_morning(*, stamp: Optional[str] = None) -> Dict[str, Any]:
    stamp = stamp or datetime.date.today().strftime("%Y-%m-%d")

    out: Dict[str, Any] = {
        "stamp": stamp,
        "opportunities": None,
        "lifecycle": None,
        "email_sent": False,
        "email_error": None,
    }

    opp_result: Dict[str, Any] | None = None
    opp_html = ""
    opp_tickers: list[str] = []

    if os.getenv("PMCC_OPPORTUNITIES_ENABLED", "1") == "1":
        try:
            from .pmcc_opportunities import run_pmcc_opportunities

            opp_result = run_pmcc_opportunities()
            opp_html = opp_result.get("html") or ""
            opp_tickers = list(opp_result.get("tickers") or [])
        except Exception as e:
            logger.exception("[pmcc_morning] opportunities failed")
            opp_result = {"rows": [], "error": str(e)}
            opp_html = f"<p><i>PMCC opportunities error: {e}</i></p>"

    out["opportunities"] = opp_result

    life_result: Dict[str, Any] | None = None
    life_html = ""
    actionable: list[str] = []

    if os.getenv("PMCC_LIFECYCLE_ENABLED", "1") == "1":
        try:
            from .pmcc_lifecycle import run_pmcc_lifecycle

            opp_rows = list(opp_result.get("rows") or []) if opp_result else []
            life_result = run_pmcc_lifecycle(opportunities=opp_rows)
            life_html = life_result.get("html") or ""
            actionable = list(life_result.get("actionable") or [])
        except Exception as e:
            logger.exception("[pmcc_morning] lifecycle failed")
            life_result = {"rows": [], "error": str(e)}
            life_html = f"<p><i>PMCC lifecycle error: {e}</i></p>"

    out["lifecycle"] = life_result

    try:
        from .emailer import send_pmcc_execution_email

        send_pmcc_execution_email(
            stamp=stamp,
            pmcc_opportunities_section_html=opp_html,
            pmcc_opportunity_tickers=opp_tickers,
            pmcc_lifecycle_section_html=life_html,
            pmcc_actionable_tickers=actionable,
            pmcc_opportunities_result=opp_result,
            pmcc_lifecycle_result=life_result,
            subj_prefix=os.getenv("PMCC_MORNING_SUBJECT_PREFIX", "PMCC — today"),
        )
        out["email_sent"] = os.getenv("SEND_EMAIL", "0") == "1"
    except Exception as e:
        logger.exception("[pmcc_morning] email failed")
        out["email_sent"] = False
        out["email_error"] = str(e)

    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import pprint

    pprint.pprint(run_pmcc_morning())
