"""Confidence aggregator — combines weighted scoring + ML prediction.

Final confidence = w_weighted × confidence_weighted + w_ml × confidence_ml
when both are available; otherwise falls back to one of them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from betbot.config import settings
from betbot.logging_setup import get_logger
from betbot.models.ml_model import MLModel, MLPrediction
from betbot.models.poisson import GoalExpectation
from betbot.models.markets import MarketProbabilities

log = get_logger(__name__)


@dataclass
class HybridConfidence:
    """Aggregated confidence for one match (1X2 market)."""
    match_id: int
    p_1: float
    p_x: float
    p_2: float
    confidence: float
    weighted_confidence: float
    ml_confidence: float
    poisson_p_1: float
    poisson_p_x: float
    poisson_p_2: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "p_1": round(self.p_1, 4),
            "p_x": round(self.p_x, 4),
            "p_2": round(self.p_2, 4),
            "confidence": round(self.confidence, 4),
            "weighted_confidence": round(self.weighted_confidence, 4),
            "ml_confidence": round(self.ml_confidence, 4),
            "poisson_p_1": round(self.poisson_p_1, 4),
            "poisson_p_x": round(self.poisson_p_x, 4),
            "poisson_p_2": round(self.poisson_p_2, 4),
        }


class ConfidenceAggregator:
    """Combine weighted-feature confidence + ML confidence + Poisson priors."""

    def __init__(self, ml_model: MLModel | None = None):
        self.ml_model = ml_model or MLModel()
        self.w_weighted = settings.WEIGHTED_MODEL_WEIGHT
        self.w_ml = settings.ML_MODEL_WEIGHT

    def aggregate(self, match: dict[str, Any], feature_bundle, ml_features: dict[str, float],
                  poisson_p: tuple[float, float, float]) -> HybridConfidence:
        """Aggregate all signals into a final confidence.

        Poisson provides the prior. Feature deltas and ML provide adjustments.
        """
        p1_p, px_p, p2_p = poisson_p

        # Convert feature deltas to prob adjustments (clamped)
        f_home = feature_bundle.delta_home
        f_draw = feature_bundle.delta_draw
        f_away = feature_bundle.delta_away

        # Weighted confidence: how strongly features lean toward an outcome
        weighted_p1 = max(0.05, min(0.95, p1_p + f_home))
        weighted_px = max(0.05, min(0.95, px_p + f_draw))
        weighted_p2 = max(0.05, min(0.95, p2_p + f_away))

        # Renormalize
        total = weighted_p1 + weighted_px + weighted_p2
        weighted_p1, weighted_px, weighted_p2 = weighted_p1 / total, weighted_px / total, weighted_p2 / total

        weighted_conf = max(weighted_p1, weighted_px, weighted_p2)
        weighted_conf = weighted_conf - sorted([weighted_p1, weighted_px, weighted_p2])[1]

        # ML prediction
        ml_pred = self.ml_model.predict(ml_features)
        ml_conf = ml_pred.confidence if ml_pred.available else 0.0

        # Hybrid blend of weighted and ML probabilities
        if ml_pred.available:
            blended_p1 = self.w_weighted * weighted_p1 + self.w_ml * ml_pred.p_home
            blended_px = self.w_weighted * weighted_px + self.w_ml * ml_pred.p_draw
            blended_p2 = self.w_weighted * weighted_p2 + self.w_ml * ml_pred.p_away
            blended_conf = self.w_weighted * weighted_conf + self.w_ml * ml_conf
        else:
            blended_p1 = weighted_p1
            blended_px = weighted_px
            blended_p2 = weighted_p2
            blended_conf = weighted_conf

        # Renormalize
        total = blended_p1 + blended_px + blended_p2
        if total > 0:
            blended_p1, blended_px, blended_p2 = blended_p1 / total, blended_px / total, blended_p2 / total

        return HybridConfidence(
            match_id=match.get("match_id", 0),
            p_1=blended_p1, p_x=blended_px, p_2=blended_p2,
            confidence=blended_conf,
            weighted_confidence=weighted_conf,
            ml_confidence=ml_conf,
            poisson_p_1=p1_p, poisson_p_x=px_p, poisson_p_2=p2_p,
        )
