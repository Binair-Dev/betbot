"""Backfill module — fetch historical data for backtest."""
from __future__ import annotations

from datetime import datetime, timedelta

from betbot.config import settings
from betbot.data.api_football import (
    get_fixtures_by_date,
    get_fixtures_by_league_season,
)
from betbot.data.odds_api import get_scores, find_soccer_keys
from betbot.data.understat import get_league_season_data
from betbot.db.repository import execute, query_one
from betbot.logging_setup import get_logger

log = get_logger(__name__)


def backfill_fixtures(start_date: datetime, end_date: datetime) -> int:
    """Backfill fixture data day-by-day from API-Football.

    Returns count of fixtures inserted/updated.
    """
    current = start_date
    count = 0
    while current <= end_date:
        try:
            fixtures = get_fixtures_by_date(current)
            for fx in fixtures:
                league_id = fx.get("league", {}).get("id")
                if league_id not in settings.TARGET_LEAGUES:
                    continue
                _upsert_fixture(fx)
                count += 1
        except Exception as exc:
            log.warning("Backfill %s failed: %s", current.date(), exc)
        current += timedelta(days=1)
    log.info("Backfilled %d fixtures from %s to %s",
             count, start_date.date(), end_date.date())
    return count


def backfill_understat_for_season(season: int) -> int:
    """Pull Understat team-level xG for the 5 main leagues of a given season."""
    leagues = {
        "EPL": "EPL",
        "La_liga": "La_liga",
        "Bundesliga": "Bundesliga",
        "Serie_A": "Serie_A",
        "Ligue_1": "Ligue_1",
    }
    count = 0
    for league_key in leagues:
        try:
            teams = get_league_season_data(league_key, season)
            for t in teams:
                # The Understat team_id is not the same as API-Football's. We store
                # by name. We'll cross-reference later in features/form.py.
                _upsert_team_xg(t, season)
                count += 1
        except Exception as exc:
            log.warning("Understat backfill %s %s failed: %s", league_key, season, exc)
    log.info("Backfilled %d team xG records for season %d", count, season)
    return count


def _upsert_fixture(fx: dict) -> None:
    fixture = fx.get("fixture", {})
    league = fx.get("league", {})
    teams = fx.get("teams", {})
    goals = fx.get("goals", {})
    score = fx.get("score", {})
    status = fixture.get("status", {})

    match_id = fixture.get("id")
    if not match_id:
        return

    home = teams.get("home", {}) or {}
    away = teams.get("away", {}) or {}

    sql = """
        INSERT INTO matches (match_id, league_id, season, match_date,
                             home_team_id, away_team_id, venue, referee,
                             status, home_score, away_score,
                             home_ht_score, away_ht_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id) DO UPDATE SET
            league_id=excluded.league_id,
            season=excluded.season,
            match_date=excluded.match_date,
            home_team_id=excluded.home_team_id,
            away_team_id=excluded.away_team_id,
            venue=excluded.venue,
            referee=excluded.referee,
            status=excluded.status,
            home_score=excluded.home_score,
            away_score=excluded.away_score,
            home_ht_score=excluded.home_ht_score,
            away_ht_score=excluded.away_ht_score,
            updated_at=CURRENT_TIMESTAMP
    """
    execute(sql, (
        match_id,
        league.get("id"),
        league.get("season"),
        fixture.get("date"),
        home.get("id"),
        away.get("id"),
        fixture.get("venue", {}).get("name"),
        fixture.get("referee"),
        status.get("short"),
        goals.get("home"),
        goals.get("away"),
        (score.get("halftime") or {}).get("home"),
        (score.get("halftime") or {}).get("away"),
    ))

    if home.get("id"):
        execute(
            """INSERT INTO teams (team_id, name, country, logo_url)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_id) DO UPDATE SET
                   name=excluded.name,
                   country=excluded.country,
                   logo_url=excluded.logo_url""",
            (home["id"], home.get("name"), home.get("country"), home.get("logo")),
        )
    if away.get("id"):
        execute(
            """INSERT INTO teams (team_id, name, country, logo_url)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_id) DO UPDATE SET
                   name=excluded.name,
                   country=excluded.country,
                   logo_url=excluded.logo_url""",
            (away["id"], away.get("name"), away.get("country"), away.get("logo")),
        )


def _upsert_team_xg(team_xg: dict, season: int) -> None:
    """Persist Understat team xG stats to a dedicated cache table.

    Note: We use a JSON-blob cache since Understat team_id != API-Football team_id.
    Cross-reference happens by team name.
    """
    import json
    key = f"understat_team_{team_xg['league']}_{season}_{team_xg['team']}"
    payload = json.dumps(team_xg)
    execute(
        """INSERT INTO api_cache (cache_key, endpoint, response_json, ttl_seconds, expires_at)
           VALUES (?, ?, ?, ?, datetime('now', '+30 days'))
           ON CONFLICT(cache_key) DO UPDATE SET
               response_json=excluded.response_json,
               fetched_at=CURRENT_TIMESTAMP,
               expires_at=datetime('now', '+30 days')""",
        (key, "understat_team_xg", payload, 30 * 86400),
    )


def get_team_xg_by_name(team_name: str, season: int) -> dict | None:
    """Look up Understat team xG by team name and season."""
    import json
    keys = [
        f"understat_team_EPL_{season}_{team_name}",
        f"understat_team_La_liga_{season}_{team_name}",
        f"understat_team_Bundesliga_{season}_{team_name}",
        f"understat_team_Serie_A_{season}_{team_name}",
        f"understat_team_Ligue_1_{season}_{team_name}",
    ]
    for key in keys:
        row = query_one("SELECT response_json FROM api_cache WHERE cache_key = ?", (key,))
        if row and row["response_json"]:
            try:
                return json.loads(row["response_json"])
            except (TypeError, ValueError):
                continue
    return None
