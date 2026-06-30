"""Tests for the model recalibration + decision engine anti-draw-spam.

Three bugs covered here:
1. team_ratings_from_xg used to fabricate 4 ratings from a single team's
   stats (returning `(attack, defense, attack, defense)`). Now returns 2.
2. The 1X2 confidence used to be shared by home/draw/away (so they tied
   and the sort-stable order home→draw→away decided the winner). Now it's
   per-selection (margin over the runner-up).
3. The decision engine only checked candidates[0]. Now it walks the list
   and picks the first that meets every threshold.
4. Draw selections below MIN_DRAW_MARGIN are dropped to stop the bot from
   spamming draw bets on close matches.
"""
from __future__ import annotations

import pytest

from betbot.betting.decision import DecisionEngine
from betbot.config import settings
from betbot.models.markets import MarketProbabilities
from betbot.models.poisson import team_ratings_from_xg


# --- team_ratings_from_xg --------------------------------------------------

def test_team_ratings_from_xg_returns_two_values():
    a, d = team_ratings_from_xg(1.5, 1.0)
    assert isinstance(a, float)
    assert isinstance(d, float)


def test_team_ratings_from_xg_stronger_attack_higher_rating():
    a_strong, _ = team_ratings_from_xg(2.0, 1.2)
    a_weak, _ = team_ratings_from_xg(1.0, 1.2)
    assert a_strong > a_weak


def test_team_ratings_from_xg_clamps_extremes():
    a, d = team_ratings_from_xg(100.0, 100.0)
    assert 0.4 <= a <= 2.5
    assert 0.4 <= d <= 2.5
    a, d = team_ratings_from_xg(0.01, 0.01)
    assert 0.4 <= a <= 2.5
    assert 0.4 <= d <= 2.5


def test_team_ratings_from_xg_independent_per_team():
    """Calling with different inputs gives different outputs — i.e. one
    call is for one team, not a fabricated 4-tuple."""
    a1, d1 = team_ratings_from_xg(1.8, 1.0)
    a2, d2 = team_ratings_from_xg(1.0, 1.8)
    assert a1 != a2
    assert d1 != d2


# --- Decision: per-selection confidence ------------------------------------

def _mp(**kw) -> MarketProbabilities:
    base = dict(
        match_id=1, p_1=0.55, p_x=0.25, p_2=0.20,
        over_under={"2.5": (0.55, 0.45)},
        btts=(0.55, 0.45),
        double_chance={"1X": 0.80, "X2": 0.45, "12": 0.75},
        exact_score=[("1-0", 0.12), ("1-1", 0.10)],
        dnb=(0.73, 0.27),
        lambda_home=1.6, lambda_away=1.0,
    )
    base.update(kw)
    return MarketProbabilities(**base)


def test_per_selection_confidence_uses_margin():
    """Each 1X2 candidate's confidence is its prob minus the runner-up."""
    engine = DecisionEngine()
    mp = _mp(p_1=0.80, p_x=0.15, p_2=0.05)
    odds = [
        {"market": "h2h", "selection": "home", "odds": 1.50, "bookmaker": "A"},
        {"market": "h2h", "selection": "draw", "odds": 4.5, "bookmaker": "A"},
        {"market": "h2h", "selection": "away", "odds": 8.0, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, {}, odds)
    by_sel = {c.selection: c for c in decision.all_candidates
              if c.market == "1X2"}
    # 'home' survives; 'draw' and 'away' are dropped by the anti-draw
    # filter (margin below MIN_DRAW_MARGIN) and by low margin respectively.
    assert by_sel["home"].confidence == pytest.approx(0.65)  # 0.80 - 0.15


# --- Decision: iterate candidates ------------------------------------------

def test_decision_picks_first_eligible_not_just_top():
    """When the top-confidence candidate fails value threshold, the engine
    should still pick the next one that passes."""
    engine = DecisionEngine()
    mp = _mp(p_1=0.85, p_x=0.10, p_2=0.05,
             over_under={"2.5": (0.92, 0.08)})
    odds = [
        # 1X2 home: massive value (0.85 × 1.30 = 1.105 → value = 0.105)
        {"market": "h2h", "selection": "home", "odds": 1.30, "bookmaker": "A"},
        # over_2.5: 0.92 × 0.85 = 0.782 → value = -0.218 (FAILS threshold)
        {"market": "totals", "selection": "over_2.5", "odds": 0.85, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, {}, odds)
    assert decision.selected is not None
    assert decision.selected.market == "1X2"
    assert decision.selected.selection == "home"


def test_decision_returns_none_when_no_candidate_passes():
    engine = DecisionEngine()
    mp = _mp(p_1=0.40, p_x=0.35, p_2=0.25)  # all margins < 0.05
    odds = [
        {"market": "h2h", "selection": "home", "odds": 1.95, "bookmaker": "A"},
        {"market": "h2h", "selection": "draw", "odds": 3.6, "bookmaker": "A"},
        {"market": "h2h", "selection": "away", "odds": 4.5, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, {}, odds)
    assert decision.selected is None


# --- Anti-draw-spam filter -------------------------------------------------

def test_draw_below_min_margin_is_rejected():
    """Draw with prob - max(home, away) < MIN_DRAW_MARGIN must be skipped."""
    engine = DecisionEngine()
    # p_x = 0.40, max(p_1=0.35, p_2=0.25) = 0.35 → margin = 0.05 < 0.08
    mp = _mp(p_1=0.35, p_x=0.40, p_2=0.25)
    odds = [
        {"market": "h2h", "selection": "home", "odds": 2.50, "bookmaker": "A"},
        {"market": "h2h", "selection": "draw", "odds": 3.20, "bookmaker": "A"},
        {"market": "h2h", "selection": "away", "odds": 4.00, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, {}, odds)
    draw_cands = [c for c in decision.all_candidates
                  if c.market == "1X2" and c.selection == "draw"]
    assert draw_cands == []


def test_draw_above_min_margin_is_kept():
    """Draw with margin > MIN_DRAW_MARGIN survives the filter."""
    engine = DecisionEngine()
    # p_x = 0.50, p_1 = 0.40 → margin = 0.10 > 0.08
    mp = _mp(p_1=0.40, p_x=0.50, p_2=0.10)
    odds = [
        {"market": "h2h", "selection": "home", "odds": 2.50, "bookmaker": "A"},
        {"market": "h2h", "selection": "draw", "odds": 2.80, "bookmaker": "A"},  # value = 0.50*2.80-1 = 0.40
        {"market": "h2h", "selection": "away", "odds": 6.00, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, {}, odds)
    draw_cands = [c for c in decision.all_candidates
                  if c.market == "1X2" and c.selection == "draw"]
    assert len(draw_cands) == 1
    assert draw_cands[0].confidence == pytest.approx(0.10)


# --- MAX_SELECTION_VALUE cap -----------------------------------------------

def test_max_selection_value_blocks_outsider_value(monkeypatch):
    """A candidate with value > MAX_SELECTION_VALUE is rejected as
    mis-calibrated (typically a runaway model prob). settings is a frozen
    dataclass, so we swap in a fresh instance for the test."""
    from betbot import config as config_mod
    from dataclasses import replace
    patched = replace(settings, MAX_SELECTION_VALUE=0.50)
    monkeypatch.setattr(config_mod, "settings", patched)
    monkeypatch.setattr("betbot.betting.decision.settings", patched)

    engine = DecisionEngine()
    mp = _mp(p_1=0.85, p_x=0.10, p_2=0.05)
    odds = [
        # 0.85 × 5.0 = 4.25 → value = 3.25 (well above 0.50 cap)
        {"market": "h2h", "selection": "home", "odds": 5.0, "bookmaker": "A"},
    ]
    decision = engine.decide({"match_id": 1}, mp, {}, odds)
    assert decision.selected is None