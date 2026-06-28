"""Value calculator — compute value vs market odds.

value = (model_probability × decimal_odds) - 1

A value > 0 means our model thinks the outcome is more likely than the
market does. We require value > VALUE_THRESHOLD (default 3%) to place a bet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ValueBet:
    market: str          # "1X2", "over_under", "btts", "correct_score", "double_chance", "draw_no_bet"
    selection: str       # "home", "draw", "over_2.5", "btts_yes", "2-1", "1X", etc.
    model_prob: float    # probability from our model
    odds: float          # best decimal odds available
    bookmaker: str
    implied_prob: float  # market's implied probability (1 / odds)
    value: float         # (model_prob * odds) - 1
    confidence: float    # model's confidence in this selection

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "selection": self.selection,
            "model_prob": round(self.model_prob, 4),
            "odds": self.odds,
            "bookmaker": self.bookmaker,
            "implied_prob": round(self.implied_prob, 4),
            "value": round(self.value, 4),
            "confidence": round(self.confidence, 4),
        }


def compute_value(model_prob: float, odds: float) -> float:
    """value = (model_prob × odds) - 1.

    Negative → no edge.
    Positive → edge exists. The higher, the better.
    """
    if odds <= 1.0 or model_prob <= 0:
        return -1.0
    return (model_prob * odds) - 1.0


def implied_probability(odds: float) -> float:
    return 1.0 / odds if odds > 1 else 0.0


def find_best_odds(odds_history: list[dict[str, Any]], market: str,
                   selection: str) -> tuple[float, str] | None:
    """Given a list of odds rows, find the best odds for a given market+selection.

    Returns (best_odds, bookmaker) or None.
    """
    candidates = [
        (o["odds"], o.get("bookmaker", ""))
        for o in odds_history
        if o.get("market") == market and o.get("selection") == selection
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])


def compute_market_value(model_prob: float, best_odds: float) -> tuple[float, float]:
    """Return (value, implied_probability)."""
    return compute_value(model_prob, best_odds), implied_probability(best_odds)
