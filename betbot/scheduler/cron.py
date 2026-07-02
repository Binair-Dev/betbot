"""APScheduler configuration — pure scraping, no betting.

The bot now does three things on a schedule:
  - 00:00 daily: pull today's + tomorrow's fixtures, refresh stale results,
                pull latest odds.
  - 06:00 daily: pull fresh odds (the morning line often differs from
                yesterday's close).
  - 12:00 daily: same — midday line, useful for late-evening kick-offs.
  - 23:00 daily: final odds refresh + final result check before midnight.

No predictions. No model. No bets. The dashboard's 'Données brutes' page
shows everything we collect.
"""
from __future__ import annotations

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from betbot.config import settings
from betbot.logging_setup import get_logger
from betbot.scheduler.scrape import (
    refresh_results,
    scrape_fixtures,
    scrape_odds,
)

log = get_logger(__name__)


def _full_scrape() -> None:
    """Run fixtures + results + odds. Used at midnight and on manual trigger."""
    try:
        scrape_fixtures(days_ahead=2)
    except Exception as exc:
        log.exception("scrape_fixtures failed: %s", exc)
    try:
        refresh_results()
    except Exception as exc:
        log.exception("refresh_results failed: %s", exc)
    try:
        scrape_odds(days_ahead=2)
    except Exception as exc:
        log.exception("scrape_odds failed: %s", exc)


def _odds_only() -> None:
    """Refresh odds + results without re-pulling fixtures."""
    try:
        refresh_results()
    except Exception as exc:
        log.exception("refresh_results failed: %s", exc)
    try:
        scrape_odds(days_ahead=2)
    except Exception as exc:
        log.exception("scrape_odds failed: %s", exc)


def build_scheduler() -> BlockingScheduler:
    tz = pytz.timezone(settings.TIMEZONE)
    scheduler = BlockingScheduler(timezone=tz)

    # 00:00 — full cycle (fixtures + results + odds)
    scheduler.add_job(
        _full_scrape, CronTrigger(hour=0, minute=0, timezone=tz),
        id="full_scrape_midnight",
        name="Full scrape (fixtures + results + odds)",
        replace_existing=True, misfire_grace_time=900, coalesce=True,
    )

    # 06:00, 12:00, 18:00 — odds + results only
    for hour in (6, 12, 18):
        scheduler.add_job(
            _odds_only, CronTrigger(hour=hour, minute=0, timezone=tz),
            id=f"odds_refresh_{hour:02d}",
            name=f"Refresh odds & results ({hour:02d}:00)",
            replace_existing=True, misfire_grace_time=900, coalesce=True,
        )

    # 23:00 — final refresh before midnight
    scheduler.add_job(
        _odds_only, CronTrigger(hour=23, minute=0, timezone=tz),
        id="odds_refresh_23",
        name="Refresh odds & results (23:00)",
        replace_existing=True, misfire_grace_time=900, coalesce=True,
    )

    return scheduler
