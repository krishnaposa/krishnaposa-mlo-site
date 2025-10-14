import os
import ssl
from email.message import EmailMessage
from typing import List, Dict, Optional

def _list_html(items: List[str], max_items: int = 100) -> str:
    if not items:
        return "<i>None</i>"
    items = items[:max_items]
    return ", ".join(map(str, items))

def _sim_table_html(rows: Optional[List[Dict]], max_rows: int = 60) -> str:
    """
    rows: [{"ticker": "AAPL", "mc30": 0.67, "hmm_bull": 0.58, "ml_prob": 0.62}, ...]
    All values are rendered as percentages where applicable.
    """
    if not rows:
        return "<i>No simulation metrics</i>"

    # clip & format
    def _fmt_pct(x):
        try:
            return f"{float(x)*100:0.0f}%"
        except Exception:
            return "—"

    head = rows[:max_rows]
    html = [
        "<table border='0' cellspacing='0' cellpadding='4'>",
        "<thead><tr>",
        "<th align='left'>Ticker</th>",
        "<th align='right'>Monte Carlo (P↑)</th>",
        "<th align='right'>HMM (Bull Prob)</th>",
        "<th align='right'>ML (P↑)</th>",
        "</tr></thead><tbody>"
    ]
    for r in head:
        tkr = str(r.get("ticker", ""))
        mc  = _fmt_pct(r.get("mc30"))
        hmm = _fmt_pct(r.get("hmm_bull"))
        ml  = _fmt_pct(r.get("ml_prob"))
        html.append(
            f"<tr><td>{tkr}</td>"
            f"<td align='right'>{mc}</td>"
            f"<td align='right'>{hmm}</td>"
            f"<td align='right'>{ml}</td></tr>"
        )
    html.append("</tbody></table>")
    return "".join(html)

def send_email_report_with_sims(*,
    stamp: str,
    picks_tickers: List[str],
    ai_spreads_list: List[str],
    ai_leaps_list: List[str],
    sim_rows: Optional[List[Dict]] = None,   # expects keys: ticker, mc30, hmm_bull, ml_prob
    subj_prefix: str = "Daily Stock Picks"
):
    """
    Minimal, list-first email with a compact simulator table.

    Subject: "... | Spreads: A, B | LEAPS: C, D"
    Body:
      - Picks (buy_flag + leaders slice)
      - AI lists (spreads, leaps)
      - Simulator table: Monte Carlo (P↑), HMM (Bull Prob), ML (P↑)
      - Tiny EAT reminder line
    """
    if os.getenv("SEND_EMAIL", "0") != "1":
        return

    email_from = os.getenv("EMAIL_FROM")
    pwd        = os.getenv("EMAIL_PASSWORD")
    tos = [t.strip() for t in os.getenv("EMAIL_TO", "").split(",") if t.strip()]
    if not (email_from and pwd and tos):
        return

    # Subject tail from top 2 AI names
    s_spreads = ", ".join(ai_spreads_list[:2])
    s_leaps   = ", ".join(ai_leaps_list[:2])
    subj_tail = f"Spreads: {s_spreads}" + (f" | LEAPS: {s_leaps}" if s_leaps else "")
    subject = f"{subj_prefix} — {stamp} | {subj_tail}".strip().rstrip(" |")

    # Sections
    html_picks   = _list_html(picks_tickers)
    html_spreads = _list_html(ai_spreads_list)
    html_leaps   = _list_html(ai_leaps_list)
    html_sims    = _sim_table_html(sim_rows)

    # Small reminder line about EAT
    eat_note = (
        "<div style='font-size:12px;color:#666;margin-top:8px'>"
        "<b>EAT</b> = Earnings Avoid Threshold (we typically avoid opening new trades if earnings "
        "are within ~2 weeks unless explicitly planned)."
        "</div>"
    )

    html_body = f"""<html><body>
      <h2>Daily Stock Picks — {stamp}</h2>

      <h3>Stock Picks (buy_flag + top leaders)</h3>
      <div>{html_picks}</div>

      <h3>AI: 30–40 Day Debit Call Spreads</h3>
      <div>{html_spreads}</div>

      <h3>AI: LEAPS (12–24 months)</h3>
      <div>{html_leaps}</div>

      <h3>Simulators</h3>
      {html_sims}
      {eat_note}
    </body></html>"""

    # Send
    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = ", ".join(tos)
    msg["Subject"] = subject
    msg.set_content("See HTML version")
    msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    import smtplib
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(email_from, pwd)
        s.send_message(msg)