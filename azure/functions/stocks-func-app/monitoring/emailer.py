# emailer.py
import os
import ssl
from typing import Iterable, Optional
from email.message import EmailMessage

try:
    import pandas as pd
except Exception:
    pd = None  # graceful if pandas isn't available for some reason


# ---------- small helpers ----------
def _list_html(items: Optional[Iterable], max_items: int = 100) -> str:
    if not items:
        return "<i>None</i>"
    items = [str(x) for x in items][:max_items]
    return ", ".join(items)

def _render_sim_table(sim_df) -> str:
    """
    Render the simulation section if both columns are present:
      - 'mc_p_up' (Monte Carlo probability of up move)
      - 'hmm_bull_p' (HMM probability of bull regime)
    The table headers must appear as:
      Monte Carlo (P↑) | HMM (Bull Prob)
    A short reminder line is placed directly under the table.
    """
    if sim_df is None or pd is None:
        return ""

    # Accept either a pandas.DataFrame or something convertible into one
    try:
        df = pd.DataFrame(sim_df)
    except Exception:
        return ""

    needed = {"ticker", "mc_p_up", "hmm_bull_p"}
    if not needed.issubset(set(df.columns)):
        return ""

    # Keep it tidy: drop NaNs, round to 2 decimals, show top 10 by presence order
    dfv = (
        df[["ticker", "mc_p_up", "hmm_bull_p"]]
        .dropna(subset=["mc_p_up", "hmm_bull_p"])
        .copy()
        .head(10)
    )

    if dfv.empty:
        return ""

    # Rename headers exactly as requested
    dfv = dfv.rename(columns={
        "mc_p_up": "Monte Carlo (P↑)",
        "hmm_bull_p": "HMM (Bull Prob)"
    })

    # numeric formatting
    for c in ["Monte Carlo (P↑)", "HMM (Bull Prob)"]:
        dfv[c] = pd.to_numeric(dfv[c], errors="coerce").round(2)

    html = []
    html.append("<h3>📈 Market Simulations</h3>")
    html.append(dfv.to_html(index=False, border=0, justify="left"))
    html.append("""
      <p><small>
        <b>Monte Carlo (P↑)</b> = Probability price is higher over the next 30–40 days.<br>
        <b>HMM (Bull Prob)</b> = Probability current regime is bullish.
      </small></p>
    """)
    return "\n".join(html)


# ---------- main API ----------
def send_email_report_simple(
    *,
    stamp: str,
    picks_tickers: list,
    ai_spreads_list: list,
    ai_leaps_list: list,
    sim_df=None,                         # <--- NEW: pass df_all (or a sub-DataFrame) with columns: ticker, mc_p_up, hmm_bull_p
    subj_prefix: str = "Daily Stock Picks"
):
    """
    Minimal email:
      - Subject includes top 2 AI names (spreads & leaps)
      - Body shows three flat lists (picks, AI spreads, AI leaps)
      - Plus a simulation table with headers "Monte Carlo (P↑)" and "HMM (Bull Prob)"
        and a short reminder line under it.
    """
    if os.getenv("SEND_EMAIL", "0") != "1":
        return

    email_from = os.getenv("EMAIL_FROM")
    pwd = os.getenv("EMAIL_PASSWORD")
    tos = [t.strip() for t in os.getenv("EMAIL_TO", "").split(",") if t.strip()]
    if not (email_from and pwd and tos):
        return

    # Subject surfacing top names
    s_spreads = ", ".join([str(x) for x in ai_spreads_list[:2]])
    s_leaps   = ", ".join([str(x) for x in ai_leaps_list[:2]])
    subj_tail = f"Spreads: {s_spreads}" + (f" | LEAPS: {s_leaps}" if s_leaps else "")
    subject = f"{subj_prefix} — {stamp} | {subj_tail}".strip().rstrip(" |")

    # Build the simulation section (optional)
    sim_html = _render_sim_table(sim_df)

    # Body
    html_body = f"""<html><body>
      <h2>Daily Stock Picks — {stamp}</h2>

      <h3>Stock Picks (buy_flag + top leaders)</h3>
      <div>{_list_html(picks_tickers)}</div>

      <h3>AI: 30–40 Day Debit Call Spreads</h3>
      <div>{_list_html(ai_spreads_list)}</div>

      <h3>AI: LEAPS (12–24 months)</h3>
      <div>{_list_html(ai_leaps_list)}</div>

      <hr>
      {sim_html if sim_html else "<p><i>No simulation results today.</i></p>"}
    </body></html>"""

    # Send
    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = ", ".join(tos)
    msg["Subject"] = subject
    msg.set_content("See HTML version")
    msg.add_alternative(html_body, subtype="html")

    import smtplib
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(email_from, pwd)
        s.send_message(msg)