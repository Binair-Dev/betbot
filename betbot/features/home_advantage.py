"""Feature 3: Home advantage.

A small but consistent boost to home win/draw probability. Magnitude varies
by league — derived from historical home-win rates.
"""
from __future__ import annotations

from typing import Any

from betbot.features.base import Feature, FeatureResult, normalize_delta

# Approximate home advantage shift (probability points) by league
LEAGUE_HOME_BOOST: dict[int, float] = {
    39: 0.04,   # Premier League
    40: 0.04,   # Championship
    61: 0.05,   # Ligue 1
    62: 0.05,   # Ligue 2
    78: 0.05,   # Bundesliga
    79: 0.05,
    135: 0.06,  # Serie A — strong home factor
    136: 0.06,
    140: 0.05,  # La Liga
    141: 0.05,
    88: 0.04,   # Eredivisie
    94: 0.05,   # Liga Portugal
    144: 0.04,  # Jupiler Pro League
    2: 0.03,    # UCL (neutral-like but home is real)
    3: 0.03,    # UEL
    848: 0.03,
    5: 0.02,    # Nations League (often neutral)
    10: 0.01,   # Friendlies (neutral)
    1: 0.02,    # World Cup
    4: 0.02,    # Euro
}


class HomeAdvantageFeature(Feature):
    name = "home_advantage"
    weight = 0.0  # Implicitly included in Elo via HOME_ADVANTAGE_ELO; here it's a small bonus

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        league_id = match.get("league_id")
        boost = LEAGUE_HOME_BOOST.get(league_id, 0.04)

        # Half the boost goes to home win, half to draw, away loses the boost
        delta = (boost / 2, boost / 2, -boost)
        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.95,
            raw={"league_id": league_id, "boost": boost},
        )
