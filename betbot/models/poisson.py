"""Poisson / Dixon-Coles goal model.

Estimates expected goals (λ_home, λ_away) for a match and provides
probability derivations for all markets: 1/N/2, exact score, over/under, BTTS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from scipy.stats import poisson


@dataclass
class GoalExpectation:
    lambda_home: float
    lambda_away: float
    rho: float = -0.1  # Dixon-Coles correlation for low-scoring outcomes

    def expected_total(self) -> float:
        return self.lambda_home + self.lambda_away


def estimate_lambdas(home_attack: float, home_defense: float,
                     away_attack: float, away_defense: float,
                     league_avg_home_goals: float = 1.45,
                     league_avg_away_goals: float = 1.10,
                     home_advantage: float = 1.30) -> GoalExpectation:
    """Estimate λ_home and λ_away from team attack/defense ratings.

    Ratings are expressed as multipliers vs the league average (1.0 = average).
    - home_attack > 1: home team scores more than average.
    - home_defense < 1: home team concedes less than average.
    - away_attack > 1: away team scores more than average.
    - away_defense < 1: away team concedes less than average.

    league_avg_home_goals / league_avg_away_goals: league-typical goals.
    home_advantage: multiplicative boost for playing at home.
    """
    lambda_home = league_avg_home_goals * home_attack * away_defense * home_advantage
    lambda_away = league_avg_away_goals * away_attack * home_defense
    lambda_home = max(0.1, min(5.0, lambda_home))
    lambda_away = max(0.1, min(5.0, lambda_away))
    return GoalExpectation(lambda_home=lambda_home, lambda_away=lambda_away)


def team_ratings_from_xg(xg_for_per_match: float, xga_per_match: float,
                          league_avg_home: float = 1.45,
                          league_avg_away: float = 1.10) -> tuple[float, float, float, float]:
    """Convert team's xG/xGA per-match to attack/defense ratings.

    Returns (home_attack, home_defense, away_attack, away_defense) multipliers.
    The split is approximate: a team's overall attacking output is used as
    attack rating; defensive output vs league average gives defense rating.
    """
    overall_xg = (xg_for_per_match + (league_avg_home + league_avg_away) / 2) / 2
    attack = max(0.4, min(2.5, xg_for_per_match / max(0.5, (league_avg_home + league_avg_away) / 2)))
    defense = max(0.4, min(2.5, xga_per_match / max(0.5, (league_avg_home + league_avg_away) / 2)))
    return attack, defense, attack, defense


# ----------------------------------------------------------------------------
# Probability derivations
# ----------------------------------------------------------------------------

def prob_score_matrix(exp: GoalExpectation, max_goals: int = 8) -> list[list[float]]:
    """Return a (max_goals+1) x (max_goals+1) matrix of P(home=i, away=j).

    Applies the Dixon-Coles correction for low-scoring cells (0-0, 0-1, 1-0, 1-1).
    """
    lh, la = exp.lambda_home, exp.lambda_away
    rho = exp.rho

    mat: list[list[float]] = []
    for i in range(max_goals + 1):
        row: list[float] = []
        for j in range(max_goals + 1):
            p = poisson.pmf(i, lh) * poisson.pmf(j, la)
            # Dixon-Coles correction
            if i == 0 and j == 0:
                p *= 1.0 - lh * la * rho
            elif i == 0 and j == 1:
                p *= 1.0 + lh * rho
            elif i == 1 and j == 0:
                p *= 1.0 + la * rho
            elif i == 1 and j == 1:
                p *= 1.0 - rho
            row.append(p)
        mat.append(row)

    return _normalize_matrix(mat)


def _normalize_matrix(mat: list[list[float]]) -> list[list[float]]:
    """Renormalize so probabilities sum to 1 (Dixon-Coles correction can drift)."""
    total = sum(sum(row) for row in mat)
    if total <= 0:
        n = len(mat)
        return [[1 / (n * n) for _ in range(n)] for _ in range(n)]
    return [[c / total for c in row] for row in mat]


def prob_outcome_1x2(exp: GoalExpectation, max_goals: int = 8) -> tuple[float, float, float]:
    """Return (P_home, P_draw, P_away)."""
    mat = prob_score_matrix(exp, max_goals)
    p_home = sum(mat[i][j] for i in range(len(mat)) for j in range(len(mat)) if i > j)
    p_draw = sum(mat[i][j] for i in range(len(mat)) for j in range(i + 1) if i == j)
    p_away = sum(mat[i][i] for i in range(len(mat)))
    # Double count correction: the loop above sums p_draw incorrectly
    # Let's recompute properly:
    p_home = p_draw = p_away = 0.0
    n = len(mat)
    for i in range(n):
        for j in range(n):
            if i > j:
                p_home += mat[i][j]
            elif i == j:
                p_draw += mat[i][j]
            else:
                p_away += mat[i][j]
    total = p_home + p_draw + p_away
    if total <= 0:
        return (1/3, 1/3, 1/3)
    return (p_home / total, p_draw / total, p_away / total)


def prob_exact_score(exp: GoalExpectation, max_goals: int = 8) -> list[tuple[str, float]]:
    """Return list of (score_str, probability) sorted by probability desc."""
    mat = prob_score_matrix(exp, max_goals)
    pairs = []
    for i in range(len(mat)):
        for j in range(len(mat)):
            if i <= max_goals and j <= max_goals:
                pairs.append((f"{i}-{j}", mat[i][j]))
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


def prob_over_under(exp: GoalExpectation, threshold: float,
                    max_goals: int = 10) -> tuple[float, float]:
    """Return (P_over, P_under) for total goals > threshold."""
    mat = prob_score_matrix(exp, max_goals)
    p_over = p_under = 0.0
    n = len(mat)
    for i in range(n):
        for j in range(n):
            if (i + j) > threshold:
                p_over += mat[i][j]
            elif (i + j) < threshold:
                p_under += mat[i][j]
    total = p_over + p_under
    if total <= 0:
        return 0.5, 0.5
    # Also count exact threshold = no_push / push
    push = 1.0 - total
    return p_over / (1 - push), p_under / (1 - push)


def prob_btts(exp: GoalExpectation, max_goals: int = 8) -> tuple[float, float]:
    """Return (P_btts_yes, P_btts_no)."""
    mat = prob_score_matrix(exp, max_goals)
    p_yes = p_no = 0.0
    n = len(mat)
    for i in range(n):
        for j in range(n):
            if i >= 1 and j >= 1:
                p_yes += mat[i][j]
            else:
                p_no += mat[i][j]
    total = p_yes + p_no
    if total <= 0:
        return 0.5, 0.5
    return p_yes / total, p_no / total


def prob_double_chance(exp: GoalExpectation, max_goals: int = 8) -> tuple[float, float, float]:
    """Return (P_1X, P_X2, P_12)."""
    p_h, p_d, p_a = prob_outcome_1x2(exp, max_goals)
    return p_h + p_d, p_d + p_a, p_h + p_a


def prob_draw_no_bet(exp: GoalExpectation, max_goals: int = 8) -> tuple[float, float]:
    """Return (P_home_dnb, P_away_dnb) — draw nullifies the bet."""
    mat = prob_score_matrix(exp, max_goals)
    p_home_only = p_away_only = 0.0
    n = len(mat)
    for i in range(n):
        for j in range(n):
            if i > j:
                p_home_only += mat[i][j]
            elif i < j:
                p_away_only += mat[i][j]
    total = p_home_only + p_away_only
    if total <= 0:
        return 0.5, 0.5
    return p_home_only / total, p_away_only / total
