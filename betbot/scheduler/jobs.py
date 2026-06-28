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
        _refresh_pending_match_scores()
        from betbot.betting.results import settle_pending_bets
        settle_pending_bets()
    except Exception as exc:
        log.exception("Settlement job failed: %s", exc)


def _refresh_pending_match_scores() -> None:
    """Update match scores/status from football-data.org for all pending bets."""
    from betbot.data.football_data_org import refresh_match_result
    from betbot.db.repository import execute, query

    pending = query("""
        SELECT DISTINCT b.match_id
        FROM bets b
        JOIN matches m ON m.match_id = b.match_id
        WHERE b.status = 'pending'
          AND m.status NOT IN ('FT', 'CANC', 'PST', 'AET', 'PEN')
    """)
    if not pending:
        return

    log.info("Refreshing scores for %d pending matches", len(pending))
    for row in pending:
        mid = row["match_id"]
        result = refresh_match_result(mid)
        if not result:
            log.debug("No result data for match %s", mid)
            continue
        execute(
            """UPDATE matches SET
               status=?, home_score=?, away_score=?,
               home_ht_score=?, away_ht_score=?, updated_at=CURRENT_TIMESTAMP
               WHERE match_id=?""",
            (result["status"], result["home_score"], result["away_score"],
             result["home_ht_score"], result["away_ht_score"], mid),
        )
        log.info("Match %s → status=%s score=%s-%s",
                 mid, result["status"], result["home_score"], result["away_score"])


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
