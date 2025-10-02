# run_daily_monitor.py
import datetime
import os
import logging
import daily_monitor  # our separate module

# ----------------------------------------------------------------------
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ----------------------------------------------------------------------
# Hardcoded list (same as in function app). 
# You could also import from a shared constants.py if you want.
LIST_TICKERS = []

OUT_DIR = "out_local_monitor"
os.makedirs(OUT_DIR, exist_ok=True)

# ----------------------------------------------------------------------
def main():
    logging.info("=== Running local daily monitor ===")
    df_all, df_leaders = daily_monitor.run_monitor(LIST_TICKERS)

    stamp = datetime.date.today().strftime("%Y-%m-%d")
    csv_all = os.path.join(OUT_DIR, f"daily_snapshot_{stamp}.csv")
    csv_lead = os.path.join(OUT_DIR, f"leaders_{stamp}.csv")

    df_all.to_csv(csv_all, index=False)
    df_leaders.to_csv(csv_lead, index=False)

    logging.info(f"Saved {csv_all} and {csv_lead}")

    # Print a quick peek
    print("\nTop Picks Today:")
    print(df_all[df_all["buy_flag"]][["ticker", "score"]].head(12).reset_index(drop=True))

    print("\nLeaders (5d & 21d up):")
    print(df_leaders.head(15).reset_index(drop=True))

    logging.info("=== Done ===")


if __name__ == "__main__":
    main()