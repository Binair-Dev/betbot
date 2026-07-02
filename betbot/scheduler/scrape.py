"""Scraper — collect fixtures, odds, and results from public APIs.

This is the entire job of the app. No predictions, no betting, no model.
The goal is to populate the SQLite database with raw, inspectable data
that the dashboard can display.

Data sources:
- football-data.org  → fixtures, results, league metadata (free, current season)
- The Odds API         → multi-bookmaker odds (free 500 req/month)
- API-Football         → fallback for results when football-data.org is missing data
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import pytz

from betbot.config import settings
from betbot.data.backfill import _upsert_fixture
from betbot.data.football_data_org import get_fixtures_by_date, refresh_match_result
from betbot.data.odds_fetcher import fetch_odds_for_today
from betbot.data.api_football import get_fixture_by_id
from betbot.db.repository import execute, query
from betbot.logging_setup import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def scrape_fixtures(days_ahead: int = 2) -> dict[str, int]:
    """Fetch fixtures for today and the next `days_ahead` days.

    Iterates football-data.org per-competition endpoints (free, no quota).
    Returns per-day counts so the caller can log issues.
    """
    tz = pytz.timezone(settings.TIMEZONE)
    today = datetime.now(tz).date()
    counts: dict[str, int] = {}
    grand_total = 0
    for offset in range(days_ahead + 1):
        day = today + timedelta(days=offset)
        day_dt = datetime.combine(day, datetime.min.time())
        try:
            fixtures = get_fixtures_by_date(day_dt)
            n_kept = 0
            for fx in fixtures:
                league_id = (fx.get("league") or {}).get("id")
                if league_id not in settings.TARGET_LEAGUES:
                    continue
                try:
                    _upsert_fixture(fx)
                    n_kept += 1
                except Exception as exc:
                    log.warning("Persist fixture failed: %s", exc)
            counts[day.isoformat()] = n_kept
            grand_total += n_kept
            log.info("scrape_fixtures %s: %d target-league matches", day, n_kept)
        except Exception as exc:
            log.warning("scrape_fixtures %s failed: %s", day, exc)
            counts[day.isoformat()] = 0
    log.info("scrape_fixtures total: %d matches over %d days",
             grand_total, days_ahead + 1)
    return counts


# ---------------------------------------------------------------------------
# Results (refresh scores for finished matches)
# ---------------------------------------------------------------------------

def _fetch_match_result_multi_source(match_id: int) -> dict | None:
    """Try football-data.org, fall back to API-Football. Returns flat dict."""
    r = refresh_match_result(match_id)
    if r and r.get("status") in ("FT", "AET", "PEN"):
        r["source"] = "football_data_org"
        return r
    fx = get_fixture_by_id(match_id)
    if fx:
        fixture = fx.get("fixture", {}) or {}
        goals = fx.get("goals", {}) or {}
        score = fx.get("score", {}) or {}
        ht = (score.get("halftime") or {})
        ft = (score.get("fulltime") or {})
        et = (score.get("extratime") or {})
        pen = (score.get("penalty") or {})
        reg_h = ft.get("home") if ft.get("home") is not None else goals.get("home")
        reg_a = ft.get("away") if ft.get("away") is not None else goals.get("away")
        et_h = et.get("home") or 0
        et_a = et.get("away") or 0
        pen_h = pen.get("home") or 0
        pen_a = pen.get("away") or 0
        duration = (
            "PENALTY_SHOOTOUT" if (pen_h or pen_a) else
            "EXTRA_TIME" if (et_h or et_a) else
            "REGULAR"
        )
        # API-Football doesn't always include a "winner" key; infer from goals
        h_goals = goals.get("home")
        a_goals = goals.get("away")
        if h_goals is not None and a_goals is not None:
            if h_goals > a_goals:
                winner = "HOME_TEAM"
            elif h_goals < a_goals:
                winner = "AWAY_TEAM"
            else:
                winner = "DRAW"
        else:
            winner = None
        return {
            "match_id": match_id,
            "status": fixture.get("status", {}).get("short", "NS"),
            "home_score": goals.get("home"),
            "away_score": goals.get("away"),
            "home_ht_score": ht.get("home"),
            "away_ht_score": ht.get("away"),
            "home_score_regular": reg_h,
            "away_score_regular": reg_a,
            "home_score_et": et_h,
            "away_score_et": et_a,
            "home_score_pen": pen_h,
            "away_score_pen": pen_a,
            "match_duration": duration,
            "match_winner": winner,
            "source": "api_football",
        }
    return None


def refresh_results(max_attempts: int = 3,
                    backoff: tuple[int, ...] = (5, 15, 45)) -> dict[str, int]:
    """Refresh scores for matches that aren't final yet.

    Multi-source with retry (transient SSL/connection errors are common on
    the free tier of these APIs). Returns {"updated": N, "failed": M}.
    """
    pending = query("""
        SELECT DISTINCT m.match_id
        FROM matches m
        WHERE m.status NOT IN ('FT', 'AET', 'PEN', 'CANC', 'PST')
          AND datetime(m.match_date) < datetime('now', '-30 minutes')
    """)
    if not pending:
        log.info("refresh_results: no stale matches to update")
        return {"updated": 0, "failed": 0, "skipped": 0}

    log.info("refresh_results: %d stale matches to check", len(pending))
    updated = 0
    failed = 0
    for row in pending:
        mid = row["match_id"]
        result = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = _fetch_match_result_multi_source(mid)
            except Exception as exc:
                log.warning("refresh match %s attempt %d raised: %s", mid, attempt, exc)
            if result is not None:
                break
            if attempt < max_attempts:
                wait = backoff[min(attempt - 1, len(backoff) - 1)]
                log.info("refresh match %s failed (attempt %d/%d), retrying in %ds",
                         mid, attempt, max_attempts, wait)
                time.sleep(wait)
        if not result:
            failed += 1
            log.warning("refresh_results: no data for match %s after %d attempts",
                        mid, max_attempts)
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
             result.get("home_ht_score"), result.get("away_ht_score"),
             result.get("home_score_regular"), result.get("away_score_regular"),
             result.get("home_score_et"), result.get("away_score_et"),
             result.get("home_score_pen"), result.get("away_score_pen"),
             result.get("match_duration"), result.get("match_winner") if isinstance(result.get("match_winner"), str) else None,
             mid),
        )
        log.info(
            "refresh_results: match %s → %s reg=%s-%s et=%s-%s pen=%s-%s dur=%s (src=%s)",
            mid, result["status"],
            result.get("home_score_regular"), result.get("away_score_regular"),
            result.get("home_score_et"), result.get("away_score_et"),
            result.get("home_score_pen"), result.get("away_score_pen"),
            result.get("match_duration"),
            result.get("source", "?"),
        )
        updated += 1
    log.info("refresh_results: updated=%d failed=%d", updated, failed)
    return {"updated": updated, "failed": failed}


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------

def scrape_odds(days_ahead: int = 2) -> int:
    """Fetch odds for all upcoming target-league matches.

    Uses the existing odds_fetcher, which:
      - hits The Odds API per sport_key
      - persists snapshots to odds_history
      - returns match_id -> rows
    """
    tz = pytz.timezone(settings.TIMEZONE)
    today = datetime.now(tz).date()

    # Build a flat list of fixture dicts the way fetch_odds_for_today expects
    fixtures: list[dict] = []
    for offset in range(days_ahead + 1):
        day = today + timedelta(days=offset)
        day_dt = datetime.combine(day, datetime.min.time())
        try:
            day_fx = get_fixtures_by_date(day_dt)
            for fx in day_fx:
                league_id = (fx.get("league") or {}).get("id")
                if league_id in settings.TARGET_LEAGUES:
                    fixtures.append(fx)
        except Exception as exc:
            log.warning("scrape_odds: load fixtures %s failed: %s", day, exc)

    if not fixtures:
        log.info("scrape_odds: no fixtures to fetch odds for")
        return 0

    log.info("scrape_odds: fetching odds for %d fixtures", len(fixtures))
    odds_by_match = fetch_odds_for_today(fixtures)
    log.info("scrape_odds: persisted odds for %d matches", len(odds_by_match))
    return len(odds_by_match)


# ---------------------------------------------------------------------------
# Master entry point
# ---------------------------------------------------------------------------

def scrape_all(days_ahead: int = 2) -> dict[str, Any]:
    """Run a full scrape cycle. Returns a summary dict."""
    log.info("=" * 60)
    log.info("SCRAPE CYCLE START")
    log.info("=" * 60)
    summary: dict[str, Any] = {}
    summary["fixtures"] = scrape_fixtures(days_ahead=days_ahead)
    summary["results"] = refresh_results()
    summary["odds_matches"] = scrape_odds(days_ahead=days_ahead)
    log.info("=" * 60)
    log.info("SCRAPE CYCLE DONE: %s", summary)
    log.info("=" * 60)
    return summary
