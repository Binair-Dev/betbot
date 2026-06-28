"""Feature 4: Injuries & suspensions impact."""
from __future__ import annotations

import json
from typing import Any

from betbot.data.api_football import get_injuries_for_fixture
from betbot.db.repository import execute, query
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class InjuryFeature(Feature):
    name = "injuries"
    weight = 0.12

    POSITION_IMPORTANCE = {
        "Goalkeeper": 1.0,
        "Defender": 0.7,
        "Midfielder": 0.85,
        "Attacker": 0.95,
    }

    REASON_MULTIPLIER = {
        "injury": 1.0,
        "suspension": 0.9,
        "doubt": 0.5,
    }

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        match_id = match.get("match_id")
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        if not match_id:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no match_id"}, missing=True)

        injuries = get_injuries_for_fixture(match_id)
        _persist_injuries(match_id, injuries)

        home_penalty = 0.0
        away_penalty = 0.0
        details: list[dict] = []
        for inj in injuries:
            team_id = inj.get("team", {}).get("id")
            player = inj.get("player", {}) or {}
            reason = (inj.get("reason") or "injury").lower()
            importance = self.POSITION_IMPORTANCE.get(player.get("type", ""), 0.6)
            multiplier = self.REASON_MULTIPLIER.get(reason, 0.8)
            penalty = importance * multiplier

            details.append({
                "team_id": team_id, "player": player.get("name"),
                "position": player.get("type"), "reason": reason,
                "importance": importance, "penalty": penalty,
            })
            if team_id == home_id:
                home_penalty += penalty
            elif team_id == away_id:
                away_penalty += penalty

        # Net advantage: away_penalty - home_penalty (positive = good for home)
        net = away_penalty - home_penalty
        # Scale: 1.0 net penalty ≈ 2.5pp shift
        shift = max(-0.08, min(0.08, net * 0.025))

        delta = (shift / 2, 0.0, -shift / 2)
        delta = normalize_delta(delta)

        confidence = 0.7 if injuries else 0.3

        return FeatureResult(
            delta=delta,
            confidence=confidence,
            raw={
                "home_penalty": round(home_penalty, 3),
                "away_penalty": round(away_penalty, 3),
                "details": details,
            },
        )


def _persist_injuries(match_id: int, injuries: list[dict]) -> None:
    """Store injuries for later reference."""
    execute("DELETE FROM injuries WHERE fixture_id = ?", (match_id,))
    for inj in injuries:
        player = inj.get("player", {}) or {}
        team = inj.get("team", {}) or {}
        execute(
            """INSERT INTO injuries
               (team_id, player_name, player_id, reason, importance,
                expected_return, fixture_id, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                team.get("id"),
                player.get("name"),
                player.get("id"),
                inj.get("reason"),
                0.6,
                None,
                match_id,
                "api_football",
            ),
        )
