"""Decision engine — for each match, pick the SINGLE best market to bet on.

For every market we compute a per-selection confidence: the model's
probability for that selection minus the second-best probability in the
same market (the "margin"). This makes 'home wins by 10pp' more attractive
than 'home wins by 2pp', even when both meet the absolute confidence
threshold. The previous version used one shared confidence per market,
which let draws win on ties whenever the home selection had a slightly
negative value.

The bot then walks the candidates sorted by per-selection confidence and
picks the first one that passes both confidence AND value thresholds.
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


def _margin(prob: float, *other_probs: float) -> float:
    """Confidence in `prob` = prob − max(other_probs). 0 if negative."""
    return max(0.0, prob - (max(other_probs) if other_probs else 0.0))


@dataclass
class MarketCandidate:
    market: str
    selection: str
    model_prob: float
    confidence: float  # confidence in the selection itself (margin over runner-up)
    best_odds: float
    bookmaker: str
    value: float

    def meets_threshold(self) -> bool:
        if self.confidence < settings.CONFIDENCE_THRESHOLD:
            return False
        if self.value < settings.VALUE_THRESHOLD:
            return False
        if self.value > settings.MAX_SELECTION_VALUE:
            return False
        return True


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

        candidates.extend(self._build_1x2_candidates(market_probs, odds_history))
        candidates.extend(self._build_ou_candidates(market_probs, odds_history))
        candidates.extend(self._build_btts_candidates(market_probs, odds_history))
        candidates.extend(self._build_dc_candidates(market_probs, odds_history))
        candidates.extend(self._build_cs_candidates(market_probs, odds_history))
        candidates.extend(self._build_dnb_candidates(market_probs, odds_history))

        candidates.sort(key=lambda c: c.confidence, reverse=True)

        # Walk candidates by descending confidence and pick the first that
        # passes every threshold. Don't restrict to candidates[0] — that
        # silently discards good bets on other markets whenever the top one
        # has a marginally-negative value.
        selected = next((c for c in candidates if c.meets_threshold()), None)
        reason = ""
        if not candidates:
            reason = "no markets evaluated"
        elif selected is None:
            top = candidates[0]
            reason = (f"top candidate '{top.market}/{top.selection}' "
                      f"failed thresholds "
                      f"(conf={top.confidence:.2%} < {settings.CONFIDENCE_THRESHOLD:.0%} OR "
                      f"value={top.value:.2%} < {settings.VALUE_THRESHOLD:.0%})")

        return MatchDecision(
            match_id=match.get("match_id", 0),
            selected=selected,
            all_candidates=candidates,
            reason=reason,
        )

    def _build_1x2_candidates(self, mp, odds_history):
        probs = {"home": mp.p_1, "draw": mp.p_x, "away": mp.p_2}
        out = []
        for sel, prob in probs.items():
            # Anti-draw-spam: require the draw probability to dominate the
            # runner-up by MIN_DRAW_MARGIN before we even consider it. Close
            # matches where draw is barely ahead of one side are the typical
            # source of bogus "value" bets.
            if sel == "draw":
                others = [p for s, p in probs.items() if s != "draw"]
                if prob - max(others) < settings.MIN_DRAW_MARGIN:
                    continue
            res = find_best_odds(odds_history, "h2h", sel)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            # Per-selection confidence: this selection's prob minus the
            # best alternative in the same market.
            others = [p for s, p in probs.items() if s != sel]
            conf = _margin(prob, *others)
            out.append(MarketCandidate(
                market="1X2", selection=sel,
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_ou_candidates(self, mp, odds_history):
        out = []
        for threshold, (po, pu) in mp.over_under.items():
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
                conf = _margin(prob, pu if sel == "over" else po)
                out.append(MarketCandidate(
                    market="over_under", selection=f"{sel}_{threshold}",
                    model_prob=prob, confidence=conf,
                    best_odds=best_odds, bookmaker=bookmaker,
                    value=value,
                ))
        return out

    def _build_btts_candidates(self, mp, odds_history):
        out = []
        for sel, prob in [("yes", mp.btts[0]), ("no", mp.btts[1])]:
            res = (
                find_best_odds(odds_history, "btts", f"btts_{sel}")
                or find_best_odds(odds_history, "btts", sel)
            )
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            conf = _margin(prob, mp.btts[1] if sel == "yes" else mp.btts[0])
            out.append(MarketCandidate(
                market="btts", selection=f"btts_{sel}",
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_dc_candidates(self, mp, odds_history):
        out = []
        for sel, prob in mp.double_chance.items():
            res = find_best_odds(odds_history, "double_chance", sel)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            others = [p for s, p in mp.double_chance.items() if s != sel]
            conf = _margin(prob, *others)
            out.append(MarketCandidate(
                market="double_chance", selection=sel,
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_cs_candidates(self, mp, odds_history):
        out = []
        # Only consider top 3 most likely scores (avoid diluting bankroll).
        # Confidence = relative dominance vs the top score (a score with prob
        # 50% of the top gets conf 0.5).
        top = mp.exact_score[0][1] if mp.exact_score else 1.0
        for score, prob in mp.exact_score[:3]:
            res = find_best_odds(odds_history, "correct_score", score)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            conf = max(0.0, prob / top - 1.0) if top > 0 else 0.0
            out.append(MarketCandidate(
                market="correct_score", selection=score,
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out

    def _build_dnb_candidates(self, mp, odds_history):
        out = []
        for sel, prob in [("home", mp.dnb[0]), ("away", mp.dnb[1])]:
            res = find_best_odds(odds_history, "draw_no_bet", sel)
            if res is None:
                continue
            best_odds, bookmaker = res
            value = compute_value(prob, best_odds)
            conf = _margin(prob, mp.dnb[1] if sel == "home" else mp.dnb[0])
            out.append(MarketCandidate(
                market="draw_no_bet", selection=f"dnb_{sel}",
                model_prob=prob, confidence=conf,
                best_odds=best_odds, bookmaker=bookmaker,
                value=value,
            ))
        return out
