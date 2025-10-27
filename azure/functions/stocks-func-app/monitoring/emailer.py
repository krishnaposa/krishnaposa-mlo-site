# monitoring/emailer.py

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
    if not rows:
        return "<i>No simulation metrics</i>"

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
        html.append(
            f"<tr><td>{r.get('ticker','')}</td>"
            f"<td align='right'>{_fmt_pct(r.get('mc30'))}</td>"
            f"<td align='right'>{_fmt_pct(r.get('hmm_bull'))}</td>"
            f"<td align='right'>{_fmt_pct(r.get('ml_prob'))}</td></tr>"
        )
    html.append("</tbody></table>")
    return "".join(html)


def _perf_table_html(rows: Optional[List[Dict]], max_rows: int = 50) -> str:
    """
    rows: [{"ticker": "AAPL", "perf_5d": 2.4, "perf_1m": 5.6, "perf_6m": 28.7}, ...]
    """
    if not rows:
        return "<i>No performance data</i>"

    def _fmt(x):
        try:
            return f"{float(x):.1f}%"
        except Exception:
            return "—"

    head = rows[:max_rows]
    html = [
        "<table border='0' cellspacing='0' cellpadding='4'>",
        "<thead><tr>",
        "<th align='left'>Ticker</th>",
        "<th align='right'>5-Day</th>",
        "<th align='right'>1-Month</th>",
        "<th align='right'>6-Month</th>",
        "</tr></thead><tbody>"
    ]
    for r in head:
        html.append(
            f"<tr><td>{r.get('ticker','')}</td>"
            f"<td align='right'>{_fmt(r.get('perf_5d'))}</td>"
            f"<td align='right'>{_fmt(r.get('perf_1m'))}</td>"
            f"<td align='right'>{_fmt(r.get('perf_6m'))}</td></tr>"
        )
    html.append("</tbody></table>")
    return "".join(html)


def _opt_table_html(rows: Optional[List[Dict]], max_rows: int = 40) -> str:
    """
    rows: [{"ticker","expiry","dte","k1","k2","debit","oi1","oi2","combo_spread"}]
    """
    if not rows:
        return "<i>No options data</i>"

    def _fmt_money(x):
        try:
            return f"${float(x):.2f}"
        except Exception:
            return "—"

    def _fmt_pct(x):
        try:
            return f"{float(x)*100:.0f}%"
        except Exception:
            return "—"

    head = rows[:max_rows]
    html = [
        "<table border='0' cellspacing='0' cellpadding='4'>",
        "<thead><tr>",
        "<th align='left'>Ticker</th>",
        "<th align='left'>Expiry</th>",
        "<th align='right'>DTE</th>",
        "<th align='right'>Long&nbsp;K</th>",
        "<th align='right'>Short&nbsp;K</th>",
        "<th align='right'>Mid&nbsp;Debit</th>",
        "<th align='right'>OI&nbsp;Long</th>",
        "<th align='right'>OI&nbsp;Short</th>",
        "<th align='right'>Combo Spread%</th>",
        "</tr></thead><tbody>",
    ]
    for r in head:
        html.append(
            f"<tr><td>{r.get('ticker','')}</td>"
            f"<td>{r.get('expiry','')}</td>"
            f"<td align='right'>{r.get('dte','')}</td>"
            f"<td align='right'>{r.get('k1','')}</td>"
            f"<td align='right'>{r.get('k2','')}</td>"
            f"<td align='right'>{_fmt_money(r.get('debit'))}</td>"
            f"<td align='right'>{r.get('oi1','')}</td>"
            f"<td align='right'>{r.get('oi2','')}</td>"
            f"<td align='right'>{_fmt_pct(r.get('combo_spread'))}</td></tr>"
        )
    html.append("</tbody></table>")
    return "".join(html)


def send_email_report_with_sims(*,
    stamp: str,
    picks_tickers: List[str],
    ai_spreads_list: List[str],
    ai_leaps_list: List[str],
    sim_rows: Optional[List[Dict]] = None,    # ticker, mc30, hmm_bull, ml_prob
    opt_rows: Optional[List[Dict]] = None,    # ticker, expiry, dte, k1, k2, debit, oi1, oi2, combo_spread
    perf_rows: Optional[List[Dict]] = None,   # ticker, perf_5d, perf_1m, perf_6m
    subj_prefix: str = "Daily Stock Picks"
):
    if os.getenv("SEND_EMAIL", "0") != "1":
        return

    email_from = os.getenv("EMAIL_FROM")
    pwd        = os.getenv("EMAIL_PASSWORD")
    tos = [t.strip() for t in os.getenv("EMAIL_TO", "").split(",") if t.strip()]
    if not (email_from and pwd and tos):
        return

    s_spreads = ", ".join(ai_spreads_list[:2])
    s_leaps   = ", ".join(ai_leaps_list[:2])
    subj_tail = f"Spreads: {s_spreads}" + (f" | LEAPS: {s_leaps}" if s_leaps else "")
    subject = f"{subj_prefix} — {stamp} | {subj_tail}".strip().rstrip(" |")

    html_picks   = _list_html(picks_tickers)
    html_spreads = _list_html(ai_spreads_list)
    html_leaps   = _list_html(ai_leaps_list)
    html_sims    = _sim_table_html(sim_rows)
    html_perf    = _perf_table_html(perf_rows)
    html_opts    = _opt_table_html(opt_rows)

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

      <h3>Performance (Price Change)</h3>
      {html_perf}

      <h3>Options (30–45 DTE) Setup</h3>
      {html_opts}

      {eat_note}
    </body></html>"""

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