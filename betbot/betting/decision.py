"""Decision engine — for each match, pick the SINGLE best market to bet on.

Rule: For each match, evaluate ALL markets and keep the one with the highest
confidence that meets the threshold. The other rule: the bet must have positive
value (model prob × odds > 1) above the value threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from betbot.betting.value_calc import (
    ValueBet,
    compute_value,
    find_best_odds,
    implied_probability,
)
from betbot.config import settings
from betbot.logging_setup import get_logger
from betbot.models.markets import MarketProbabilities

log = get_logger(__name__)


@dataclass
class MarketCandidate:
    market: str
    selection: str
    model_prob: float
    confidence: float  # confidence in the selection itself (max - second max)
    best_odds: float
    bookmaker: str
    value: float

    def meets_threshold(self) -> bool:
        return (self.confidence >= settings.CONFIDENCE_THRESHOLD
                and self.value >= settings.VALUE_THRESHOLD)


@dataclass
class MatchDecision:
    match_id: int
    selected: MarketCandidate | None  # The single best market for this match
    all_candidates: list[MarketCandidate] = field(default_factory=list)
    reason: str = ""

    def should_bet(self) -> bool:
        return self.selected is not None and self.selected.meets_threshold()

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "selected": self.selected.__dict__ if self.selected else None,
            "all_candidates": [c.__dict__ for c in self.all_candidates],
            "reason": self.reason,
            "should_bet": self.should_bet(),
        }


class DecisionEngine:
    """For each match, evaluate all markets and pick the best one."""

    def decide(self, match: dict[str, Any], market_probs: MarketProbabilities,
               confidence_per_market: dict[str, float],
               odds_history: list[dict[str, Any]]) -> MatchDecision:
        candidates: list[MarketCandidate] = []

        # 1X2 market
        candidates.extend(self._build_1x2_candidates(match, market_probs, confidence_per_market, odds_history))
        # Over/Under
        candidates.extend(self._build_ou_candidates(match, market_probs, confidence_per_market, odds_history))
        # BTTS
        candidates.extend(self._build_btts_candidates(match, market_probs, confidence_per_market, odds_history))
        # Double Chance
        candidates.extend(self._build_dc_candidates(match, market_probs, confidence_per_market, odds_history))
        # Correct Score (only top 3 most likely)
        candidates.extend(self._build_cs_candidates(match, market_probs, confidence_per_market, odds_history))
        # Draw No Bet
        candidates.extend(self._build_dnb_candidates(match, market_probs, confidence_per_market, odds_history))

        candidates.sort(key=lambda c: c.confidence, reverse=True)

        selected = candidates[0] if candidates and candidates[0].meets_threshold() else None
        reason = ""
        if not candidates:
            reason = "no markets evaluated"
        elif selected is None:
            reason = (f"best candidate '{candidates[0].market}/{candidates[0].selection}' "
                      f"failed thresholds "
                      f"(conf={candidates[0].confidence:.2%} < {settings.CONFIDENCE_THRESHOLD:.0%} OR "
                      f"value={candidates[0].value:.2%} < {settings.VALUE_THRESHOLD:.0%})")

        return MatchDecision(
            match_id=match.get("match_id", 0),
            selected=selected,
            all_candidates=candidates,
            reason=reason,
        )

    def _build_1x2_candidates(self, match, mp, conf_map, odds_history):
        out = []
        conf = conf_map.get("1X2", 0.0)
        probs = {"home": mp.p_1, "draw": mp.p_x, "away": mp.p_2}
        for sel, prob in probs.items():
            res = find_best_odds(odds_history, "h2h", sel)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            out.append(MarketCandidate(
                market="1X2", selection=sel,
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_ou_candidates(self, match, mp, conf_map, odds_history):
        out = []
        for threshold, (po, pu) in mp.over_under.items():
            conf = conf_map.get(f"over_under_{threshold}", 0.0)
            for sel, prob in [("over", po), ("under", pu)]:
                res = (
                    find_best_odds(odds_history, "totals", f"{sel}_{threshold}")
                    or find_best_odds(odds_history, "totals", f"totals_{threshold}_{sel}")
                    or find_best_odds(odds_history, "totals", f"{threshold}_{sel}")
                )
                if res is None:
                    continue
                best_odds, bookmaker = res
                value = compute_value(prob, best_odds)
                out.append(MarketCandidate(
                    market="over_under", selection=f"{sel}_{threshold}",
                    model_prob=prob, confidence=conf,
                    best_odds=best_odds, bookmaker=bookmaker,
                    value=value,
                ))
        return out

    def _build_btts_candidates(self, match, mp, conf_map, odds_history):
        out = []
        conf = conf_map.get("btts", 0.0)
        for sel, prob in [("yes", mp.btts[0]), ("no", mp.btts[1])]:
            res = find_best_odds(odds_history, "btts", sel)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            out.append(MarketCandidate(
                market="btts", selection=f"btts_{sel}",
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_dc_candidates(self, match, mp, conf_map, odds_history):
        out = []
        conf = conf_map.get("double_chance", 0.0)
        for sel, prob in mp.double_chance.items():
            res = find_best_odds(odds_history, "double_chance", sel)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            out.append(MarketCandidate(
                market="double_chance", selection=sel,
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_cs_candidates(self, match, mp, conf_map, odds_history):
        out = []
        conf = conf_map.get("correct_score", 0.0)
        # Only consider top 3 most likely scores (avoid diluting bankroll)
        for score, prob in mp.exact_score[:3]:
            res = find_best_odds(odds_history, "correct_score", score)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            # Correct score requires much higher confidence to bet
            adjusted_conf = conf * 0.5
            out.append(MarketCandidate(
                market="correct_score", selection=score,
                model_prob=prob, confidence=adjusted_conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_dnb_candidates(self, match, mp, conf_map, odds_history):
        out = []
        conf = conf_map.get("draw_no_bet", 0.0)
        for sel, prob in [("home", mp.dnb[0]), ("away", mp.dnb[1])]:
            res = find_best_odds(odds_history, "draw_no_bet", sel)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            out.append(MarketCandidate(
                market="draw_no_bet", selection=f"dnb_{sel}",
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out
