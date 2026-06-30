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
    """Update match scores/status for all pending bets.

    Multi-source with fallback:
      1. football-data.org (primary — free, current season)
      2. API-Football (fallback — paid plans cover more competitions)

    Skips matches whose status is already terminal. Logs warnings on
    failures so the settlement job can retry on the next cycle.
    """
    from betbot.data.api_football import get_fixture_by_id
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
        result = _fetch_match_result(mid)
        if not result:
            log.warning("No result data for match %s (sources exhausted) — will retry", mid)
            continue
        execute(
            """UPDATE matches SET
               status=?, home_score=?, away_score=?,
               home_ht_score=?, away_ht_score=?,
               home_score_regular=?, away_score_regular=?,
               home_score_et=?, away_score_et=?,
               home_score_pen=?, away_score_pen=?,
               match_duration=?, match_winner=?,
               updated_at=CURRENT_TIMESTAMP
               WHERE match_id=?""",
            (result["status"], result["home_score"], result["away_score"],
             result["home_ht_score"], result["away_ht_score"],
             result.get("home_score_regular"), result.get("away_score_regular"),
             result.get("home_score_et"), result.get("away_score_et"),
             result.get("home_score_pen"), result.get("away_score_pen"),
             result.get("match_duration"), result.get("match_winner"),
             mid),
        )
        log.info(
            "Match %s → status=%s reg=%s-%s et=%s-%s pen=%s-%s dur=%s winner=%s (src=%s)",
            mid, result["status"],
            result.get("home_score_regular"), result.get("away_score_regular"),
            result.get("home_score_et"), result.get("away_score_et"),
            result.get("home_score_pen"), result.get("away_score_pen"),
            result.get("match_duration"), result.get("match_winner"),
            result.get("source", "?"),
        )


def _fetch_match_result(match_id: int) -> dict | None:
    """Try football-data.org, then API-Football. Return normalised dict or None.

    Always returns the full breakdown (regular / extraTime / penalties /
    duration / winner) so settlement can pick the correct score for the
    market (90-min vs full-time vs shootout).
    """
    from betbot.data.football_data_org import refresh_match_result
    from betbot.data.api_football import get_fixture_by_id

    result = refresh_match_result(match_id)
    if result and result.get("status") in ("FT", "AET", "PEN"):
        result["source"] = "football_data_org"
        return result

    fx = get_fixture_by_id(match_id)
    if fx:
        fixture = fx.get("fixture", {})
        goals = fx.get("goals", {}) or {}
        score = fx.get("score", {}) or {}
        ht = score.get("halftime", {}) or {}
        ft = score.get("fulltime", {}) or {}
        et = score.get("extratime", {}) or {}
        pen = score.get("penalty", {}) or {}
        # API-Football "goals" includes ET goals but NOT penalties.
        # fullTime is the 90-min score; extratime holds ET goals.
        reg_home = ft.get("home") if ft.get("home") is not None else goals.get("home")
        reg_away = ft.get("away") if ft.get("away") is not None else goals.get("away")
        et_home = et.get("home") or 0
        et_away = et.get("away") or 0
        pen_home = pen.get("home") or 0
        pen_away = pen.get("away") or 0
        duration = (
            "PENALTY_SHOOTOUT" if (pen_home or pen_away) else
            "EXTRA_TIME" if (et_home or et_away) else
            "REGULAR"
        )
        return {
            "status": fixture.get("status", {}).get("short", "NS"),
            "home_score": goals.get("home"),
            "away_score": goals.get("away"),
            "home_ht_score": ht.get("home"),
            "away_ht_score": ht.get("away"),
            "home_score_regular": reg_home,
            "away_score_regular": reg_away,
            "home_score_et": et_home,
            "away_score_et": et_away,
            "home_score_pen": pen_home,
            "away_score_pen": pen_away,
            "match_duration": duration,
            "match_winner": fixture.get("winner") or score.get("winner"),
            "source": "api_football",
        }

    return None


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
