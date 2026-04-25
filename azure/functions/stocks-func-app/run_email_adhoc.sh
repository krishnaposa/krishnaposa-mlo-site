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
export EMAIL_PASSWORD="${EMAIL_PASSWORD:-<gmail-app-password>}"
export EMAIL_TO="krishnaposa@gmail.com"
export EMAIL_SUBJECT_PREFIX="Adhoc Stock Picks"

# Required for universe/local-list Blob access.
export MONITOR_STORAGE="${MONITOR_STORAGE:-<azure-storage-connection-string>}"

# Optional wheel strategy knobs.
export WHEEL_ENABLED="1"
export WHEEL_DEBUG="1"
export WHEEL_TOPK="8"

export WHEEL_MIN_INSIDER_OWNERSHIP="0"
export WHEEL_MIN_REL_VOLUME="0.8"
export WHEEL_MAX_DIST_52W_HIGH="0.10"
export WHEEL_MIN_GROWTH="0.10"
export WHEEL_MIN_OI="100"
export WHEEL_MAX_SPREAD_PCT="0.30"
export WHEEL_PREFILTER_TOPN="100"
export WHEEL_MIN_PRICE="10"
export WHEEL_MIN_MARKET_CAP="10000000000"
export WHEEL_MAX_RSI="70"

python run_daily_monitor.py
