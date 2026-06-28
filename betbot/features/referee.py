"""Feature 9: Referee style analysis."""
from __future__ import annotations

import json
from typing import Any

from betbot.data.api_football import get_fixture_referee_stats
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class RefereeFeature(Feature):
    name = "referee"
    weight = 0.03

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        referee = match.get("referee")
        if not referee:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no referee assigned"}, missing=True)

        # Try to find referee ID — API-Football returns referee as a name; for now
        # we approximate using name keyword (fouls-heavy referees known by reputation).
        # A more robust approach: maintain a referee name → stats table.
        ref_stats = _lookup_referee_by_name(referee)
        if not ref_stats:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"referee": referee, "reason": "unknown ref"}, missing=True)

        # High-card referees correlate with slightly more under/draw outcomes
        cards_per_game = ref_stats.get("yellow_cards_per_match", 0)
        penalties_per_game = ref_stats.get("penalties_per_match", 0)
        fouls_per_game = ref_stats.get("fouls_per_match", 0)

        shift = 0.0
        if cards_per_game > 4.5:
            shift = 0.005  # slight under/draw bias
        if fouls_per_game > 25:
            shift += 0.005
        # Higher penalties → slightly higher chance favorite scores
        if penalties_per_game > 0.30:
            shift -= 0.003

        delta = (-shift / 2, shift, -shift / 2)
        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.5,
            raw={
                "referee": referee,
                "cards_per_match": cards_per_game,
                "penalties_per_match": penalties_per_game,
                "fouls_per_match": fouls_per_game,
            },
        )


# ----------------------------------------------------------------------------
# Referee database (manual seed list, in production would be populated from API)
# This is a small curated set; we'll grow it over time.
# ----------------------------------------------------------------------------
_REFEREE_DATABASE: dict[str, dict[str, float]] = {
    # name (lowercase): stats
    "anthony taylor": {"yellow_cards_per_match": 3.8, "penalties_per_match": 0.28, "fouls_per_match": 22.1},
    "michael oliver": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.32, "fouls_per_match": 23.4},
    "martin atkinson": {"yellow_cards_per_match": 3.5, "penalties_per_match": 0.25, "fouls_per_match": 21.0},
    "andrew madley": {"yellow_cards_per_match": 4.5, "penalties_per_match": 0.22, "fouls_per_match": 24.0},
    "simon marciniak": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.30, "fouls_per_match": 22.5},
    "daniel orsato": {"yellow_cards_per_match": 4.7, "penalties_per_match": 0.35, "fouls_per_match": 24.5},
    "felix zwayer": {"yellow_cards_per_match": 3.6, "penalties_per_match": 0.27, "fouls_per_match": 21.5},
    "szymon marciniak": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.30, "fouls_per_match": 22.5},
    "antonio mateu lahoz": {"yellow_cards_per_match": 5.5, "penalties_per_match": 0.40, "fouls_per_match": 26.0},
    "cesar ramos": {"yellow_cards_per_match": 4.8, "penalties_per_match": 0.33, "fouls_per_match": 24.0},
}


def _lookup_referee_by_name(name: str) -> dict[str, float] | None:
    name_l = name.strip().lower()
    # Try exact match
    if name_l in _REFEREE_DATABASE:
        return _REFEREE_DATABASE[name_l]
    # Try partial match (last name only)
    last_name = name_l.split()[-1] if name_l else ""
    for db_name, stats in _REFEREE_DATABASE.items():
        if last_name and last_name == db_name.split()[-1]:
            return stats
    return None


def add_referee_stats(name: str, **stats) -> None:
    """Programmatically add/override referee stats."""
    _REFEREE_DATABASE[name.strip().lower()] = stats
