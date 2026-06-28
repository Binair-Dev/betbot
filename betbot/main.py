"""Betbot entry point.

Starts the scheduler and keeps the bot process alive.
The dashboard is a separate docker-compose service that runs Streamlit.
"""
from __future__ import annotations

import signal
import sys
import time

from betbot.config import settings
from betbot.db.repository import init_db
from betbot.logging_setup import get_logger, setup_logging
from betbot.scheduler.cron import build_scheduler

log = get_logger("betbot.main")


def _handle_signal(signum, _frame) -> None:  # noqa: ANN001
    log.info("Received signal %s, shutting down", signum)
    sys.exit(0)


def main() -> None:
    setup_logging()
    log.info("=" * 60)
    log.info("Betbot starting")
    log.info("Bankroll start: %.2f € | Bet size: %.2f €", settings.BANKROLL_START, settings.BET_SIZE)
    log.info("Timezone: %s", settings.TIMEZONE)
    log.info("Confidence threshold: %.2f | Value threshold: %.2f",
             settings.CONFIDENCE_THRESHOLD, settings.VALUE_THRESHOLD)
    log.info("=" * 60)

    init_db()
    log.info("Database initialized at %s", settings.DB_PATH)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    scheduler = build_scheduler()
    log.info("Scheduled jobs:")
    for job in scheduler.get_jobs():
        log.info("  - %s | trigger: %s", job.name, job.trigger)

    log.info("Bot is running. Dashboard on http://localhost:8501")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
    except Exception:
        log.exception("Fatal error in scheduler")
        time.sleep(5)
        sys.exit(1)


if __name__ == "__main__":
    main()
