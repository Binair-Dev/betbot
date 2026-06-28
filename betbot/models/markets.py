"""Markets — unified probability derivations for all bet types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from betbot.models.poisson import (
    GoalExpectation,
    prob_btts,
    prob_double_chance,
    prob_draw_no_bet,
    prob_exact_score,
    prob_outcome_1x2,
    prob_over_under,
)


@dataclass
class MarketProbabilities:
    match_id: int
    p_1: float
    p_x: float
    p_2: float
    over_under: dict[str, tuple[float, float]] = field(default_factory=dict)
    btts: tuple[float, float] = (0.5, 0.5)
    double_chance: dict[str, float] = field(default_factory=dict)
    exact_score: list[tuple[str, float]] = field(default_factory=list)
    dnb: tuple[float, float] = (0.5, 0.5)
    lambda_home: float = 0.0
    lambda_away: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "p_1": round(self.p_1, 4),
            "p_x": round(self.p_x, 4),
            "p_2": round(self.p_2, 4),
            "over_under": {k: [round(v[0], 4), round(v[1], 4)]
                            for k, v in self.over_under.items()},
            "btts": {"yes": round(self.btts[0], 4), "no": round(self.btts[1], 4)},
            "double_chance": {k: round(v, 4) for k, v in self.double_chance.items()},
            "exact_score": [(s, round(p, 4)) for s, p in self.exact_score[:10]],
            "dnb": {"home": round(self.dnb[0], 4), "away": round(self.dnb[1], 4)},
            "lambda_home": round(self.lambda_home, 3),
            "lambda_away": round(self.lambda_away, 3),
        }


def compute_all_markets(match_id: int, exp: GoalExpectation,
                        ou_thresholds: tuple[float, ...] = (1.5, 2.5, 3.5, 4.5),
                        max_goals: int = 8) -> MarketProbabilities:
    """Compute probabilities for all markets from goal expectations."""
    p1, px, p2 = prob_outcome_1x2(exp, max_goals)
    ou = {f"{t}": prob_over_under(exp, t, max_goals) for t in ou_thresholds}
    btts = prob_btts(exp, max_goals)
    dc1x, dcx2, dc12 = prob_double_chance(exp, max_goals)
    exact = prob_exact_score(exp, max_goals)
    dnb = prob_draw_no_bet(exp, max_goals)

    return MarketProbabilities(
        match_id=match_id,
        p_1=p1, p_x=px, p_2=p2,
        over_under=ou,
        btts=btts,
        double_chance={"1X": dc1x, "X2": dcx2, "12": dc12},
        exact_score=exact,
        dnb=dnb,
        lambda_home=exp.lambda_home,
        lambda_away=exp.lambda_away,
    )
