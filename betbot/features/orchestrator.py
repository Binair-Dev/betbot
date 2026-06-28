"""Feature orchestrator — runs all features for a given match.

Output: aggregated delta + per-feature breakdown for dashboard/transparency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from betbot.config import settings
from betbot.features.conditions import ConditionsFeature
from betbot.features.context import ContextFeature
from betbot.features.elo import EloFeature
from betbot.features.fatigue import FatigueFeature
from betbot.features.form import FormFeature
from betbot.features.home_advantage import HomeAdvantageFeature
from betbot.features.injuries import InjuryFeature
from betbot.features.odds_features import (
    MarketBiasFeature,
    OddsMovementFeature,
    OddsValueFeature,
)
from betbot.features.players import PlayersFeature
from betbot.features.referee import RefereeFeature
from betbot.features.setpieces import SetPiecesFeature
from betbot.features.soft_factors import SoftFactorsFeature
from betbot.features.styles import StylesFeature
from betbot.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class FeatureBundle:
    """Aggregated feature output for one match."""
    match_id: int
    delta_home: float
    delta_draw: float
    delta_away: float
    confidence: float
    breakdown: dict[str, dict[str, Any]]
    missing_features: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "delta_home": round(self.delta_home, 4),
            "delta_draw": round(self.delta_draw, 4),
            "delta_away": round(self.delta_away, 4),
            "confidence": round(self.confidence, 4),
            "breakdown": self.breakdown,
            "missing_features": self.missing_features,
        }


class FeatureOrchestrator:
    """Run all features and aggregate their deltas using configured weights."""

    def __init__(self):
        self.features = {
            "xg_form": FormFeature(),
            "elo": EloFeature(),
            "home_advantage": HomeAdvantageFeature(),
            "injuries": InjuryFeature(),
            "context": ContextFeature(),
            "styles": StylesFeature(),
            "odds_value": OddsValueFeature(),
            "conditions": ConditionsFeature(),
            "referee": RefereeFeature(),
            "fatigue": FatigueFeature(),
            "players": PlayersFeature(),
            "setpieces": SetPiecesFeature(),
            "soft_factors": SoftFactorsFeature(),
            "odds_movement": OddsMovementFeature(),
            "market_bias": MarketBiasFeature(),
        }
        self.weights = settings.FEATURE_WEIGHTS

    def run(self, match: dict[str, Any]) -> FeatureBundle:
        weighted_home = 0.0
        weighted_draw = 0.0
        weighted_away = 0.0
        weight_sum = 0.0
        confidence_sum = 0.0
        breakdown: dict[str, dict[str, Any]] = {}
        missing: list[str] = []

        for feat_name, feat in self.features.items():
            try:
                result = feat.compute(match)
            except Exception as exc:
                log.exception("Feature %s failed for match %s: %s", feat_name, match.get("match_id"), exc)
                continue

            if result.missing:
                missing.append(feat_name)
                breakdown[feat_name] = {"missing": True, "raw": result.raw}
                continue

            w = self.weights.get(feat_name, feat.weight)
            weighted_home += result.delta[0] * w
            weighted_draw += result.delta[1] * w
            weighted_away += result.delta[2] * w
            weight_sum += w
            confidence_sum += result.confidence * w

            breakdown[feat_name] = {
                "delta": list(result.delta),
                "confidence": round(result.confidence, 3),
                "weight": round(w, 3),
                "raw": result.raw,
            }

        confidence = (confidence_sum / weight_sum) if weight_sum > 0 else 0.0

        return FeatureBundle(
            match_id=match.get("match_id", 0),
            delta_home=weighted_home,
            delta_draw=weighted_draw,
            delta_away=weighted_away,
            confidence=confidence,
            breakdown=breakdown,
            missing_features=missing,
        )
