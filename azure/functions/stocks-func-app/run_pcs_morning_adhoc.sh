#!/usr/bin/env bash
set -euo pipefail

# Morning PCS execution email (ideas + open-position lifecycle). Run near 10:00 ET.
cd "/c/pers/krishnaposa-mlo-site/azure/functions/stocks-func-app"

if [[ -f ".venv/Scripts/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/Scripts/activate"
elif [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

export SEND_EMAIL="${SEND_EMAIL:-1}"
export EMAIL_FROM="${EMAIL_FROM:-krishna.posa@gmail.com}"
export EMAIL_PASSWORD="${EMAIL_PASSWORD:-ivwy ubxh jzjd atmr}"
export EMAIL_TO="${EMAIL_TO:-krishnaposa@gmail.com}"
export PCS_MORNING_SUBJECT_PREFIX="${PCS_MORNING_SUBJECT_PREFIX:-PCS — today}"
export PCS_SESSION_LABEL="${PCS_SESSION_LABEL:-"today's session"}"

export MONITOR_STORAGE="${MONITOR_STORAGE:-DefaultEndpointsProtocol=https;AccountName=stockmonitorsg;AccountKey=EuLxqWwCZ372e3t91CXTf0WLnvt08ZEWZZyxPLPURGhQilq38WiWi6mXED1yWAdclMP7v5jwRwm2+AStwoHE9w==;EndpointSuffix=core.windows.net}"

export PCS_OPPORTUNITIES_ENABLED="${PCS_OPPORTUNITIES_ENABLED:-1}"
export PIE_TICKERS_FILE="${PIE_TICKERS_FILE:-/c/pers/krishnaposa-mlo-site/scripts/stocks/my_tickers.txt}"
export PIE_TARGET_DTE="${PIE_TARGET_DTE:-35}"
export PIE_OTM_PCT="${PIE_OTM_PCT:-0.06}"
export PIE_SPREAD_WIDTH_PCT="${PIE_SPREAD_WIDTH_PCT:-0.03}"
export PIE_MAX_PCS_CANDIDATES="${PIE_MAX_PCS_CANDIDATES:-12}"

export PCS_LIFECYCLE_ENABLED="${PCS_LIFECYCLE_ENABLED:-1}"
export PCS_POSITIONS_FILE="${PCS_POSITIONS_FILE:-/c/pers/krishnaposa-mlo-site/scripts/stocks/positions.json}"
export PCS_PROFIT_TARGET="${PCS_PROFIT_TARGET:-50}"
export PCS_STOP_LOSS="${PCS_STOP_LOSS:--100}"
export PCS_ROLL_DTE="${PCS_ROLL_DTE:-14}"
export PCS_MANAGE_DTE="${PCS_MANAGE_DTE:-21}"

python run_pcs_morning.py
