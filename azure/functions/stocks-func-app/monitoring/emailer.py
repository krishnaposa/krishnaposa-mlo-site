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


def _wheel_table_html(rows: Optional[List[Dict]], max_rows: int = 20) -> str:
    if not rows:
        return "<i>No wheel candidates</i>"

    def _fmt_money(x):
        try:
            return f"${float(x):.2f}"
        except Exception:
            return "—"

    def _fmt_pct(x):
        try:
            return f"{float(x)*100:.1f}%"
        except Exception:
            return "—"

    def _fmt_num(x):
        try:
            return f"{float(x):.1f}"
        except Exception:
            return "—"

    head = rows[:max_rows]
    html = [
        "<table border='0' cellspacing='0' cellpadding='4'>",
        "<thead><tr>",
        "<th align='left'>Ticker</th>",
        "<th align='left'>Expiry</th>",
        "<th align='right'>DTE</th>",
        "<th align='right'>Spot</th>",
        "<th align='right'>Put K</th>",
        "<th align='right'>Credit</th>",
        "<th align='right'>ROC</th>",
        "<th align='right'>Ann.</th>",
        "<th align='right'>B/E</th>",
        "<th align='right'>Buffer</th>",
        "<th align='right'>OI</th>",
        "<th align='right'>Spread</th>",
        "<th align='right'>Score</th>",
        "</tr></thead><tbody>",
    ]
    for r in head:
        html.append(
            f"<tr><td>{r.get('ticker','')}</td>"
            f"<td>{r.get('expiry','')}</td>"
            f"<td align='right'>{r.get('dte','')}</td>"
            f"<td align='right'>{_fmt_money(r.get('spot'))}</td>"
            f"<td align='right'>{_fmt_money(r.get('strike'))}</td>"
            f"<td align='right'>{_fmt_money(r.get('credit'))}</td>"
            f"<td align='right'>{_fmt_pct(r.get('roc'))}</td>"
            f"<td align='right'>{_fmt_pct(r.get('ann_return'))}</td>"
            f"<td align='right'>{_fmt_money(r.get('breakeven'))}</td>"
            f"<td align='right'>{_fmt_pct(r.get('buffer'))}</td>"
            f"<td align='right'>{_fmt_num(r.get('oi'))}</td>"
            f"<td align='right'>{_fmt_pct(r.get('spread'))}</td>"
            f"<td align='right'>{_fmt_num(r.get('score'))}</td></tr>"
        )
    html.append("</tbody></table>")
    return "".join(html)


def _trend_table_html(rows: Optional[List[Dict]], max_rows: int = 30) -> str:
    if not rows:
        return "<i>No trend rows</i>"

    def _fmt_money(x):
        try:
            return f"${float(x):.2f}"
        except Exception:
            return "—"

    def _fmt_pct(x):
        try:
            return f"{float(x)*100:.1f}%"
        except Exception:
            return "—"

    def _fmt_num(x):
        try:
            return f"{float(x):.1f}"
        except Exception:
            return "—"

    head = rows[:max_rows]
    html = [
        "<table border='0' cellspacing='0' cellpadding='4'>",
        "<thead><tr>",
        "<th align='left'>Ticker</th>",
        "<th align='left'>Entry</th>",
        "<th align='right'>Price</th>",
        "<th align='right'>RSI</th>",
        "<th align='right'>ADX</th>",
        "<th align='right'>RelVol</th>",
        "<th align='right'>52W Dist</th>",
        "<th align='right'>ATR Stop</th>",
        "<th align='right'>3-Bar Low</th>",
        "<th align='left'>Exit Watch</th>",
        "</tr></thead><tbody>",
    ]
    for r in head:
        html.append(
            f"<tr><td>{r.get('ticker','')}</td>"
            f"<td>{r.get('entry_status','')}</td>"
            f"<td align='right'>{_fmt_money(r.get('price'))}</td>"
            f"<td align='right'>{_fmt_num(r.get('rsi'))}</td>"
            f"<td align='right'>{_fmt_num(r.get('adx'))}</td>"
            f"<td align='right'>{_fmt_num(r.get('rel_volume'))}</td>"
            f"<td align='right'>{_fmt_pct(r.get('dist_52w_high'))}</td>"
            f"<td align='right'>{_fmt_money(r.get('atr_stop'))}</td>"
            f"<td align='right'>{_fmt_money(r.get('three_bar_low'))}</td>"
            f"<td>{r.get('exit_watch','')}</td></tr>"
        )
    html.append("</tbody></table>")
    return "".join(html)


def _tickers_from_rows(rows: Optional[List[Dict]], *, entry_only: bool = False) -> List[str]:
    if not rows:
        return []
    out: List[str] = []
    for r in rows:
        if entry_only and r.get("entry_status") != "Entry OK":
            continue
        ticker = str(r.get("ticker", "")).upper().strip()
        if ticker:
            out.append(ticker)
    return list(dict.fromkeys(out))


def send_email_report_with_sims(*,
    stamp: str,
    universe_tickers: List[str],
    picks_tickers: List[str],
    ai_spreads_list: List[str],
    ai_leaps_list: List[str],
    alltime_high_value_list: Optional[List[str]] = None,
    alltime_high_trend_rows: Optional[List[Dict]] = None,
    trend_entry_list: Optional[List[str]] = None,
    trend_entry_rows: Optional[List[Dict]] = None,
    holdings_exit_rows: Optional[List[Dict]] = None,
    sim_rows: Optional[List[Dict]] = None,    # ticker, mc30, hmm_bull, ml_prob
    opt_rows: Optional[List[Dict]] = None,    # ticker, expiry, dte, k1, k2, debit, oi1, oi2, combo_spread
    wheel_rows: Optional[List[Dict]] = None,  # cash-secured put wheel candidates
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

    # Disabled for now: LEAPS/debit-spread AI lists are not included in the subject.
    # s_spreads = ", ".join(ai_spreads_list[:2])
    # s_leaps = ", ".join(ai_leaps_list[:2])
    # subj_tail = f"Spreads: {s_spreads}" + (f" | LEAPS: {s_leaps}" if s_leaps else "")
    subject = f"{subj_prefix} — {stamp}".strip()

    strong_buy_entries = _tickers_from_rows(alltime_high_trend_rows, entry_only=True)
    trend_entries = _tickers_from_rows(trend_entry_rows, entry_only=True)
    holdings_exits = _tickers_from_rows(holdings_exit_rows)
    wheel_tickers = _tickers_from_rows(wheel_rows)

    html_universe = _list_html(universe_tickers)
    html_picks = _list_html(picks_tickers)
    html_alltime_high_value = _list_html(alltime_high_value_list or [])
    html_strong_buy_entries = _list_html(strong_buy_entries)
    html_trend_entries = _list_html(trend_entries)
    html_holdings_exits = _list_html(holdings_exits)
    html_wheel_tickers = _list_html(wheel_tickers)
    # Disabled for now: LEAPS/debit-spread AI sections are not rendered.
    # html_spreads = _list_html(ai_spreads_list)
    # html_leaps = _list_html(ai_leaps_list)

    eat_note = (
        "<div style='font-size:12px;color:#666;margin-top:8px'>"
        "<b>EAT</b> = Earnings Avoid Threshold (we typically avoid opening new trades if earnings "
        "are within ~2 weeks unless explicitly planned)."
        "</div>"
    )

    html_body = f"""<html><body>
      <h2>Daily Stock Picks — {stamp}</h2>

      <h3>Universe Stocks</h3>
      <div>{html_universe}</div>

      <h3>Stock Picks</h3>
      <div>{html_picks}</div>

      <h3>Finviz: Strong Buy Large Caps at All-Time High</h3>
      <div>{html_alltime_high_value}</div>

      <h3>Strong Buy Large Cap Stock List</h3>
      <div><i>Passed trend entry criteria</i></div>
      <div>{html_strong_buy_entries}</div>

      <h3>Trend Entry Stock List</h3>
      <div><i>Passed trend entry criteria</i></div>
      <div>{html_trend_entries}</div>

      <h3>Holdings Exit List</h3>
      <div>{html_holdings_exits}</div>

      <h3>Wheel Stocks</h3>
      <div>{html_wheel_tickers}</div>

      <!-- Disabled for now: LEAPS/debit-spread AI sections. -->
      <!--
      <h3>AI: 30–40 Day Debit Call Spreads</h3>
      <div>{{html_spreads}}</div>

      <h3>AI: LEAPS (12–24 months)</h3>
      <div>{{html_leaps}}</div>
      -->

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