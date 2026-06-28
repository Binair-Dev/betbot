"""Scheduler jobs for Betbot."""
from __future__ import annotations

from datetime import datetime

import pytz

from betbot.config import settings
from betbot.logging_setup import get_logger

log = get_logger(__name__)
_TZ = pytz.timezone(settings.TIMEZONE)


def job_analyze_and_bet() -> None:
    """Job 1 — 00:00 local: analyse matches of the day, place bets."""
    now = datetime.now(_TZ)
    log.info("=" * 60)
    log.info("[JOB 1] Analyse & betting started at %s", now.isoformat())
    log.info("=" * 60)
    try:
        from betbot.scheduler.run_daily import run_daily_analysis
        run_daily_analysis()
    except Exception as exc:
        log.exception("Daily analysis job failed: %s", exc)


def job_settle_results() -> None:
    """Job 2 — 23:00 local: fetch results and settle pending bets."""
    now = datetime.now(_TZ)
    log.info("=" * 60)
    log.info("[JOB 2] Result settlement started at %s", now.isoformat())
    log.info("=" * 60)
    try:
        from betbot.betting.results import settle_pending_bets
        settle_pending_bets()
    except Exception as exc:
        log.exception("Settlement job failed: %s", exc)


def job_recompute_elo() -> None:
    """Job 3 — 06:00 local: refresh Elo ratings from latest results."""
    now = datetime.now(_TZ)
    log.info("=" * 60)
    log.info("[JOB 3] Elo recomputation started at %s", now.isoformat())
    log.info("=" * 60)
    try:
        from betbot.features.elo import recompute_all_elos
        recompute_all_elos()
    except Exception as exc:
        log.exception("Elo recomputation job failed: %s", exc)
