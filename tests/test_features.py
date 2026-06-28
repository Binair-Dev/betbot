"""Tests for feature modules."""
from __future__ import annotations

import pytest

from betbot.features.base import FeatureResult, normalize_delta
from betbot.features.home_advantage import HomeAdvantageFeature
from betbot.features.odds_features import (
    MarketBiasFeature,
    OddsMovementFeature,
    OddsValueFeature,
    remove_vig,
)


def test_normalize_delta_clamps():
    """normalize_delta should clamp each value to [-0.2, +0.2] and zero the sum."""
    delta = normalize_delta((0.5, 0.5, 0.5))
    assert all(-0.2 <= d <= 0.2 for d in delta)
    # Sum should be ~zero after zero-mean
    assert abs(sum(delta)) < 1e-6


def test_remove_vig():
    probs = remove_vig([0.50, 0.30, 0.25])  # sum = 1.05
    assert abs(sum(probs) - 1.0) < 1e-6
    # Proportional: each scaled by 1/1.05
    assert abs(probs[0] - 0.50 / 1.05) < 1e-6


def test_home_advantage_premier_league():
    feat = HomeAdvantageFeature()
    result = feat.compute({"league_id": 39})  # Premier League
    assert result.confidence == 0.95
    assert result.delta[0] > 0  # home boost positive
    assert result.delta[2] < 0  # away negative


def test_home_advantage_ucl_smaller():
    feat = HomeAdvantageFeature()
    pl = feat.compute({"league_id": 39}).delta
    ucl = feat.compute({"league_id": 2}).delta
    assert pl[0] > ucl[0]  # PL home advantage > UCL


def test_market_bias_popular_home():
    feat = MarketBiasFeature()
    result = feat.compute({
        "home_team_name": "Real Madrid",
        "away_team_name": "Girona",
    })
    assert result.raw["bias"] == "home_popular"
    # Slight negative on home, positive on draw (outsider bias)
    assert result.delta[0] < 0
    assert result.delta[1] > 0


def test_market_bias_no_popular():
    feat = MarketBiasFeature()
    result = feat.compute({
        "home_team_name": "Club Brugge",
        "away_team_name": "Anderlecht",
    })
    assert result.raw["bias"] == "none"


def test_odds_value_no_odds():
    feat = OddsValueFeature()
    result = feat.compute({"match_id": 999})  # no odds
    assert result.missing is True


def test_odds_movement_no_history():
    feat = OddsMovementFeature()
    result = feat.compute({"match_id": 999})
    assert result.missing is True
