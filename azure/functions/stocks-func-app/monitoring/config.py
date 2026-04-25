import os

# Logging
DAILY_MONITOR_LOG_LEVEL = os.getenv("DAILY_MONITOR_LOG_LEVEL", "INFO").upper()

# Yahoo fetch
YF_BATCH_SIZE = int(os.getenv("YF_BATCH_SIZE", "50"))
YF_MAX_RETRIES = int(os.getenv("YF_MAX_RETRIES", "2"))
YF_RETRY_BACKOFF_S = float(os.getenv("YF_RETRY_BACKOFF_S", "3.0"))

# Liquidity / penny threshold
MIN_DOLLAR_VOL_DEFAULT = int(os.getenv("MIN_DOLLAR_VOL", "1000000"))
PENNY_PRICE = float(os.getenv("PENNY_PRICE", "5"))

# Local list policy
LOCAL_PRUNE_COUNT = int(os.getenv("LOCAL_PRUNE_COUNT", "5"))
LOCAL_MAX_SIZE = int(os.getenv("LOCAL_MAX_SIZE", "0")) or None
LOCAL_ADD_MIN_PRICE = float(os.getenv("LOCAL_MIN_PRICE", str(PENNY_PRICE)))
LOCAL_ADD_MIN_STRENGTH_Z = float(os.getenv("LOCAL_MIN_STRENGTH_Z", "0.0"))

# Email
AI_EMAIL_TOPK = int(os.getenv("AI_EMAIL_TOPK", "8"))
EMAIL_INCLUDE_FULL = (os.getenv("EMAIL_INCLUDE_FULL", "0") == "1")  # OFF by default

# Leaders inclusion into picks
ADD_LEADERS_TOPK = int(os.getenv("ADD_LEADERS_TOPK", "8"))

# Optional MC/HMM filter
USE_MC_HMM_FILTER = (os.getenv("USE_MC_HMM_FILTER", "0") == "1")
MC_MIN_PUP = float(os.getenv("MC_MIN_PUP", "0.55"))
HMM_MIN_BULL = float(os.getenv("HMM_MIN_BULL", "0.50"))

# --- Options-specific gates for debit call spreads (defaults; override via env) ---

OPT_MIN_OI         = int(os.getenv("OPT_MIN_OI", "500"))        # min OI for each leg
OPT_MAX_SPREAD_PCT = float(os.getenv("OPT_MAX_SPREAD_PCT", "0.12"))  # combined bid/ask width vs mid debit (≤ 12%)

IVP_MIN            = float(os.getenv("IVP_MIN", "0.20"))         # 20th percentile proxy
IVP_MAX            = float(os.getenv("IVP_MAX", "0.70"))         # 70th percentile proxy

DTE_MIN            = int(os.getenv("DTE_MIN", "25"))
DTE_MAX            = int(os.getenv("DTE_MAX", "50"))

EARNINGS_BLOCK_DAYS = int(os.getenv("EARNINGS_BLOCK_DAYS", "14"))

OTM_LONG_PCT       = float(os.getenv("OTM_LONG_PCT", "0.05"))    # +5% OTM for the long call
OTM_SHORT_PCT      = float(os.getenv("OTM_SHORT_PCT", "0.10"))   # +10% OTM for the short call

# --- Wheel / cash-secured put candidates ---
WHEEL_ENABLED = (os.getenv("WHEEL_ENABLED", "1") == "1")
WHEEL_TOPK = int(os.getenv("WHEEL_TOPK", "8"))
WHEEL_PREFILTER_TOPN = int(os.getenv("WHEEL_PREFILTER_TOPN", "40"))
WHEEL_MIN_DTE = int(os.getenv("WHEEL_MIN_DTE", "35"))
WHEEL_MAX_DTE = int(os.getenv("WHEEL_MAX_DTE", "55"))
WHEEL_PUT_OTM_PCT = float(os.getenv("WHEEL_PUT_OTM_PCT", "0.05"))
WHEEL_MIN_MARKET_CAP = float(os.getenv("WHEEL_MIN_MARKET_CAP", "10000000000"))
WHEEL_MIN_PRICE = float(os.getenv("WHEEL_MIN_PRICE", "10"))
WHEEL_MAX_RSI = float(os.getenv("WHEEL_MAX_RSI", "70"))
WHEEL_MIN_REL_VOLUME = float(os.getenv("WHEEL_MIN_REL_VOLUME", "1.2"))
WHEEL_MAX_DIST_52W_HIGH = float(os.getenv("WHEEL_MAX_DIST_52W_HIGH", "0.05"))
WHEEL_MAX_DEBT_TO_EQUITY = float(os.getenv("WHEEL_MAX_DEBT_TO_EQUITY", "1.0"))
WHEEL_MIN_INSIDER_OWNERSHIP = float(os.getenv("WHEEL_MIN_INSIDER_OWNERSHIP", "0.10"))
WHEEL_MIN_GROWTH = float(os.getenv("WHEEL_MIN_GROWTH", "0.20"))
WHEEL_MIN_OI = int(os.getenv("WHEEL_MIN_OI", "500"))
WHEEL_MAX_SPREAD_PCT = float(os.getenv("WHEEL_MAX_SPREAD_PCT", "0.15"))
WHEEL_BLOCK_EARNINGS = (os.getenv("WHEEL_BLOCK_EARNINGS", "1") == "1")