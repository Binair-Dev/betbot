"""Feature 10: Fatigue & travel impact."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from betbot.db.repository import query
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class FatigueFeature(Feature):
    name = "fatigue"
    weight = 0.05

    def __init__(self, rest_advantage_thresh_days: float = 2.0):
        self.thresh = rest_advantage_thresh_days

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        match_date = match.get("match_date")
        if not (home_id and away_id and match_date):
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "missing data"}, missing=True)

        if isinstance(match_date, str):
            try:
                match_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            except ValueError:
                return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                     raw={"reason": "bad date"}, missing=True)

        home_rest = _days_since_last_match(home_id, match_date)
        away_rest = _days_since_last_match(away_id, match_date)

        delta = (0.0, 0.0, 0.0)
        reason = "no advantage"
        # Away team with less rest (more fatigued) → small disadvantage
        if home_rest is not None and away_rest is not None:
            diff = away_rest - home_rest  # negative = away has less rest
            if diff < -self.thresh:
                delta = (0.015, 0.005, -0.020)
                reason = "away_more_fatigued"
            elif diff > self.thresh:
                delta = (-0.015, -0.005, 0.020)
                reason = "home_more_fatigued"

        delta = (delta[0], delta[1] - 0.005, delta[2]) if delta != (0.0, 0.0, 0.0) else delta
        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.6,
            raw={
                "home_rest_days": home_rest,
                "away_rest_days": away_rest,
                "reason": reason,
            },
        )


def _days_since_last_match(team_id: int, match_date: datetime) -> float | None:
    """Days since the team's last match before `match_date`."""
    rows = query(
        """SELECT match_date FROM matches
           WHERE (home_team_id = ? OR away_team_id = ?)
             AND match_date < ?
             AND status = 'FT'
           ORDER BY match_date DESC
           LIMIT 1""",
        (team_id, team_id, match_date.isoformat()),
    )
    if not rows:
        return None
    last_date_raw = rows[0]["match_date"]
    if isinstance(last_date_raw, str):
        try:
            last_date = datetime.fromisoformat(last_date_raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        last_date = last_date_raw
    diff = (match_date - last_date).total_seconds() / 86400.0
    return round(diff, 2)
