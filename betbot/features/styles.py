"""Feature 6: H2H and playing styles.

Less predictive than commonly thought, but some styles structurally
trouble others (low block vs possession team, etc.).
"""
from __future__ import annotations

from typing import Any

from betbot.data.api_football import get_h2h
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class StylesFeature(Feature):
    name = "styles"
    weight = 0.0  # Not in the top features; informational only

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        if not (home_id and away_id):
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no team ids"}, missing=True)

        try:
            h2h_fixtures = get_h2h(home_id, away_id, last_n=10)
        except Exception as exc:
            log.warning("H2H fetch failed for %s vs %s: %s", home_id, away_id, exc)
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"error": str(exc)}, missing=True)

        if not h2h_fixtures:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no H2H data"}, missing=True)

        # Compute home/away/draw rates in H2H
        home_wins = away_wins = draws = 0
        for fx in h2h_fixtures:
            teams = fx.get("teams", {}) or {}
            goals = fx.get("goals", {}) or {}
            if teams.get("home", {}).get("id") == home_id:
                hg = goals.get("home") or 0
                ag = goals.get("away") or 0
            else:
                hg = goals.get("away") or 0
                ag = goals.get("home") or 0
            if hg > ag:
                home_wins += 1
            elif hg < ag:
                away_wins += 1
            else:
                draws += 1

        n = home_wins + away_wins + draws
        if n == 0:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no H2H data"}, missing=True)

        home_rate = home_wins / n
        away_rate = away_wins / n
        draw_rate = draws / n

        # Compare to uniform 1/3 baseline; weight limited since H2H is weak signal
        shift_home = (home_rate - 1/3) * 0.04
        shift_away = (away_rate - 1/3) * 0.04
        shift_draw = (draw_rate - 1/3) * 0.04

        delta = (shift_home, shift_draw, shift_away)
        delta = normalize_delta(delta)

        confidence = 0.4 if n >= 5 else 0.2

        return FeatureResult(
            delta=delta,
            confidence=confidence,
            raw={
                "n": n, "home_wins": home_wins,
                "away_wins": away_wins, "draws": draws,
                "home_rate": round(home_rate, 3),
                "away_rate": round(away_rate, 3),
                "draw_rate": round(draw_rate, 3),
            },
        )
