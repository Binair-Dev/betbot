"""Feature 2: Elo rating system for football teams."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from betbot.db.repository import execute, query, query_one
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_ELO = 1500.0
HOME_ADVANTAGE_ELO = 100.0  # Elo points added to home team for expected score
K_FACTOR = 20.0


class EloFeature(Feature):
    name = "elo"
    weight = 0.15

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        if not home_id or not away_id:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "missing team_ids"}, missing=True)

        home_elo = _get_team_elo(home_id)
        away_elo = _get_team_elo(away_id)

        # Expected scores
        exp_home = _expected_score(home_elo + HOME_ADVANTAGE_ELO, away_elo)
        exp_away = 1.0 - exp_home
        exp_draw = _draw_probability(home_elo + HOME_ADVANTAGE_ELO, away_elo)

        # Convert expected probabilities to deltas relative to a uniform 1/3-1/3-1/3 baseline
        uniform = 1.0 / 3.0
        delta = (
            (exp_home - uniform) * 0.30,
            (exp_draw - uniform) * 0.30,
            (exp_away - uniform) * 0.30,
        )
        delta = normalize_delta(delta)

        confidence = 0.85 if (home_elo != DEFAULT_ELO and away_elo != DEFAULT_ELO) else 0.4

        return FeatureResult(
            delta=delta,
            confidence=confidence,
            raw={
                "home_elo": round(home_elo, 1),
                "away_elo": round(away_elo, 1),
                "exp_home": round(exp_home, 3),
                "exp_draw": round(exp_draw, 3),
                "exp_away": round(exp_away, 3),
                "elo_diff": round(home_elo - away_elo, 1),
            },
        )


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def _draw_probability(rating_a: float, rating_b: float) -> float:
    """Approximate draw probability based on rating closeness.

    Empirical: draws are most likely when teams are evenly matched.
    Simple bell-curve around 0 difference.
    """
    diff = abs(rating_a - rating_b)
    base = 0.30
    reduction = diff / 800.0
    return max(0.10, base - reduction * 0.15)


def _get_team_elo(team_id: int) -> float:
    row = query_one(
        "SELECT elo FROM teams WHERE team_id = ?",
        (team_id,),
    )
    if row and row["elo"] is not None:
        return float(row["elo"])
    return DEFAULT_ELO


def update_elo_from_match(match_id: int, home_score: int, away_score: int) -> None:
    """Update Elo ratings after a match result."""
    row = query_one(
        "SELECT home_team_id, away_team_id FROM matches WHERE match_id = ?",
        (match_id,),
    )
    if not row:
        return
    home_id = row["home_team_id"]
    away_id = row["away_team_id"]

    home_elo = _get_team_elo(home_id)
    away_elo = _get_team_elo(away_id)

    if home_score > away_score:
        s_home, s_away = 1.0, 0.0
    elif home_score < away_score:
        s_home, s_away = 0.0, 1.0
    else:
        s_home, s_away = 0.5, 0.5

    e_home = _expected_score(home_elo + HOME_ADVANTAGE_ELO, away_elo)
    e_away = 1.0 - e_home

    new_home = home_elo + K_FACTOR * (s_home - e_home)
    new_away = away_elo + K_FACTOR * (s_away - e_away)

    now = datetime.utcnow().isoformat()
    execute("UPDATE teams SET elo = ?, elo_updated_at = ? WHERE team_id = ?",
            (new_home, now, home_id))
    execute("UPDATE teams SET elo = ?, elo_updated_at = ? WHERE team_id = ?",
            (new_away, now, away_id))
    log.info("Elo updated: team %s %.0f→%.0f | team %s %.0f→%.0f",
             home_id, home_elo, new_home, away_id, away_elo, new_away)


def recompute_all_elos() -> int:
    """Recompute all Elo ratings from historical match data in chronological order."""
    rows = query("""
        SELECT match_id, home_team_id, away_team_id, home_score, away_score, match_date
        FROM matches
        WHERE status = 'FT' AND home_score IS NOT NULL AND away_score IS NOT NULL
        ORDER BY match_date ASC
    """)
    if not rows:
        log.info("No finished matches to recompute Elo from")
        return 0
    # Reset
    execute("UPDATE teams SET elo = ?", (DEFAULT_ELO,))
    count = 0
    for r in rows:
        if r["home_score"] is None or r["away_score"] is None:
            continue
        update_elo_from_match(r["match_id"], r["home_score"], r["away_score"])
        count += 1
    log.info("Recomputed %d matches → Elo ratings", count)
    return count
