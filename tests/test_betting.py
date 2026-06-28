"""Tests for value calculation & decision engine."""
from __future__ import annotations

import pytest

from betbot.betting.decision import DecisionEngine, MatchDecision, MarketCandidate
from betbot.betting.value_calc import (
    ValueBet,
    compute_market_value,
    compute_value,
    find_best_odds,
    implied_probability,
)
from betbot.models.markets import MarketProbabilities


def test_compute_value_positive():
    # Model says 50%, odds 2.50 → value = 0.25 (25% edge)
    assert compute_value(0.5, 2.5) == pytest.approx(0.25)


def test_compute_value_negative():
    # Model says 30%, odds 2.50 → value = -0.25 (no edge)
    assert compute_value(0.3, 2.5) == pytest.approx(-0.25)


def test_compute_value_at_breakeven():
    # Model says 40%, odds 2.50 → value = 0.0 (fair)
    assert compute_value(0.4, 2.5) == pytest.approx(0.0)


def test_compute_value_invalid_odds():
    assert compute_value(0.5, 0.5) == -1.0
    assert compute_value(0.0, 2.5) == -1.0


def test_implied_probability():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(1.5) == pytest.approx(2 / 3)


def test_compute_market_value():
    value, imp = compute_market_value(0.6, 2.0)
    assert value == pytest.approx(0.2)
    assert imp == pytest.approx(0.5)


def test_find_best_odds():
    odds_history = [
        {"market": "h2h", "selection": "home", "odds": 2.0, "bookmaker": "A"},
        {"market": "h2h", "selection": "home", "odds": 2.1, "bookmaker": "B"},
        {"market": "h2h", "selection": "home", "odds": 1.9, "bookmaker": "C"},
    ]
    best = find_best_odds(odds_history, "h2h", "home")
    assert best == (2.1, "B")


def test_find_best_odds_missing():
    assert find_best_odds([], "h2h", "home") is None


def _make_market_probs() -> MarketProbabilities:
    return MarketProbabilities(
        match_id=1,
        p_1=0.55, p_x=0.25, p_2=0.20,
        over_under={"2.5": (0.55, 0.45), "1.5": (0.85, 0.15)},
        btts=(0.55, 0.45),
        double_chance={"1X": 0.80, "X2": 0.45, "12": 0.75},
        exact_score=[("1-0", 0.12), ("1-1", 0.10), ("2-1", 0.09)],
        dnb=(0.73, 0.27),
        lambda_home=1.6, lambda_away=1.0,
    )


def test_decision_picks_highest_confidence_meeting_thresholds():
    engine = DecisionEngine()
    mp = _make_market_probs()
    # Confidences chosen so 1X2 "home" is highest at 0.85 and has good value
    conf_map = {
        "1X2": 0.85, "btts": 0.55, "double_chance": 0.75,
        "correct_score": 0.55, "draw_no_bet": 0.65,
        "over_under_2.5": 0.60, "over_under_1.5": 0.70,
    }
    odds_history = [
        {"market": "h2h", "selection": "home", "odds": 1.95, "bookmaker": "A"},   # value = 0.55*1.95-1 = 0.0725
        {"market": "h2h", "selection": "draw", "odds": 3.6, "bookmaker": "A"},    # value = 0.25*3.6-1 = -0.10
        {"market": "h2h", "selection": "away", "odds": 4.5, "bookmaker": "A"},    # value = 0.20*4.5-1 = -0.10
    ]
    match = {"match_id": 1}
    decision = engine.decide(match, mp, conf_map, odds_history)
    assert decision.selected is not None
    assert decision.selected.market == "1X2"
    assert decision.selected.selection == "home"


def test_decision_rejects_low_confidence():
    engine = DecisionEngine()
    mp = _make_market_probs()
    conf_map = {"1X2": 0.50}  # below threshold
    odds_history = [
        {"market": "h2h", "selection": "home", "odds": 1.95, "bookmaker": "A"},
        {"market": "h2h", "selection": "draw", "odds": 3.6, "bookmaker": "A"},
        {"market": "h2h", "selection": "away", "odds": 4.5, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, conf_map, odds_history)
    assert decision.selected is None
    assert not decision.should_bet()


def test_decision_rejects_negative_value():
    engine = DecisionEngine()
    mp = _make_market_probs()
    # Force confidence high but odds too short → negative value
    conf_map = {"1X2": 0.90, "over_under_2.5": 0.90}
    odds_history = [
        {"market": "h2h", "selection": "home", "odds": 1.20, "bookmaker": "A"},   # value = 0.55*1.20-1 = -0.34
        {"market": "h2h", "selection": "draw", "odds": 5.0, "bookmaker": "A"},
        {"market": "h2h", "selection": "away", "odds": 10.0, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, conf_map, odds_history)
    assert decision.selected is None


def test_decision_single_bet_per_match():
    """Even if multiple markets meet thresholds, decision.selected is the highest."""
    engine = DecisionEngine()
    mp = _make_market_probs()
    conf_map = {
        "1X2": 0.95,
        "over_under_1.5": 0.85,
        "over_under_2.5": 0.75,
        "btts": 0.70,
        "double_chance": 0.80,
    }
    odds_history = [
        {"market": "h2h", "selection": "home", "odds": 1.95, "bookmaker": "A"},
        {"market": "totals", "selection": "over_1.5", "odds": 1.20, "bookmaker": "A"},
        {"market": "totals", "selection": "under_1.5", "odds": 4.5, "bookmaker": "A"},
        {"market": "totals", "selection": "over_2.5", "odds": 1.85, "bookmaker": "A"},
        {"market": "totals", "selection": "under_2.5", "odds": 1.95, "bookmaker": "A"},
        {"market": "btts", "selection": "yes", "odds": 1.85, "bookmaker": "A"},
        {"market": "btts", "selection": "no", "odds": 1.95, "bookmaker": "A"},
        {"market": "double_chance", "selection": "1X", "odds": 1.25, "bookmaker": "A"},
        {"market": "double_chance", "selection": "X2", "odds": 2.30, "bookmaker": "A"},
        {"market": "double_chance", "selection": "12", "odds": 1.35, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, conf_map, odds_history)
    # Selected should be only ONE candidate (1X2 home), even though many meet thresholds
    assert decision.selected is not None
    assert decision.selected.market == "1X2"
    assert len(decision.all_candidates) >= 3  # we have many candidates evaluated
