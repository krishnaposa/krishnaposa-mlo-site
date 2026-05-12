#!/usr/bin/env bash
set -euo pipefail

# Run from Git Bash on Windows. If using WSL, change /c/... to /mnt/c/...
cd "/c/pers/krishnaposa-mlo-site/azure/functions/stocks-func-app"

if [[ -f ".venv/Scripts/activate" ]]; then
  # Git Bash / Windows venv
  # shellcheck disable=SC1091
  source ".venv/Scripts/activate"
elif [[ -f ".venv/bin/activate" ]]; then
  # WSL / Linux venv
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

# Email settings. Use a Gmail app password, not your normal Gmail password.
export SEND_EMAIL="1"
export EMAIL_FROM="krishna.posa@gmail.com"
export EMAIL_PASSWORD="ivwy ubxh jzjd atmr"
export EMAIL_TO="krishnaposa@gmail.com"
export EMAIL_SUBJECT_PREFIX="Adhoc Stock Picks"

# Required for universe/local-list Blob access.
export MONITOR_STORAGE="${MONITOR_STORAGE:-<azure-storage-connection-string>}"

# --- Momentum RS portfolio (trailing stop + RS exit; email section) ---
# Persists to blob momentum_portfolio.json (override container/name if needed).
export MOMENTUM_PORTFOLIO_ENABLED="${MOMENTUM_PORTFOLIO_ENABLED:-1}"
export MOMENTUM_FINVIZ_URL="${MOMENTUM_FINVIZ_URL:-https://finviz.com/screener.ashx?v=111&f=cap_midover,sh_price_o5,ta_highlow52w_nh&ft=3}"
# Used when the URL has no &o= sort param (yfinance/Finviz screener order).
export MOMENTUM_FINVIZ_SORT="${MOMENTUM_FINVIZ_SORT:--marketcap}"
export MOMENTUM_PORTFOLIO_SIZE="${MOMENTUM_PORTFOLIO_SIZE:-20}"
export MOMENTUM_RS_EXIT_THRESHOLD="${MOMENTUM_RS_EXIT_THRESHOLD:-70}"
export MOMENTUM_TRAILING_STOP_PCT="${MOMENTUM_TRAILING_STOP_PCT:-0.15}"
# After successful blob save, also write ./momentum_portfolio.json (handy for local).
export MOMENTUM_PORTFOLIO_MIRROR_LOCAL="${MOMENTUM_PORTFOLIO_MIRROR_LOCAL:-1}"

# Holdings list: same trailing/RS rules; state in holdings_trailing_state.json.
# holdings_list.json is NOT auto-edited on exit (you remove tickers manually). Set to 1 to auto-drop exits from the blob:
export HOLDINGS_LIST_REMOVE_ON_EXIT="${HOLDINGS_LIST_REMOVE_ON_EXIT:-0}"
export HOLDINGS_TRAILING_EXITS_ENABLED="${HOLDINGS_TRAILING_EXITS_ENABLED:-1}"

# Optional wheel strategy knobs.
export WHEEL_ENABLED="1"
export WHEEL_DEBUG="1"
export WHEEL_INCLUDE_FINVIZ="1"
export WHEEL_FINVIZ_TOPN="25"
export WHEEL_USE_EQUITY_FILTERS="0"
export WHEEL_TOPK="8"

# Configurable Finviz wheel query tokens. Set any to empty to omit that filter.
export WHEEL_FINVIZ_RSI_FILTER="${WHEEL_FINVIZ_RSI_FILTER:-ta_rsi_nob70}"
export WHEEL_FINVIZ_REL_VOLUME_FILTER="${WHEEL_FINVIZ_REL_VOLUME_FILTER:-sh_relvol_o1.2}"
export WHEEL_FINVIZ_HIGH_FILTER="${WHEEL_FINVIZ_HIGH_FILTER:-ta_highlow52w_b0to10h}"
export WHEEL_FINVIZ_SMA20_FILTER="${WHEEL_FINVIZ_SMA20_FILTER:-ta_sma20_pa}"
export WHEEL_FINVIZ_SMA50_FILTER="${WHEEL_FINVIZ_SMA50_FILTER:-ta_sma50_pa}"
export WHEEL_FINVIZ_SORT="${WHEEL_FINVIZ_SORT:--change}"

export WHEEL_MIN_INSIDER_OWNERSHIP="0"
export WHEEL_MIN_REL_VOLUME="0.8"
export WHEEL_MAX_DIST_52W_HIGH="0.10"
export WHEEL_MIN_GROWTH="0.10"
export WHEEL_MIN_OI="0"
export WHEEL_MAX_SPREAD_PCT="0.30"
export WHEEL_PREFILTER_TOPN="100"
export WHEEL_MIN_PRICE="10"
export WHEEL_MIN_MARKET_CAP="10000000000"
export WHEEL_MAX_RSI="70"
export EARNINGS_BLOCK_DAYS="45"
export WHEEL_BLOCK_EARNINGS="1"

python run_daily_monitor.py
