import os
import ssl
from email.message import EmailMessage

def _list_html(items, max_items=100):
    if not items: return "<i>None</i>"
    items = items[:max_items]
    return ", ".join(map(str, items))

def send_email_report_simple(*,
    stamp: str,
    picks_tickers: list,
    ai_spreads_list: list,
    ai_leaps_list: list,
    subj_prefix: str = "Daily Stock Picks"
):
    if os.getenv("SEND_EMAIL","0") != "1":
        return
    email_from = os.getenv("EMAIL_FROM"); pwd = os.getenv("EMAIL_PASSWORD")
    tos = [t.strip() for t in os.getenv("EMAIL_TO","").split(",") if t.strip()]
    if not (email_from and pwd and tos):
        return

    s_spreads = ", ".join(ai_spreads_list[:2])
    s_leaps   = ", ".join(ai_leaps_list[:2])
    subj_tail = f"Spreads: {s_spreads}" + (f" | LEAPS: {s_leaps}" if s_leaps else "")
    subject = f"{subj_prefix} — {stamp} | {subj_tail}".strip().rstrip(" |")

    html_body = f"""<html><body>
      <h2>Daily Stock Picks — {stamp}</h2>
      <h3>Stock Picks (buy_flag + top leaders)</h3>
      <div>{_list_html(picks_tickers)}</div>

      <h3>AI: 30–40 Day Debit Call Spreads</h3>
      <div>{_list_html(ai_spreads_list)}</div>

      <h3>AI: LEAPS (12–24 months)</h3>
      <div>{_list_html(ai_leaps_list)}</div>
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