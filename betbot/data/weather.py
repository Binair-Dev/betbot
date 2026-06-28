"""OpenWeatherMap client — weather forecasts at stadium locations."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from betbot.config import settings
from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get
from betbot.logging_setup import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.openweathermap.org/data/2.5"


def _params(extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "appid": settings.OPENWEATHER_API_KEY,
        "units": "metric",
        **extra,
    }


def _request(endpoint: str, params: dict[str, Any] | None = None,
             ttl: int = 3600, cache_key: str | None = None) -> Any:
    if not settings.OPENWEATHER_API_KEY:
        log.warning("OPENWEATHER_API_KEY not set — skipping call to %s", endpoint)
        return None

    key = cache_key or f"openweather:{endpoint}:{params}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    url = f"{BASE_URL}/{endpoint}"
    data = get(url, params=_params(params or {}))
    cache_set(key, endpoint, data, ttl_seconds=ttl)
    return data


def get_current_weather(lat: float, lon: float) -> dict | None:
    return _request("weather", params={"lat": lat, "lon": lon}, ttl=1800)


def get_forecast_5d(lat: float, lon: float) -> dict | None:
    """5-day / 3-hour forecast. Used to find conditions around match time."""
    return _request("forecast", params={"lat": lat, "lon": lon}, ttl=1800)


def get_forecast_at_time(lat: float, lon: float, when: datetime,
                         window_hours: int = 3) -> dict | None:
    """Return weather forecast closest to `when` (within ±window_hours)."""
    forecast = get_forecast_5d(lat, lon)
    if not forecast or "list" not in forecast:
        return None
    target_ts = when.timestamp()
    best = None
    best_diff = float("inf")
    for entry in forecast["list"]:
        entry_ts = datetime.utcfromtimestamp(entry["dt"]).timestamp()
        diff = abs(entry_ts - target_ts)
        if diff < best_diff and diff <= window_hours * 3600:
            best = entry
            best_diff = diff
    return best


# ----------------------------------------------------------------------------
# Stadium geocoding — known venues for major leagues
# Note: for simplicity we hardcode a small subset.
# In production we'd pull from a venue database.
# ----------------------------------------------------------------------------

KNOWN_STADIUMS: dict[str, tuple[float, float]] = {
    # England — Premier League
    "Old Trafford": (53.4631, -2.2913),
    "Anfield": (53.4308, -2.9608),
    "Etihad Stadium": (53.4831, -2.2004),
    "Stamford Bridge": (51.4817, -0.1910),
    "Emirates Stadium": (51.5549, -0.1084),
    "Tottenham Hotspur Stadium": (51.6042, -0.0664),
    "London Stadium": (51.5387, -0.0166),
    "St James' Park": (54.9756, -1.6216),
    "Aston Villa Park": (52.5090, -1.8847),
    "Molineux Stadium": (52.5902, -2.1304),
    # Spain
    "Santiago Bernabéu": (40.4530, -3.6883),
    "Camp Nou": (41.3809, 2.1228),
    "Wanda Metropolitano": (40.4362, -3.5995),
    "Mestalla": (39.4744, -0.3581),
    "San Mamés": (43.2642, -2.9494),
    # Germany
    "Allianz Arena": (48.2188, 11.6248),
    "Signal Iduna Park": (51.4926, 7.4518),
    "Veltins-Arena": (51.5546, 7.0675),
    "Mercedes-Benz Arena": (48.7924, 9.2320),
    "Olympiastadion Berlin": (52.5147, 13.2395),
    # Italy
    "San Siro": (45.4781, 9.1240),
    "Stadio Olimpico": (41.9341, 12.4547),
    "Diego Armando Maradona": (40.8280, 14.1930),
    "Allianz Stadium": (45.1096, 7.6412),
    # France
    "Parc des Princes": (48.8414, 2.2530),
    "Stade Vélodrome": (43.2698, 5.3958),
    "Groupama Stadium": (45.7653, 4.9822),
    "Stade Pierre-Mauroy": (50.6127, 3.1307),
    # Netherlands
    "Johan Cruyff Arena": (52.3141, 4.9419),
    "De Kuip": (51.8938, 4.5231),
    # Portugal
    "Estádio da Luz": (38.7527, -9.1847),
    "Estádio do Dragão": (41.1616, -8.5856),
    # Belgium
    "King Baudouin Stadium": (50.8353, 4.3211),
    "Jan Breydel Stadium": (51.1934, 3.1805),
}


def get_stadium_coords(venue_name: str) -> tuple[float, float] | None:
    return KNOWN_STADIUMS.get(venue_name)
