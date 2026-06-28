"""Feature 11: Individual player data & form.

This is partly informed by API-Football's lineup/player stats and partly
by injury weighting. We're using a simple proxy: the importance of absent
players + line-up availability.
"""
from __future__ import annotations

from typing import Any

from betbot.data.api_football import get_fixture_lineups
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.features.injuries import InjuryFeature
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class PlayersFeature(Feature):
    name = "players"
    weight = 0.03

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        match_id = match.get("match_id")
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        if not match_id:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no match_id"}, missing=True)

        try:
            lineups = get_fixture_lineups(match_id)
        except Exception as exc:
            log.warning("Lineups fetch failed for %s: %s", match_id, exc)
            lineups = []

        home_quality = away_quality = 0.0
        home_n = away_n = 0
        team_id_map = {home_id: "home", away_id: "away"}
        quality_map = {"home": 0.0, "away": 0.0, "home_n": 0, "away_n": 0}

        for team_lineup in lineups:
            team = team_lineup.get("team", {}) or {}
            tid = team.get("id")
            side = team_id_map.get(tid)
            if not side:
                continue
            for player in team_lineup.get("startXI", []) or []:
                p_info = player.get("player", {}) or {}
                rating = p_info.get("rating")
                if rating is None:
                    continue
                try:
                    quality_map[side] += float(rating)
                    quality_map[f"{side}_n"] += 1
                except (TypeError, ValueError):
                    continue

        if quality_map["home_n"]:
            home_quality = quality_map["home"] / quality_map["home_n"]
        if quality_map["away_n"]:
            away_quality = quality_map["away"] / quality_map["away_n"]

        if home_quality == 0 and away_quality == 0:
            # Fallback to injury-based signal
            inj_feature = InjuryFeature()
            inj_result = inj_feature.compute(match)
            if inj_result.raw.get("home_penalty", 0) or inj_result.raw.get("away_penalty", 0):
                return FeatureResult(
                    delta=inj_result.delta,
                    confidence=inj_result.confidence * 0.8,
                    raw={"source": "injuries_fallback", **inj_result.raw},
                )
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no lineups"}, missing=True)

        # Rating difference: 0.5 rating ≈ 2pp shift toward that team
        diff = home_quality - away_quality
        shift = max(-0.06, min(0.06, diff * 0.04))
        delta = (shift / 2, 0.0, -shift / 2)

        from betbot.features.base import normalize_delta
        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.7 if lineups else 0.0,
            raw={
                "home_quality": round(home_quality, 2),
                "away_quality": round(away_quality, 2),
                "home_xi_count": quality_map["home_n"],
                "away_xi_count": quality_map["away_n"],
            },
        )
