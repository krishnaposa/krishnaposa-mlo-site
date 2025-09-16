# constants.py
UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/124.0")
UA_HDRS = {"User-Agent": UA_STR, "Accept-Language": "en-US,en;q=0.9"}

REDFIN_MEDIAN_CSV = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "housing-market-data/market-tracker/median_sale_price.csv"
)

DUMP_DIR = "rf_dumps"