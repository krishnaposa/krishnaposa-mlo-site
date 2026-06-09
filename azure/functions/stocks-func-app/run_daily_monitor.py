import datetime
import logging
import os
import warnings

# Stderr noise from pandas/sklearn/etc. (does not affect logging).
warnings.filterwarnings("ignore")

# Configure logging before importing monitor so this entrypoint owns root level.
# (monitor.py also calls basicConfig; it becomes a no-op if the root logger already has handlers.)
_lvl_name = os.getenv("DAILY_MONITOR_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _lvl_name, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if os.getenv("DAILY_MONITOR_SHOW_WARNINGS", "0") != "1":

    class _DropLoggingWarning(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.levelno != logging.WARNING

    for _h in logging.root.handlers:
        _h.addFilter(_DropLoggingWarning())

for _quiet in (
    "urllib3",
    "urllib3.connectionpool",
    "azure.core.pipeline.policies.http_logging_policy",
):
    logging.getLogger(_quiet).setLevel(logging.ERROR)

from monitoring.monitor import run_monitor  # noqa: E402

LIST_TICKERS = []
OUT_DIR = "out_local_monitor"
os.makedirs(OUT_DIR, exist_ok=True)


def main():
    logging.info("=== Running local daily monitor ===")
    df_all, df_leaders = run_monitor(LIST_TICKERS)

    stamp = datetime.date.today().strftime("%Y-%m-%d")
    csv_all = os.path.join(OUT_DIR, f"daily_snapshot_{stamp}.csv")
    csv_lead = os.path.join(OUT_DIR, f"leaders_{stamp}.csv")

    df_all.to_csv(csv_all, index=False)
    df_leaders.to_csv(csv_lead, index=False)

    logging.info(f"Saved {csv_all} and {csv_lead}")

    print("\nTop Picks Today:")
    print(df_all[df_all["buy_flag"]][["ticker", "score"]].head(12).reset_index(drop=True))

    print("\nLeaders (5d & 21d up):")
    print(df_leaders.head(15).reset_index(drop=True))

    logging.info("=== Done ===")


if __name__ == "__main__":
    main()
