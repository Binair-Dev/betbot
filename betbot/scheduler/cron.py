"""APScheduler configuration and lifecycle."""
from __future__ import annotations

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from betbot.config import settings
from betbot.logging_setup import get_logger
from betbot.scheduler.jobs import job_analyze_and_bet, job_recompute_elo, job_settle_results

log = get_logger(__name__)


def build_scheduler() -> BlockingScheduler:
    tz = pytz.timezone(settings.TIMEZONE)
    scheduler = BlockingScheduler(timezone=tz)

    # 00:00 — analyse + paris
    scheduler.add_job(
        job_analyze_and_bet,
        CronTrigger(hour=0, minute=0, timezone=tz),
        id="daily_analysis",
        name="Daily analysis & betting",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
    )

    # 23:00 — règlement des résultats
    scheduler.add_job(
        job_settle_results,
        CronTrigger(hour=23, minute=0, timezone=tz),
        id="settle_results",
        name="Settle daily results",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
    )

    # 06:00 — recalcul Elo
    scheduler.add_job(
        job_recompute_elo,
        CronTrigger(hour=6, minute=0, timezone=tz),
        id="recompute_elo",
        name="Recompute Elo ratings",
        replace_existing=True,
        misfire_grace_time=900,
        coalesce=True,
    )

    return scheduler
