"""API-Football client (via RapidAPI) — fixtures, stats, injuries, referees, standings."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from betbot.config import settings
from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get
from betbot.logging_setup import get_logger

log = get_logger(__name__)

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"


def _headers() -> dict[str, str]:
    return {
        "X-RapidAPI-Key": settings.API_FOOTBALL_KEY,
        "X-RapidAPI-Host": settings.API_FOOTBALL_HOST,
    }


def _request(endpoint: str, params: dict[str, Any] | None = None,
             ttl: int = 3600, cache_key: str | None = None) -> dict[str, Any]:
    if not settings.API_FOOTBALL_KEY:
        log.warning("API_FOOTBALL_KEY not set — skipping call to %s", endpoint)
        return {"response": [], "errors": {"token": "missing"}}

    key = cache_key or f"apifootball:{endpoint}:{params}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    url = f"{BASE_URL}/{endpoint}"
    data = get(url, headers=_headers(), params=params or {})
    cache_set(key, endpoint, data, ttl_seconds=ttl)
    return data


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

def get_fixtures_by_date(date: datetime) -> list[dict]:
    """Return all fixtures for a specific date (UTC)."""
    data = _request(
        "fixtures",
        params={"date": date.strftime("%Y-%m-%d")},
        ttl=1800,
    )
    return data.get("response", []) or []


def get_fixtures_next_24h(from_dt: datetime | None = None) -> list[dict]:
    """Return fixtures scheduled between now and now+24h, filtered to target leagues."""
    from_dt = from_dt or datetime.utcnow()
    to_dt = from_dt + timedelta(hours=24)
    data = _request(
        "fixtures",
        params={
            "from": from_dt.strftime("%Y-%m-%d"),
            "to": to_dt.strftime("%Y-%m-%d"),
        },
        ttl=1800,
    )
    fixtures = data.get("response", []) or []
    target_leagues = set(settings.TARGET_LEAGUES)
    filtered = []
    for fx in fixtures:
        lg = fx.get("league", {}).get("id")
        if lg in target_leagues:
            filtered.append(fx)
    return filtered


def get_fixture_by_id(fixture_id: int) -> dict | None:
    data = _request("fixtures", params={"id": fixture_id}, ttl=3600)
    resp = data.get("response", [])
    return resp[0] if resp else None


def get_fixtures_by_league_season(league_id: int, season: int, last_n: int | None = None) -> list[dict]:
    params: dict[str, Any] = {"league": league_id, "season": season}
    data = _request("fixtures", params=params, ttl=86400)
    fixtures = data.get("response", []) or []
    if last_n is not None:
        fixtures = sorted(
            fixtures, key=lambda f: f.get("fixture", {}).get("date", ""), reverse=True
        )[:last_n]
    return fixtures


# ----------------------------------------------------------------------------
# Standings
# ----------------------------------------------------------------------------

def get_standings(league_id: int, season: int) -> list[dict]:
    data = _request(
        "standings",
        params={"league": league_id, "season": season},
        ttl=86400,
    )
    resp = data.get("response", [])
    if not resp:
        return []
    league_data = resp[0].get("league", {})
    standings_groups = league_data.get("standings", [])
    if not standings_groups:
        return []
    return standings_groups[0]


# ----------------------------------------------------------------------------
# Team statistics
# ----------------------------------------------------------------------------

def get_team_statistics(team_id: int, league_id: int, season: int) -> dict | None:
    data = _request(
        "teams/statistics",
        params={"team": team_id, "league": league_id, "season": season},
        ttl=86400,
    )
    resp = data.get("response", [])
    return resp[0] if resp else None


def get_team_last_fixtures(team_id: int, last_n: int = 10, league_id: int | None = None,
                           season: int | None = None) -> list[dict]:
    """Return last N finished fixtures for a team, optionally filtered by league."""
    params: dict[str, Any] = {"team": team_id, "last": last_n}
    if league_id:
        params["league"] = league_id
    if season:
        params["season"] = season
    data = _request("fixtures", params=params, ttl=86400)
    fixtures = data.get("response", []) or []
    return [f for f in fixtures if f.get("fixture", {}).get("status", {}).get("short") == "FT"]


# ----------------------------------------------------------------------------
# Injuries
# ----------------------------------------------------------------------------

def get_injuries_for_fixture(fixture_id: int) -> list[dict]:
    data = _request("injuries", params={"fixture": fixture_id}, ttl=1800)
    return data.get("response", []) or []


def get_injuries_for_team(team_id: int, league_id: int | None = None,
                          season: int | None = None) -> list[dict]:
    params: dict[str, Any] = {"team": team_id}
    if league_id:
        params["league"] = league_id
    if season:
        params["season"] = season
    data = _request("injuries", params=params, ttl=3600)
    return data.get("response", []) or []


# ----------------------------------------------------------------------------
# Referees
# ----------------------------------------------------------------------------

def get_fixture_referee_stats(referee_id: int, season: int | None = None) -> dict | None:
    params: dict[str, Any] = {"id": referee_id}
    if season:
        params["season"] = season
    data = _request("referees", params=params, ttl=86400)
    resp = data.get("response", [])
    return resp[0] if resp else None


# ----------------------------------------------------------------------------
# H2H
# ----------------------------------------------------------------------------

def get_h2h(team_a_id: int, team_b_id: int, last_n: int = 10) -> list[dict]:
    data = _request("fixtures/headtohead", params={"h2h": f"{team_a_id}-{team_b_id}", "last": last_n},
                    ttl=86400)
    return data.get("response", []) or []


# ----------------------------------------------------------------------------
# Fixture events / lineups / stats (per fixture)
# ----------------------------------------------------------------------------

def get_fixture_events(fixture_id: int) -> list[dict]:
    data = _request("fixtures/events", params={"fixture": fixture_id}, ttl=3600)
    return data.get("response", []) or []


def get_fixture_lineups(fixture_id: int) -> list[dict]:
    data = _request("fixtures/lineups", params={"fixture": fixture_id}, ttl=3600)
    return data.get("response", []) or []


def get_fixture_statistics(fixture_id: int) -> list[dict]:
    data = _request("fixtures/statistics", params={"fixture": fixture_id}, ttl=3600)
    return data.get("response", []) or []


# ----------------------------------------------------------------------------
# Predictions (bookmaker-provided, baseline)
# ----------------------------------------------------------------------------

def get_fixture_predictions(fixture_id: int) -> dict | None:
    data = _request("predictions", params={"fixture": fixture_id}, ttl=3600)
    resp = data.get("response", [])
    return resp[0] if resp else None


# ----------------------------------------------------------------------------
# Leagues & Teams metadata
# ----------------------------------------------------------------------------

def get_leagues(country: str | None = None, season: int | None = None) -> list[dict]:
    params: dict[str, Any] = {}
    if country:
        params["country"] = country
    if season:
        params["season"] = season
    data = _request("leagues", params=params, ttl=604800)
    return data.get("response", []) or []


def get_teams_by_league(league_id: int, season: int) -> list[dict]:
    data = _request("teams", params={"league": league_id, "season": season}, ttl=604800)
    return data.get("response", []) or []
