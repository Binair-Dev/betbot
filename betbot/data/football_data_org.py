"""Data adapter for football-data.org v4 API (free tier).

Covers current season for: PL, ELC, FL1, BL1, SA, PD, DED, PPL, CL, WC, EC.
Rate limit: 10 req/min. Returns fixtures in API-Football-compatible format.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from betbot.config import settings
from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get_session
from betbot.logging_setup import get_logger

log = get_logger(__name__)

_BASE = "https://api.football-data.org/v4"

_CODE_TO_LEAGUE: dict[str, int] = {
    "PL":  39,    # Premier League
    "ELC": 40,    # Championship
    "FL1": 61,    # Ligue 1
    "BL1": 78,    # Bundesliga
    "SA":  135,   # Serie A
    "PD":  140,   # La Liga
    "DED": 88,    # Eredivisie
    "PPL": 94,    # Liga Portugal
    "CL":  2,     # Champions League
    "WC":  1,     # World Cup
    "EC":  4,     # Euro Championship
    "EL":  3,     # Europa League
    "CONF": 848,  # Conference League
}

_STATUS_MAP: dict[str, str] = {
    "SCHEDULED": "NS", "TIMED": "NS", "IN_PLAY": "1H",
    "PAUSED": "HT", "FINISHED": "FT", "CANCELLED": "CANC",
    "POSTPONED": "PST", "SUSPENDED": "SUSP",
}


def _headers() -> dict[str, str]:
    return {"X-Auth-Token": settings.FOOTBALL_DATA_ORG_KEY}


def _get(path: str, params: dict | None = None) -> dict[str, Any] | None:
    if not settings.FOOTBALL_DATA_ORG_KEY:
        return None
    try:
        resp = get_session().get(
            f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=15
        )
        if resp.status_code == 429:
            log.warning("football-data.org rate limit hit")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("football-data.org %s: %s", path, exc)
        return None


def get_fixtures_by_date(date: datetime) -> list[dict[str, Any]]:
    """Fixtures for a date, in API-Football-compatible format."""
    date_str = date.strftime("%Y-%m-%d")
    cache_key = f"fdo:fixtures:{date_str}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("/matches", {"dateFrom": date_str, "dateTo": date_str})
    if not data:
        cache_set(cache_key, "fdo_fixtures", [], ttl_seconds=1800)
        return []

    results: list[dict[str, Any]] = []
    for m in data.get("matches", []):
        fx = _normalize(m)
        if fx and fx["league"]["id"] in settings.TARGET_LEAGUES:
            results.append(fx)

    cache_set(cache_key, "fdo_fixtures", results, ttl_seconds=3600)
    log.info("football-data.org: %d target fixtures on %s", len(results), date_str)
    return results


def get_team_recent_matches(fdo_team_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Recent finished matches for a team, in API-Football-compatible format."""
    cache_key = f"fdo:team:{fdo_team_id}:last{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get(f"/teams/{fdo_team_id}/matches", {
        "status": "FINISHED",
        "limit": limit,
        "ordering": "DESC",
    })
    if not data:
        cache_set(cache_key, "fdo_team_matches", [], ttl_seconds=3600)
        return []

    results = []
    for m in data.get("matches", []):
        fx = _normalize(m)
        if fx:
            results.append(fx)

    cache_set(cache_key, "fdo_team_matches", results, ttl_seconds=3600)
    return results


def _normalize(m: dict) -> dict[str, Any] | None:
    """Convert football-data.org match → API-Football-compatible dict."""
    comp = m.get("competition", {})
    league_id = _CODE_TO_LEAGUE.get(comp.get("code", ""))
    if not league_id:
        return None

    home = m.get("homeTeam", {})
    away = m.get("awayTeam", {})
    ft = m.get("score", {}).get("fullTime", {})
    ht = m.get("score", {}).get("halfTime", {})
    referees = m.get("referees", [])
    referee = next((r.get("name") for r in referees if r.get("type") == "REFEREE"), None)
    utc_date = m.get("utcDate", "")

    return {
        "fixture": {
            "id": m.get("id"),
            "date": utc_date,
            "referee": referee,
            "venue": {"name": m.get("venue")},
            "status": {"short": _STATUS_MAP.get(m.get("status", ""), "NS")},
        },
        "league": {
            "id": league_id,
            "name": comp.get("name", ""),
            "season": _season(utc_date),
        },
        "teams": {
            "home": {"id": home.get("id"), "name": home.get("name", "")},
            "away": {"id": away.get("id"), "name": away.get("name", "")},
        },
        "goals": {"home": ft.get("home"), "away": ft.get("away")},
        "score": {"halftime": {"home": ht.get("home"), "away": ht.get("away")}},
        "_source": "football_data_org",
    }


def refresh_match_result(match_id: int) -> dict[str, Any] | None:
    """Fetch current status + score for a match. Short-TTL for settlement use."""
    cache_key = f"fdo:match:{match_id}:result"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get(f"/matches/{match_id}")
    if not data:
        return None

    # v4 API wraps in "match" key when fetching single match
    m = data.get("match") or (data if data.get("id") else None)
    if not m:
        return None

    ft = m.get("score", {}).get("fullTime", {})
    ht = m.get("score", {}).get("halfTime", {})
    status_raw = m.get("status", "")
    result = {
        "match_id": m["id"],
        "status": _STATUS_MAP.get(status_raw, status_raw),
        "home_score": ft.get("home"),
        "away_score": ft.get("away"),
        "home_ht_score": ht.get("home"),
        "away_ht_score": ht.get("away"),
    }
    ttl = 3600 if status_raw == "FINISHED" else 120
    cache_set(cache_key, "fdo_match_result", result, ttl_seconds=ttl)
    return result


def _season(utc_date: str) -> int:
    try:
        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        return dt.year if dt.month >= 7 else dt.year - 1
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).year
