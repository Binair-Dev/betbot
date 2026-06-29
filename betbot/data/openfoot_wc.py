"""OpenFootball WC 2026 schedule — venue lookup for matches missing stadium data."""
from __future__ import annotations

from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get_session
from betbot.logging_setup import get_logger

log = get_logger(__name__)

_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
_CACHE_KEY = "openfoot:wc2026:matches"

# ground (city label) → (lat, lon)
GROUND_COORDS: dict[str, tuple[float, float]] = {
    "Vancouver": (49.277, -123.112),
    "Seattle": (47.595, -122.332),
    "San Francisco Bay Area (Santa Clara)": (37.403, -121.970),
    "Los Angeles (Inglewood)": (33.953, -118.339),
    "Guadalajara (Zapopan)": (20.682, -103.462),
    "Mexico City": (19.303, -99.151),
    "Monterrey (Guadalupe)": (25.669, -100.244),
    "Houston": (29.685, -95.411),
    "Dallas (Arlington)": (32.748, -97.093),
    "Kansas City": (39.049, -94.484),
    "Atlanta": (33.756, -84.401),
    "Miami (Miami Gardens)": (25.958, -80.239),
    "Toronto": (43.633, -79.419),
    "Boston (Foxborough)": (42.091, -71.264),
    "Philadelphia": (39.901, -75.168),
    "New York/New Jersey (East Rutherford)": (40.814, -74.074),
}


def _load_matches() -> list[dict]:
    cached = cache_get(_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        resp = get_session().get(_URL, timeout=10)
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        cache_set(_CACHE_KEY, "openfoot_wc", matches, ttl_seconds=86400)
        return matches
    except Exception as exc:
        log.warning("OpenFootball WC fetch failed: %s", exc)
        return []


def get_match_ground(match_date: str, home: str, away: str) -> str | None:
    """Return ground (city label) for a WC match by date + team names."""
    date_str = str(match_date)[:10]
    home_l = home.lower()
    away_l = away.lower()
    for m in _load_matches():
        if m.get("date") != date_str:
            continue
        t1 = m.get("team1", "").lower()
        t2 = m.get("team2", "").lower()
        if (home_l in t1 or t1 in home_l) and (away_l in t2 or t2 in away_l):
            return m.get("ground")
    return None


def get_match_coords(match_date: str, home: str, away: str) -> tuple[float, float] | None:
    """Return (lat, lon) for a WC match by date + team names."""
    ground = get_match_ground(match_date, home, away)
    if not ground:
        return None
    return GROUND_COORDS.get(ground)
