"""Feature 8: Weather + pitch conditions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from betbot.data.weather import get_forecast_at_time, get_stadium_coords
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class ConditionsFeature(Feature):
    name = "conditions"
    weight = 0.03

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        venue = match.get("venue")
        match_date = match.get("match_date")
        if not venue or not match_date:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no venue/date"}, missing=True)

        coords = get_stadium_coords(venue)
        if not coords:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "unknown venue", "venue": venue}, missing=True)

        lat, lon = coords
        if isinstance(match_date, str):
            try:
                match_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            except ValueError:
                return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                     raw={"reason": "bad date"}, missing=True)

        weather = get_forecast_at_time(lat, lon, match_date)
        if not weather:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no weather data"}, missing=True)

        # Extract weather params
        main = weather.get("main", {}) or {}
        wind = weather.get("wind", {}) or {}
        rain = weather.get("rain", {}) or {}
        weather_main = (weather.get("weather") or [{}])[0].get("main", "").lower()

        temp = main.get("temp", 20)
        wind_speed = wind.get("speed", 0)
        rain_3h = rain.get("3h", 0)
        is_bad = (
            weather_main in ("rain", "snow", "thunderstorm") or
            wind_speed > 8 or  # ~30 km/h
            rain_3h > 5 or
            temp < 2
        )

        # Bad weather: more draws, fewer goals → slight bias toward draw
        if is_bad:
            delta = (-0.01, 0.02, -0.01)
        else:
            delta = (0.0, 0.0, 0.0)

        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.6 if weather else 0.0,
            raw={
                "temp": temp, "wind_speed": wind_speed,
                "rain_3h": rain_3h, "weather_main": weather_main,
                "is_bad": is_bad,
            },
        )
