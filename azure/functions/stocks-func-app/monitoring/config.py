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
ADD_LEADERS_TOPK = int(os.getenv("ADD_LEADERS_TOPK", "5"))

# Optional MC/HMM filter
USE_MC_HMM_FILTER = (os.getenv("USE_MC_HMM_FILTER", "0") == "1")
MC_MIN_PUP = float(os.getenv("MC_MIN_PUP", "0.55"))
HMM_MIN_BULL = float(os.getenv("HMM_MIN_BULL", "0.50"))