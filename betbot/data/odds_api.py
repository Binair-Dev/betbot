"""The Odds API client — multi-bookmaker odds for football."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from betbot.config import settings
from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get
from betbot.logging_setup import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

SUPPORTED_MARKETS = (
    "h2h",              # 1X2 (home/draw/away)
    "h2h_lay",          # 1X2 lay (exchange)
    "spreads",          # handicap
    "totals",           # over/under
    "team_totals",      # team over/under
    "btts",             # both teams to score
    "double_chance",    # 1X / X2 / 12
    "draw_no_bet",      # DNMB
    "alternate_totals", # alternate over/under
    "correct_score",    # score exact
)

SUPPORTED_REGIONS = ("uk", "eu", "us", "au")
DEFAULT_REGION = "eu"

ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"


def _params(extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiKey": settings.ODDS_API_KEY,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
        **extra,
    }


def _request(endpoint: str, params: dict[str, Any] | None = None,
             ttl: int = 1800, cache_key: str | None = None) -> Any:
    if not settings.ODDS_API_KEY:
        log.warning("ODDS_API_KEY not set — skipping call to %s", endpoint)
        return []

    key = cache_key or f"oddsapi:{endpoint}:{params}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    url = f"{BASE_URL}/{endpoint}"
    data = get(url, params=_params(params or {}))
    cache_set(key, endpoint, data, ttl_seconds=ttl)
    return data


# ----------------------------------------------------------------------------
# Sports
# ----------------------------------------------------------------------------

def get_sports() -> list[dict]:
    return _request("sports", ttl=86400) or []


def find_soccer_keys() -> list[str]:
    """Discover all soccer sport_keys (e.g. soccer_epl, soccer_france_ligue_one...)."""
    sports = get_sports()
    return [s["key"] for s in sports if s.get("group") == "Soccer"]


# ----------------------------------------------------------------------------
# Odds
# ----------------------------------------------------------------------------

def get_odds_for_sport(sport_key: str, markets: str = "h2h",
                       regions: str = DEFAULT_REGION,
                       commence_time_from: datetime | None = None,
                       commence_time_to: datetime | None = None,
                       bookmakers: str | None = None) -> list[dict]:
    """Fetch odds for a given sport (league). markets is comma-separated."""
    params: dict[str, Any] = {
        "sport": sport_key,
        "regions": regions,
        "markets": markets,
    }
    if commence_time_from:
        params["commenceTimeFrom"] = commence_time_from.isoformat() + "Z"
    if commence_time_to:
        params["commenceTimeTo"] = commence_time_to.isoformat() + "Z"
    if bookmakers:
        params["bookmakers"] = bookmakers
    return _request("odds", params=params, ttl=1800) or []


def get_event_odds(sport_key: str, event_id: str,
                   markets: str = "h2h,totals,btts,double_chance,correct_score",
                   regions: str = DEFAULT_REGION) -> dict | None:
    """Fetch detailed odds for a single event."""
    params = {"regions": regions, "markets": markets, "dateFormat": DATE_FORMAT}
    result = _request(
        f"sports/{sport_key}/events/{event_id}/odds",
        params=params,
        ttl=600,
    )
    return result if isinstance(result, dict) else None


# ----------------------------------------------------------------------------
# Scores / results (for settlement)
# ----------------------------------------------------------------------------

def get_scores(sport_key: str, days_from: int = 3,
               date_format: str = "iso") -> list[dict]:
    return _request(
        f"sports/{sport_key}/scores",
        params={"daysFrom": days_from, "dateFormat": date_format},
        ttl=1800,
    ) or []
