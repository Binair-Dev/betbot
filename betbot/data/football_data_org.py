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
    """Fixtures for a date, in API-Football-compatible format.

    Queries per-competition endpoints because the generic /matches endpoint
    does not return tournament matches (WC, EC, etc.) on the free tier.
    """
    date_str = date.strftime("%Y-%m-%d")
    cache_key = f"fdo:fixtures:{date_str}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    results: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    params = {"dateFrom": date_str, "dateTo": date_str}

    for code, league_id in _CODE_TO_LEAGUE.items():
        if league_id not in settings.TARGET_LEAGUES:
            continue
        data = _get(f"/competitions/{code}/matches", params)
        if not data:
            continue
        for m in data.get("matches", []):
            fx = _normalize(m)
            if fx and fx["fixture"]["id"] not in seen_ids:
                seen_ids.add(fx["fixture"]["id"])
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
    reg = m.get("score", {}).get("regularTime", {}) or {}
    et = m.get("score", {}).get("extraTime", {}) or {}
    pen = m.get("score", {}).get("penalties", {}) or {}
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
        "score": {
            "halftime": {"home": ht.get("home"), "away": ht.get("away")},
            "regular": {"home": reg.get("home"), "away": reg.get("away")},
            "extratime": {"home": et.get("home"), "away": et.get("away")},
            "penalty": {"home": pen.get("home"), "away": pen.get("away")},
        },
        "_score_duration": m.get("score", {}).get("duration"),
        "_score_winner": m.get("score", {}).get("winner"),
        "_source": "football_data_org",
    }


def refresh_match_result(match_id: int) -> dict[str, Any] | None:
    """Fetch current status + score for a match. Short-TTL for settlement use.

    Returns a dict that includes the FULL score breakdown:
    - regular (90-min score — used for 1X2 / O-U / BTTS markets)
    - extratime (goals in ET)
    - penalty (shootout score)
    - duration (REGULAR / EXTRA_TIME / PENALTY_SHOOTOUT)
    - winner (HOME_TEAM / AWAY_TEAM / DRAW — final, includes penalties)
    """
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

    sc = m.get("score", {}) or {}
    ft = sc.get("fullTime", {}) or {}
    ht = sc.get("halfTime", {}) or {}
    reg = sc.get("regularTime", {}) or {}
    et = sc.get("extraTime", {}) or {}
    pen = sc.get("penalties", {}) or {}
    status_raw = m.get("status", "")
    duration = sc.get("duration")  # REGULAR / EXTRA_TIME / PENALTY_SHOOTOUT
    # For FINISHED league games duration is "REGULAR"; for WC knockouts it can be "PENALTY_SHOOTOUT"
    # regularTime can be null when status was TIMED/SCHEDULED — fall back to fullTime
    reg_home = reg.get("home") if reg.get("home") is not None else ft.get("home")
    reg_away = reg.get("away") if reg.get("away") is not None else ft.get("away")
    et_home = et.get("home") or 0
    et_away = et.get("away") or 0
    pen_home = pen.get("home") or 0
    pen_away = pen.get("away") or 0
    if duration is None:
        duration = "PENALTY_SHOOTOUT" if (pen_home or pen_away) else (
            "EXTRA_TIME" if (et_home or et_away) else "REGULAR"
        )
    result = {
        "match_id": m["id"],
        "status": _STATUS_MAP.get(status_raw, status_raw),
        # Legacy fields (full-time incl. ET goals, NO penalties)
        "home_score": ft.get("home"),
        "away_score": ft.get("away"),
        "home_ht_score": ht.get("home"),
        "away_ht_score": ht.get("away"),
        # Breakdown — used by settlement for 90-min markets
        "home_score_regular": reg_home,
        "away_score_regular": reg_away,
        "home_score_et": et_home,
        "away_score_et": et_away,
        "home_score_pen": pen_home,
        "away_score_pen": pen_away,
        "match_duration": duration,
        "match_winner": sc.get("winner"),
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
