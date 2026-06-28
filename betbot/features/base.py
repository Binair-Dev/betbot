"""Base class for all match features.

Each feature module computes:
- raw values from various data sources
- a normalized impact on home/draw/away probabilities
- a confidence (0-1) of how reliable this signal is
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from betbot.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class FeatureResult:
    """Result of a single feature computation.

    delta: (delta_home, delta_draw, delta_away) — additive adjustments to base probs.
           e.g. (+0.05, -0.02, -0.03) means shift prob toward home by 5pp.
    confidence: 0-1, reliability of this signal.
    raw: dict of raw values used (for transparency / dashboard).
    missing: True if data unavailable — feature should be ignored in scoring.
    """
    delta: tuple[float, float, float]
    confidence: float
    raw: dict[str, Any]
    missing: bool = False

    @property
    def net_lean(self) -> float:
        """Net positive lean toward home in [-1, +1]. +1 = strong home, -1 = strong away."""
        return max(-1.0, min(1.0, self.delta[0] - self.delta[2]))


class Feature(ABC):
    name: str = "feature"
    weight: float = 0.0  # default; will be set from config

    @abstractmethod
    def compute(self, match: dict[str, Any]) -> FeatureResult:
        """Compute the feature for a given match dict.

        match dict contains:
            match_id, league_id, season, match_date, home_team_id, away_team_id,
            venue, referee, status, home_score, away_score,
            home_team_name, away_team_name
        """
        raise NotImplementedError


def normalize_delta(delta: tuple[float, float, float]) -> tuple[float, float, float]:
    """Clamp deltas so each is in [-0.2, +0.2] and they sum to zero (prob conservation)."""
    clamped = tuple(max(-0.2, min(0.2, d)) for d in delta)
    total = sum(clamped)
    zeroed = (clamped[0] - total / 3, clamped[1] - total / 3, clamped[2] - total / 3)
    return zeroed
