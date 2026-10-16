"""Once-a-day Forecast & Pricing refresh, for cron / Task Scheduler / launchd.

    cd livingdoc/backend && python ../scripts/refresh_daily.py            # normal run
    cd livingdoc/backend && python ../scripts/refresh_daily.py --force    # re-run the web search even if cached today

For every branch it: (1) refreshes the web-trend scores (falls back to labelled assumed scores offline),
(2) imports yesterday's LivingDoc numbers as sales (set LIVINGDOC_FORESIGHT_AUTOIMPORT=0 to skip),
(3) freezes today's forecast so the scorecard can grade it later.

Schedule examples
    macOS/Linux cron:   30 6 * * *  cd /path/to/livingdoc/backend && python ../scripts/refresh_daily.py
    Windows:            Task Scheduler -> daily -> python scripts\refresh_daily.py (start in the backend folder)

The API server also runs this job itself, at most once per day, when its background workers are on.
Use the same LIVINGDOC_DB / LIVINGDOC_FORESIGHT_DIR environment as the server.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.services import forecasting  # noqa: E402
from app.services.seed import init_db  # noqa: E402


def main(force: bool = False) -> int:
    init_db()
    summary = forecasting.daily_refresh(force=force)
    bad = 0
    for branch, res in summary.items():
        if "error" in res:
            bad += 1
        print(f"{branch}: " + ", ".join(f"{k}={v}" for k, v in res.items()))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
