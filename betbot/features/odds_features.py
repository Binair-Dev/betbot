"""Features 7, 14, 15: Market odds features.

- 7. Odds value: implicit probability vs our model probability.
- 14. Odds movement: opening vs current odds movement.
- 15. Market bias: favorite-longshot bias detection.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from betbot.db.repository import execute, query, query_one
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)

# Bookmaker overround typically ~5-8% in soccer
TYPICAL_OVERROUND = 0.05


def decimal_to_implied(odds: float) -> float:
    """Convert decimal odds to implied probability, including bookmaker margin."""
    return 1.0 / odds if odds > 1 else 0.0


def remove_vig(probs: list[float]) -> list[float]:
    """Remove bookmaker overround from implied probabilities (proportional method)."""
    total = sum(probs)
    if total <= 0:
        return probs
    return [p / total for p in probs]


class OddsValueFeature(Feature):
    """Feature 7: market value. Returns the 'true' fair odds for each outcome
    based on the market consensus. The deltas reflect how much our internal
    probability diverges from the market.

    For this feature, we compute the *opposite* — the market is the ground truth
    and we shift our model toward the market when our data is sparse.
    """

    name = "odds_value"
    weight = 0.20

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        match_id = match.get("match_id")
        odds = _get_latest_odds(match_id, market="h2h") if match_id else []
        if not odds:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no odds"}, missing=True)

        # Aggregate best odds per selection across bookmakers
        best = {"home": (0.0, ""), "draw": (0.0, ""), "away": (0.0, "")}
        avg = {"home": [], "draw": [], "away": []}

        for entry in odds:
            selection = entry.get("selection")
            odds_val = entry.get("odds", 0)
            bookmaker = entry.get("bookmaker", "")
            if selection in best and odds_val > best[selection][0]:
                best[selection] = (odds_val, bookmaker)
            if selection in avg:
                avg[selection].append(odds_val)

        # Average implied probability (de-vigged)
        imp = {
            sel: [decimal_to_implied(o) for o in avg[sel]] for sel in avg
        }
        # Use best odds to compute fair market prob (de-vigged)
        fair_probs = remove_vig([
            decimal_to_implied(best["home"][0]),
            decimal_to_implied(best["draw"][0]),
            decimal_to_implied(best["away"][0]),
        ])
        f_home, f_draw, f_away = fair_probs

        # Compare to uniform 1/3 baseline; this is the model's view of "the market says"
        uniform = 1.0 / 3.0
        delta = (
            (f_home - uniform) * 0.15,
            (f_draw - uniform) * 0.15,
            (f_away - uniform) * 0.15,
        )
        delta = normalize_delta(delta)

        confidence = 0.85  # market is generally reliable

        return FeatureResult(
            delta=delta,
            confidence=confidence,
            raw={
                "best_home": best["home"][0], "best_draw": best["draw"][0],
                "best_away": best["away"][0],
                "best_bookmaker_home": best["home"][1],
                "fair_home": round(f_home, 3),
                "fair_draw": round(f_draw, 3),
                "fair_away": round(f_away, 3),
            },
        )


class OddsMovementFeature(Feature):
    """Feature 14: Odds movement detection.

    A sharp movement often signals new information (injury, lineup).
    We compare the earliest vs latest odds we have on record.
    """

    name = "odds_movement"
    weight = 0.05

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        match_id = match.get("match_id")
        if not match_id:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no match_id"}, missing=True)

        rows = query(
            """SELECT selection, odds, fetched_at FROM odds_history
               WHERE match_id = ? AND market = 'h2h'
               ORDER BY fetched_at ASC""",
            (match_id,),
        )
        if not rows or len(rows) < 2:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "insufficient history"}, missing=True)

        # Group by selection
        by_sel: dict[str, list[tuple[float, str]]] = {}
        for r in rows:
            by_sel.setdefault(r["selection"], []).append(
                (r["odds"], r["fetched_at"])
            )

        movements = {}
        for sel, points in by_sel.items():
            if len(points) < 2:
                continue
            first_odds = points[0][0]
            last_odds = points[-1][0]
            movement = (last_odds - first_odds) / first_odds if first_odds else 0
            movements[sel] = round(movement, 4)

        # Strong drop in odds = team more likely to win
        # home drift: positive = drift away (less likely), negative = shortening (more likely)
        home_drift = movements.get("home", 0)
        away_drift = movements.get("away", 0)
        draw_drift = movements.get("draw", 0)

        # Convert to shifts: each 5% shortening ≈ +1.5pp shift
        shift_home = -home_drift * 0.30
        shift_away = -away_drift * 0.30
        shift_draw = -draw_drift * 0.30

        delta = (shift_home, shift_draw, shift_away)
        delta = normalize_delta(delta)

        confidence = 0.5 if movements else 0.0

        return FeatureResult(
            delta=delta,
            confidence=confidence,
            raw={"movements": movements},
        )


class MarketBiasFeature(Feature):
    """Feature 15: favorite-longshot bias.

    Bookmakers shade prices against the favorite in popular markets
    (Real Madrid, PSG, Man City, Bayern). If our model agrees with the
    market that the favorite wins, this bias doesn't help us. But when
    we think the favorite is overrated vs the market, we have edge on
    the outsider/draw.
    """

    name = "market_bias"
    weight = 0.04

    POPULAR_FAVORITES = {
        # Team names commonly affected
        "Real Madrid", "Barcelona", "Atletico Madrid",
        "Manchester City", "Liverpool", "Manchester United", "Arsenal", "Chelsea",
        "Bayern Munich", "Borussia Dortmund",
        "Paris Saint-Germain", "Marseille",
        "Juventus", "Inter", "AC Milan", "Napoli", "Roma",
        "Ajax", "PSV", "Feyenoord",
        "Benfica", "Porto", "Sporting CP",
        "Club Brugge", "Anderlecht",
    }

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_name = (match.get("home_team_name") or "").lower()
        away_name = (match.get("away_team_name") or "").lower()

        home_popular = any(pop.lower() in home_name for pop in self.POPULAR_FAVORITES)
        away_popular = any(pop.lower() in away_name for pop in self.POPULAR_FAVORITES)

        # If home is a popular favorite, their odds are slightly inflated;
        # the outsider/draw has slight extra value.
        if home_popular and not away_popular:
            return FeatureResult(
                delta=(-0.01, 0.01, 0.0),
                confidence=0.4,
                raw={"bias": "home_popular"},
            )
        if away_popular and not home_popular:
            return FeatureResult(
                delta=(0.0, 0.01, -0.01),
                confidence=0.4,
                raw={"bias": "away_popular"},
            )
        return FeatureResult(
            delta=(0.0, 0.0, 0.0),
            confidence=0.2,
            raw={"bias": "none"},
        )


def _get_latest_odds(match_id: int, market: str = "h2h") -> list[dict]:
    """Get the most recent odds snapshot for a match+market."""
    rows = query(
        """SELECT bookmaker, selection, odds FROM odds_history
           WHERE match_id = ? AND market = ?
           AND fetched_at = (
               SELECT MAX(fetched_at) FROM odds_history
               WHERE match_id = ? AND market = ?
           )""",
        (match_id, market, match_id, market),
    )
    return [dict(r) for r in rows]


def persist_odds_snapshot(match_id: int, market: str, bookmaker: str,
                          selections: dict[str, float], implied: dict[str, float]) -> None:
    """Persist an odds snapshot to the history table."""
    now = datetime.utcnow().isoformat()
    for sel, odds in selections.items():
        execute(
            """INSERT INTO odds_history (match_id, bookmaker, market, selection, odds, implied_prob, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (match_id, bookmaker, market, sel, odds, implied.get(sel, 0), now),
        )
