"""Tests for the Poisson / Dixon-Coles goal model."""
from __future__ import annotations

import math

import pytest

from betbot.models.poisson import (
    estimate_lambdas,
    prob_btts,
    prob_double_chance,
    prob_draw_no_bet,
    prob_exact_score,
    prob_outcome_1x2,
    prob_over_under,
    prob_score_matrix,
)


def test_estimate_lambdas_realistic():
    exp = estimate_lambdas(
        home_attack=1.20, home_defense=0.85,
        away_attack=1.05, away_defense=1.00,
    )
    assert 0.5 < exp.lambda_home < 4.0
    assert 0.5 < exp.lambda_away < 4.0
    # Home team is stronger → λ_home > λ_away
    assert exp.lambda_home > exp.lambda_away


def test_estimate_lambdas_clamping():
    # Extreme values should be clamped
    exp = estimate_lambdas(
        home_attack=10.0, home_defense=10.0,
        away_attack=0.01, away_defense=0.01,
    )
    assert exp.lambda_home <= 5.0
    assert exp.lambda_away >= 0.1


def test_outcome_1x2_sums_to_one():
    exp = estimate_lambdas(1.10, 1.00, 1.00, 1.00)
    p1, px, p2 = prob_outcome_1x2(exp)
    assert abs(p1 + px + p2 - 1.0) < 1e-6


def test_outcome_1x2_home_favored():
    exp = estimate_lambdas(1.30, 0.80, 1.00, 1.00)
    p1, px, p2 = prob_outcome_1x2(exp)
    assert p1 > p2


def test_over_under_consistency():
    exp = estimate_lambdas(1.20, 0.90, 1.10, 0.90)
    for t in [1.5, 2.5, 3.5, 4.5]:
        po, pu = prob_over_under(exp, t)
        assert abs(po + pu - 1.0) < 1e-6
    # Higher threshold → lower over probability
    p_over_25, _ = prob_over_under(exp, 2.5)
    p_over_35, _ = prob_over_under(exp, 3.5)
    assert p_over_25 > p_over_35


def test_btts_consistency():
    exp = estimate_lambdas(1.20, 0.90, 1.10, 0.90)
    py, pn = prob_btts(exp)
    assert abs(py + pn - 1.0) < 1e-6


def test_double_chance_complementary():
    exp = estimate_lambdas(1.20, 0.90, 1.10, 0.90)
    p1x, px2, p12 = prob_double_chance(exp)
    p1, px, p2 = prob_outcome_1x2(exp)
    # 1X = P(home) + P(draw)
    assert abs(p1x - (p1 + px)) < 1e-6
    assert abs(px2 - (px + p2)) < 1e-6
    assert abs(p12 - (p1 + p2)) < 1e-6


def test_exact_score_top_5_sum():
    exp = estimate_lambdas(1.20, 0.90, 1.10, 0.90)
    scores = prob_exact_score(exp)
    assert len(scores) > 0
    assert all(0 <= p <= 1 for _, p in scores)
    # Sum of top scores should not exceed 1
    top5_sum = sum(p for _, p in scores[:5])
    assert top5_sum <= 1.0


def test_score_matrix_dimensions():
    exp = estimate_lambdas(1.20, 0.90, 1.10, 0.90)
    mat = prob_score_matrix(exp, max_goals=5)
    assert len(mat) == 6
    assert all(len(row) == 6 for row in mat)
    # Total mass should be ~1
    total = sum(sum(row) for row in mat)
    assert abs(total - 1.0) < 0.05  # Dixon-Coles can drift slightly


def test_dnb_consistency():
    exp = estimate_lambdas(1.30, 0.80, 1.10, 1.00)
    p_home, p_away = prob_draw_no_bet(exp)
    # Should sum to 1 (draws removed)
    assert abs(p_home + p_away - 1.0) < 1e-6
    # Home stronger → home > away
    assert p_home > p_away
