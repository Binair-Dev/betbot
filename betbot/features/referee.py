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
    # Premier League
    "anthony taylor": {"yellow_cards_per_match": 3.8, "penalties_per_match": 0.28, "fouls_per_match": 22.1},
    "michael oliver": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.32, "fouls_per_match": 23.4},
    "martin atkinson": {"yellow_cards_per_match": 3.5, "penalties_per_match": 0.25, "fouls_per_match": 21.0},
    "andrew madley": {"yellow_cards_per_match": 4.5, "penalties_per_match": 0.22, "fouls_per_match": 24.0},
    "stuart attwell": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.30, "fouls_per_match": 22.5},
    "chris kavanagh": {"yellow_cards_per_match": 4.3, "penalties_per_match": 0.27, "fouls_per_match": 23.0},
    "paul tierney": {"yellow_cards_per_match": 3.9, "penalties_per_match": 0.24, "fouls_per_match": 21.8},
    "darren england": {"yellow_cards_per_match": 4.1, "penalties_per_match": 0.26, "fouls_per_match": 22.3},
    "john brooks": {"yellow_cards_per_match": 3.7, "penalties_per_match": 0.23, "fouls_per_match": 21.5},
    "simon hooper": {"yellow_cards_per_match": 4.4, "penalties_per_match": 0.29, "fouls_per_match": 23.5},
    "robert jones": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.25, "fouls_per_match": 22.0},
    # Ligue 1
    "francois letexier": {"yellow_cards_per_match": 3.5, "penalties_per_match": 0.24, "fouls_per_match": 20.8},
    "clement turpin": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.28, "fouls_per_match": 22.0},
    "benoit bastien": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.26, "fouls_per_match": 22.5},
    "ruddy buquet": {"yellow_cards_per_match": 4.5, "penalties_per_match": 0.30, "fouls_per_match": 23.0},
    "johan hamel": {"yellow_cards_per_match": 4.3, "penalties_per_match": 0.27, "fouls_per_match": 22.8},
    "eric wattellier": {"yellow_cards_per_match": 3.8, "penalties_per_match": 0.22, "fouls_per_match": 21.0},
    "florent batta": {"yellow_cards_per_match": 4.1, "penalties_per_match": 0.25, "fouls_per_match": 22.2},
    # Bundesliga
    "felix zwayer": {"yellow_cards_per_match": 3.6, "penalties_per_match": 0.27, "fouls_per_match": 21.5},
    "tobias stieler": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.25, "fouls_per_match": 22.0},
    "daniel siebert": {"yellow_cards_per_match": 3.9, "penalties_per_match": 0.28, "fouls_per_match": 21.8},
    "benjamin brand": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.26, "fouls_per_match": 22.5},
    "robert schroder": {"yellow_cards_per_match": 3.7, "penalties_per_match": 0.24, "fouls_per_match": 21.2},
    "christian dingert": {"yellow_cards_per_match": 4.1, "penalties_per_match": 0.23, "fouls_per_match": 22.0},
    "sascha stegemann": {"yellow_cards_per_match": 3.8, "penalties_per_match": 0.26, "fouls_per_match": 21.5},
    # Serie A
    "daniele orsato": {"yellow_cards_per_match": 4.7, "penalties_per_match": 0.35, "fouls_per_match": 24.5},
    "daniel orsato": {"yellow_cards_per_match": 4.7, "penalties_per_match": 0.35, "fouls_per_match": 24.5},
    "massimiliano irrati": {"yellow_cards_per_match": 4.5, "penalties_per_match": 0.32, "fouls_per_match": 23.8},
    "marco guida": {"yellow_cards_per_match": 4.3, "penalties_per_match": 0.29, "fouls_per_match": 23.0},
    "paolo valeri": {"yellow_cards_per_match": 4.6, "penalties_per_match": 0.33, "fouls_per_match": 24.0},
    "luca pairetto": {"yellow_cards_per_match": 4.4, "penalties_per_match": 0.31, "fouls_per_match": 23.5},
    "fabrizio doveri": {"yellow_cards_per_match": 4.8, "penalties_per_match": 0.34, "fouls_per_match": 25.0},
    "maurizio mariani": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.28, "fouls_per_match": 22.8},
    # La Liga
    "antonio mateu lahoz": {"yellow_cards_per_match": 5.5, "penalties_per_match": 0.40, "fouls_per_match": 26.0},
    "juan martinez munuera": {"yellow_cards_per_match": 4.8, "penalties_per_match": 0.35, "fouls_per_match": 24.5},
    "jesus gil manzano": {"yellow_cards_per_match": 5.0, "penalties_per_match": 0.38, "fouls_per_match": 25.5},
    "jose maria sanchez martinez": {"yellow_cards_per_match": 4.5, "penalties_per_match": 0.32, "fouls_per_match": 24.0},
    "ricardo de burgos bengoetxea": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.28, "fouls_per_match": 23.0},
    "cesar ramos": {"yellow_cards_per_match": 4.8, "penalties_per_match": 0.33, "fouls_per_match": 24.0},
    "alejandro hernandez hernandez": {"yellow_cards_per_match": 4.4, "penalties_per_match": 0.30, "fouls_per_match": 23.5},
    "guillermo cuadra fernandez": {"yellow_cards_per_match": 4.6, "penalties_per_match": 0.31, "fouls_per_match": 24.2},
    # Eredivisie
    "serdar gozubuyuk": {"yellow_cards_per_match": 3.5, "penalties_per_match": 0.28, "fouls_per_match": 21.0},
    "dennis higler": {"yellow_cards_per_match": 3.8, "penalties_per_match": 0.25, "fouls_per_match": 21.5},
    "bas nijhuis": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.30, "fouls_per_match": 22.0},
    "jochem kamphuis": {"yellow_cards_per_match": 3.6, "penalties_per_match": 0.22, "fouls_per_match": 20.8},
    "pol van boekel": {"yellow_cards_per_match": 3.9, "penalties_per_match": 0.26, "fouls_per_match": 21.5},
    # Liga Portugal
    "artur soares dias": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.29, "fouls_per_match": 22.5},
    "hugo miguel": {"yellow_cards_per_match": 4.3, "penalties_per_match": 0.31, "fouls_per_match": 23.0},
    "manuel mota": {"yellow_cards_per_match": 4.1, "penalties_per_match": 0.27, "fouls_per_match": 22.0},
    "luis godinho": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.28, "fouls_per_match": 22.5},
    # Jupiler Pro League (Belgium)
    "lawrence visser": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.28, "fouls_per_match": 22.0},
    "jonathan lardot": {"yellow_cards_per_match": 3.8, "penalties_per_match": 0.25, "fouls_per_match": 21.5},
    "erik lambrechts": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.30, "fouls_per_match": 22.5},
    "nathan verboomen": {"yellow_cards_per_match": 3.9, "penalties_per_match": 0.27, "fouls_per_match": 22.0},
    # UEFA / International
    "szymon marciniak": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.30, "fouls_per_match": 22.5},
    "simon marciniak": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.30, "fouls_per_match": 22.5},
    "slavko vincic": {"yellow_cards_per_match": 4.2, "penalties_per_match": 0.30, "fouls_per_match": 22.8},
    "istvan kovacs": {"yellow_cards_per_match": 4.0, "penalties_per_match": 0.27, "fouls_per_match": 22.0},
    "carlos del cerro grande": {"yellow_cards_per_match": 4.3, "penalties_per_match": 0.31, "fouls_per_match": 23.2},
    "sandro scharer": {"yellow_cards_per_match": 3.8, "penalties_per_match": 0.26, "fouls_per_match": 21.5},
    "cuneyt cakir": {"yellow_cards_per_match": 4.5, "penalties_per_match": 0.33, "fouls_per_match": 23.5},
    "michael fabbri": {"yellow_cards_per_match": 4.1, "penalties_per_match": 0.28, "fouls_per_match": 22.3},
    "tobias welz": {"yellow_cards_per_match": 3.9, "penalties_per_match": 0.25, "fouls_per_match": 21.8},
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
