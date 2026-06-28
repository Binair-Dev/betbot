"""Feature 12: Set pieces proportion.

Teams that score/concede a high % of their goals from set pieces are more
predictable. This signal is weak; we use it to slightly bias low-scoring games.
"""
from __future__ import annotations

from typing import Any

from betbot.data.api_football import get_team_statistics
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class SetPiecesFeature(Feature):
    name = "setpieces"
    weight = 0.0  # informational

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")
        season = match.get("season")

        home_sp_share = _setpiece_share(home_id, league_id, season)
        away_sp_share = _setpiece_share(away_id, league_id, season)

        if home_sp_share is None and away_sp_share is None:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no data"}, missing=True)

        # If both teams heavily depend on set pieces, expect more draws (less open play)
        avg = 0.0
        n = 0
        if home_sp_share is not None:
            avg += home_sp_share
            n += 1
        if away_sp_share is not None:
            avg += away_sp_share
            n += 1
        avg /= n

        delta = (0.0, 0.0, 0.0)
        if avg > 0.40:  # 40%+ of goals from set pieces
            delta = (-0.01, 0.02, -0.01)
        elif avg < 0.20:
            delta = (0.005, -0.01, 0.005)

        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.3,
            raw={
                "home_sp_share": home_sp_share,
                "away_sp_share": away_sp_share,
            },
        )


def _setpiece_share(team_id: int | None, league_id: int | None, season: int | None) -> float | None:
    """Estimate set-piece share of goals from API-Football team statistics."""
    if not (team_id and league_id and season):
        return None
    try:
        stats = get_team_statistics(team_id, league_id, season)
    except Exception as exc:
        log.warning("Team stats fetch failed: %s", exc)
        return None
    if not stats:
        return None

    # Try multiple paths in the API response
    goals = stats.get("goals", {}) or {}
    # In some versions of API-Football, set pieces data lives under
    # `goals.for.goal_distribution` or `goals.against.goal_distribution`
    for key in ("for", "against"):
        side = goals.get(key, {}) or {}
        distribution = side.get("goal_distribution") or {}
        if distribution:
            sp = sum(v for k, v in distribution.items() if "set" in k.lower() or "free" in k.lower())
            total = sum(distribution.values())
            if total > 0:
                return sp / total
    return None
