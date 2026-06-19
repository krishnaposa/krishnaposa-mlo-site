#!/usr/bin/env bash
set -euo pipefail

# Morning PMCC screening email (LEAP ideas + open PMCC lifecycle). Run near 10:30 ET.
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
export PMCC_MORNING_SUBJECT_PREFIX="${PMCC_MORNING_SUBJECT_PREFIX:-PMCC — today}"

export MONITOR_STORAGE="${MONITOR_STORAGE:-DefaultEndpointsProtocol=https;AccountName=stockmonitorsg;AccountKey=EuLxqWwCZ372e3t91CXTf0WLnvt08ZEWZZyxPLPURGhQilq38WiWi6mXED1yWAdclMP7v5jwRwm2+AStwoHE9w==;EndpointSuffix=core.windows.net}"

export PMCC_OPPORTUNITIES_ENABLED="${PMCC_OPPORTUNITIES_ENABLED:-1}"
export PIE_TICKERS_FILE="${PIE_TICKERS_FILE:-/c/pers/krishnaposa-mlo-site/scripts/stocks/my_tickers.txt}"
export PMCC_MODE="${PMCC_MODE:-core}"
export PMCC_MIN_SCORE="${PMCC_MIN_SCORE:-6.0}"
export PMCC_PREFILTER_N="${PMCC_PREFILTER_N:-120}"
export PMCC_MAX_CHAIN_ANALYSIS="${PMCC_MAX_CHAIN_ANALYSIS:-80}"
export PMCC_MAX_CANDIDATES="${PMCC_MAX_CANDIDATES:-12}"
export PMCC_BLOCK_EARNINGS="${PMCC_BLOCK_EARNINGS:-1}"
export PMCC_EARNINGS_BLOCK_DAYS="${PMCC_EARNINGS_BLOCK_DAYS:-7}"
export PMCC_BLOCK_NEG_1Y="${PMCC_BLOCK_NEG_1Y:-1}"

export PMCC_LIFECYCLE_ENABLED="${PMCC_LIFECYCLE_ENABLED:-1}"
export PMCC_POSITIONS_FILE="${PMCC_POSITIONS_FILE:-/c/pers/krishnaposa-mlo-site/scripts/stocks/positions.json}"
export PMCC_SHORT_PROFIT_TARGET="${PMCC_SHORT_PROFIT_TARGET:-50}"

python run_pmcc_morning.py
