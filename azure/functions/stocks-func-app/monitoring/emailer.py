# monitoring/emailer.py

import logging
import os
import ssl
from email.message import EmailMessage
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


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


def _list_text(items: List[str], max_items: int = 100) -> str:
    if not items:
        return "  (none)"
    return "  " + ", ".join(map(str, items[:max_items]))


def _pct_text(x) -> str:
    try:
        return f"{float(x) * 100:.0f}%"
    except Exception:
        return "—"


def _sim_table_text(rows: Optional[List[Dict]], max_rows: int = 60) -> str:
    if not rows:
        return "  (none)"
    lines = [f"  {'Ticker':<8} {'MC P(up)':>10} {'HMM Bull':>10} {'ML P(up)':>10}"]
    for r in rows[:max_rows]:
        lines.append(
            f"  {str(r.get('ticker', '')):<8} {_pct_text(r.get('mc30')):>10} "
            f"{_pct_text(r.get('hmm_bull')):>10} {_pct_text(r.get('ml_prob')):>10}"
        )
    return "\n".join(lines)


def _perf_table_text(rows: Optional[List[Dict]], max_rows: int = 50) -> str:
    if not rows:
        return "  (none)"

    def _fmt(x):
        try:
            return f"{float(x):.1f}%"
        except Exception:
            return "—"

    lines = [f"  {'Ticker':<8} {'5-Day':>10} {'1-Month':>10} {'6-Month':>10}"]
    for r in rows[:max_rows]:
        lines.append(
            f"  {str(r.get('ticker', '')):<8} {_fmt(r.get('perf_5d')):>10} "
            f"{_fmt(r.get('perf_1m')):>10} {_fmt(r.get('perf_6m')):>10}"
        )
    return "\n".join(lines)


def format_monitor_report_text(
    *,
    stamp: str,
    universe_tickers: List[str],
    picks_tickers: List[str],
    alltime_high_value_list: Optional[List[str]] = None,
    alltime_high_trend_rows: Optional[List[Dict]] = None,
    trend_entry_rows: Optional[List[Dict]] = None,
    sim_rows: Optional[List[Dict]] = None,
    wheel_rows: Optional[List[Dict]] = None,
    perf_rows: Optional[List[Dict]] = None,
    momentum_result: Optional[Dict] = None,
    momentum_sim_rows: Optional[List[Dict]] = None,
    momentum_perf_rows: Optional[List[Dict]] = None,
    momentum_exited_tickers: Optional[List[str]] = None,
    pcs_opportunities_result: Optional[Dict] = None,
    pcs_lifecycle_result: Optional[Dict] = None,
    subj_prefix: str = "Daily Stock Picks",
) -> str:
    """Plain-text report matching the daily email sections."""
    from .momentum_portfolio import format_momentum_text
    from .pcs_lifecycle import format_pcs_lifecycle_text
    from .pcs_opportunities import format_pcs_opportunities_result_text

    strong_buy_entries = _tickers_from_rows(alltime_high_trend_rows, entry_only=True)
    trend_entries = _tickers_from_rows(trend_entry_rows, entry_only=True)
    wheel_tickers = _tickers_from_rows(wheel_rows)

    lines: List[str] = [
        "",
        "=" * 72,
        f"{subj_prefix} — {stamp}",
        "=" * 72,
    ]
    alerts: List[str] = []
    if alerts:
        lines.append("ALERTS: " + " · ".join(alerts))
        lines.append("")

    sections = [
        ("Universe Stocks", _list_text(universe_tickers)),
        ("Stock Picks (buy_flag + top leaders)", _list_text(picks_tickers)),
        (
            "Finviz: Strong Buy Large Caps at All-Time High",
            _list_text(alltime_high_value_list or []),
        ),
        (
            "Strong Buy Large Cap Stock List (trend entry OK)",
            _list_text(strong_buy_entries),
        ),
        ("Trend Entry Stock List (trend entry OK)", _list_text(trend_entries)),
    ]
    for title, body in sections:
        lines.extend([f"\n## {title}", body])

    if pcs_opportunities_result is not None:
        lines.extend([
            "\n## PCS ideas for next session (pie_analyze_swing)",
            format_pcs_opportunities_result_text(pcs_opportunities_result),
        ])

    if pcs_lifecycle_result is not None:
        lines.extend([
            "\n## Open positions — lifecycle (positions.json)",
            format_pcs_lifecycle_text(
                pcs_lifecycle_result.get("swing_rows") or [],
                pcs_lifecycle_result.get("pcs_rows") or [],
            ),
        ])

    lines.append("\n## Momentum portfolio")
    if momentum_result is not None:
        mom_txt = format_momentum_text(momentum_result)
        lines.append(mom_txt if mom_txt.strip() else "  (empty)")
    else:
        lines.append("  Momentum portfolio not run (disabled or error).")

    lines.append("\n## Momentum — Simulators (new high today)")
    if momentum_sim_rows is None:
        lines.append("  (momentum not run)")
    elif not momentum_sim_rows:
        lines.append("  (no new highs today)")
    else:
        lines.append(_sim_table_text(momentum_sim_rows))

    lines.append("\n## Momentum — Performance (new high today)")
    if momentum_perf_rows is None:
        lines.append("  (momentum not run)")
    elif not momentum_perf_rows:
        lines.append("  (no new highs today)")
    else:
        lines.append(_perf_table_text(momentum_perf_rows))

    lines.extend(
        [
            "\n## Wheel Stocks",
            _list_text(wheel_tickers),
            "\n## Simulators (picks)",
            _sim_table_text(sim_rows),
            "\n## Performance — Price change (picks)",
            _perf_table_text(perf_rows),
            "",
            "EAT = Earnings Avoid Threshold (~2 weeks before earnings for new trades).",
            "=" * 72,
            "",
        ]
    )
    return "\n".join(lines)


def print_monitor_report_text(**kwargs) -> None:
    print(format_monitor_report_text(**kwargs), flush=True)


def format_pcs_execution_report_text(
    *,
    stamp: str,
    pcs_opportunities_result: Optional[Dict] = None,
    pcs_lifecycle_result: Optional[Dict] = None,
    subj_prefix: str = "PCS — today",
) -> str:
    """Plain-text PCS execution report (morning email)."""
    from .pcs_lifecycle import format_pcs_lifecycle_text
    from .pcs_opportunities import format_pcs_opportunities_result_text

    lines: List[str] = [
        "",
        "=" * 72,
        f"{subj_prefix} — {stamp}",
        "=" * 72,
        "",
        "Live option quotes — verify chain before placing orders.",
    ]

    if pcs_opportunities_result is not None:
        lines.extend([
            "\n## PCS ideas — today's session",
            format_pcs_opportunities_result_text(pcs_opportunities_result),
        ])

    if pcs_lifecycle_result is not None:
        lines.extend([
            "\n## Open positions — lifecycle (positions.json)",
            format_pcs_lifecycle_text(
                pcs_lifecycle_result.get("swing_rows") or [],
                pcs_lifecycle_result.get("pcs_rows") or [],
            ),
        ])

    lines.extend(["", "=" * 72, ""])
    return "\n".join(lines)


def send_pcs_execution_email(
    *,
    stamp: str,
    pcs_opportunities_section_html: Optional[str] = None,
    pcs_opportunity_tickers: Optional[List[str]] = None,
    pcs_lifecycle_section_html: Optional[str] = None,
    pcs_actionable_tickers: Optional[List[str]] = None,
    pcs_opportunities_result: Optional[Dict] = None,
    pcs_lifecycle_result: Optional[Dict] = None,
    subj_prefix: str = "PCS — today",
) -> None:
    """Morning PCS-only email: entry ideas + open-position plan."""
    if os.getenv("SEND_EMAIL", "0") != "1":
        logger.info("[pcs_email] SEND_EMAIL != 1 — not sending")
        return

    email_from = os.getenv("EMAIL_FROM")
    pwd = os.getenv("EMAIL_PASSWORD")
    tos = [t.strip() for t in os.getenv("EMAIL_TO", "").split(",") if t.strip()]
    if not (email_from and pwd and tos):
        logger.warning(
            "[pcs_email] missing EMAIL_FROM, EMAIL_PASSWORD, or EMAIL_TO — not sending"
        )
        return

    subject = f"{subj_prefix} — {stamp}".strip()
    alert_parts: List[str] = []
    po = pcs_opportunity_tickers or []
    if po:
        ox = ", ".join(str(t) for t in po[:8])
        if len(po) > 8:
            ox += " …"
        alert_parts.append(f"ideas: {ox}")
    pa = pcs_actionable_tickers or []
    if pa:
        px = ", ".join(str(t) for t in pa[:10])
        if len(pa) > 10:
            px += " …"
        alert_parts.append(f"actions: {px}")
    if alert_parts:
        subject = f"{subject} — " + " · ".join(alert_parts)

    opp_block = ""
    if pcs_opportunities_section_html is not None:
        opp_block = (
            "<h3>PCS ideas — today's session</h3>"
            f"<div>{pcs_opportunities_section_html}</div>"
        )

    lifecycle_block = ""
    if pcs_lifecycle_section_html is not None:
        lifecycle_block = (
            "<h3>Open positions — lifecycle review (positions.json)</h3>"
            f"<div>{pcs_lifecycle_section_html}</div>"
        )

    if not opp_block and not lifecycle_block:
        opp_block = (
            "<p><i>PCS morning run produced no sections "
            "(check PCS_OPPORTUNITIES_ENABLED / PCS_LIFECYCLE_ENABLED).</i></p>"
        )

    html_body = f"""<html><body>
      <h2>{subj_prefix} — {stamp}</h2>
      <p style="font-size:12px;color:#666">Morning execution sheet — live option quotes. Verify chain before placing orders.</p>
      {opp_block}
      {lifecycle_block}
    </body></html>"""

    plain = format_pcs_execution_report_text(
        stamp=stamp,
        pcs_opportunities_result=pcs_opportunities_result,
        pcs_lifecycle_result=pcs_lifecycle_result,
        subj_prefix=subj_prefix,
    )

    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = ", ".join(tos)
    msg["Subject"] = subject
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    import smtplib
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(email_from, pwd)
        s.send_message(msg)
    logger.info("[pcs_email] sent to %s subject=%s", ", ".join(tos), subject)


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
    pcs_opportunities_section_html: Optional[str] = None,  # pie funnel PCS ideas for next session
    pcs_opportunity_tickers: Optional[List[str]] = None,  # PCS idea tickers (subject line)
    pcs_lifecycle_section_html: Optional[str] = None,  # swing + PCS held-position lifecycle
    pcs_actionable_tickers: Optional[List[str]] = None,  # positions needing action (subject line)
    sim_rows: Optional[List[Dict]] = None,    # ticker, mc30, hmm_bull, ml_prob
    opt_rows: Optional[List[Dict]] = None,    # ticker, expiry, dte, k1, k2, debit, oi1, oi2, combo_spread
    wheel_rows: Optional[List[Dict]] = None,  # cash-secured put wheel candidates
    perf_rows: Optional[List[Dict]] = None,   # ticker, perf_5d, perf_1m, perf_6m
    momentum_section_html: Optional[str] = None,  # monitoring.momentum_portfolio HTML fragment
    momentum_sim_rows: Optional[List[Dict]] = None,  # MC/HMM/ML for new-high tickers only
    momentum_perf_rows: Optional[List[Dict]] = None,
    momentum_exited_tickers: Optional[List[str]] = None,  # set when momentum ran; None if feature off
    subj_prefix: str = "Daily Stock Picks"
):
    if os.getenv("SEND_EMAIL", "0") != "1":
        logger.info("[email] SEND_EMAIL != 1 — not sending")
        return

    email_from = os.getenv("EMAIL_FROM")
    pwd        = os.getenv("EMAIL_PASSWORD")
    tos = [t.strip() for t in os.getenv("EMAIL_TO", "").split(",") if t.strip()]
    if not (email_from and pwd and tos):
        logger.warning(
            "[email] missing EMAIL_FROM, EMAIL_PASSWORD, or EMAIL_TO — not sending"
        )
        return

    # Disabled for now: LEAPS/debit-spread AI lists are not included in the subject.
    # s_spreads = ", ".join(ai_spreads_list[:2])
    # s_leaps = ", ".join(ai_leaps_list[:2])
    # subj_tail = f"Spreads: {s_spreads}" + (f" | LEAPS: {s_leaps}" if s_leaps else "")
    subject = f"{subj_prefix} — {stamp}".strip()
    alert_parts: List[str] = []
    if pcs_opportunity_tickers is not None:
        po = pcs_opportunity_tickers or []
        if po:
            ox = ", ".join(str(t) for t in po[:8])
            if len(po) > 8:
                ox += " …"
            alert_parts.append(f"PCS ideas: {ox}")
    if pcs_actionable_tickers is not None:
        pa = pcs_actionable_tickers or []
        if pa:
            px = ", ".join(str(t) for t in pa[:10])
            if len(pa) > 10:
                px += " …"
            alert_parts.append(f"Position actions: {px}")
    if alert_parts:
        subject = f"{subject} — " + " · ".join(alert_parts)

    strong_buy_entries = _tickers_from_rows(alltime_high_trend_rows, entry_only=True)
    trend_entries = _tickers_from_rows(trend_entry_rows, entry_only=True)
    wheel_tickers = _tickers_from_rows(wheel_rows)

    html_universe = _list_html(universe_tickers)
    html_picks = _list_html(picks_tickers)
    html_alltime_high_value = _list_html(alltime_high_value_list or [])
    html_strong_buy_entries = _list_html(strong_buy_entries)
    html_trend_entries = _list_html(trend_entries)
    html_pcs_opportunities_block = ""
    if pcs_opportunities_section_html is not None:
        html_pcs_opportunities_block = (
            "<h3>PCS ideas for next session (pie_analyze_swing)</h3>"
            f"<div>{pcs_opportunities_section_html}</div>"
        )

    html_pcs_lifecycle_block = ""
    if pcs_lifecycle_section_html is not None:
        html_pcs_lifecycle_block = (
            "<h3>Open positions — lifecycle review (positions.json)</h3>"
            f"<div>{pcs_lifecycle_section_html}</div>"
        )
    html_wheel_tickers = _list_html(wheel_tickers)
    html_sims = _sim_table_html(sim_rows)
    html_perf = _perf_table_html(perf_rows)
    if momentum_section_html:
        html_momentum_block = (
            "<h3>Momentum portfolio</h3>"
            f"<div>{momentum_section_html}</div>"
        )
    else:
        html_momentum_block = ""

    if momentum_sim_rows is None:
        html_momentum_sims = "<i>Momentum portfolio not run (disabled or error).</i>"
    elif not momentum_sim_rows:
        html_momentum_sims = "<i>No new highs today — no simulator rows.</i>"
    else:
        html_momentum_sims = _sim_table_html(momentum_sim_rows)

    if momentum_perf_rows is None:
        html_momentum_perf = "<i>Momentum portfolio not run (disabled or error).</i>"
    elif not momentum_perf_rows:
        html_momentum_perf = "<i>No new highs today — no performance rows.</i>"
    else:
        html_momentum_perf = _perf_table_html(momentum_perf_rows)

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

      {html_pcs_opportunities_block}

      {html_pcs_lifecycle_block}

      {html_momentum_block}

      <h3>Momentum — Simulators (new high today)</h3>
      {html_momentum_sims}

      <h3>Momentum — Performance (new high today)</h3>
      {html_momentum_perf}

      <h3>Wheel Stocks</h3>
      <div>{html_wheel_tickers}</div>

      <h3>Simulators</h3>
      {html_sims}

      <h3>Performance (Price Change)</h3>
      {html_perf}

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