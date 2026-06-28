"""Feature 1: Recent form (xG/xGA + results over last N matches)."""
from __future__ import annotations

from typing import Any

from betbot.data.api_football import get_team_last_fixtures
from betbot.data.backfill import get_team_xg_by_name
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class FormFeature(Feature):
    name = "xg_form"
    weight = 0.20

    def __init__(self, last_n: int = 8):
        self.last_n = last_n

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        home_name = match.get("home_team_name", "")
        away_name = match.get("away_team_name", "")
        season = match.get("season")

        home_form = _team_form(home_id, home_name, season, self.last_n)
        away_form = _team_form(away_id, away_name, season, self.last_n)

        if home_form["missing"] and away_form["missing"]:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"home_form": home_form, "away_form": away_form},
                                 missing=True)

        # Difference in expected goal diff (xG - xGA) per match
        home_xg_diff = home_form["xg_per_match"] - home_form["xga_per_match"]
        away_xg_diff = away_form["xg_per_match"] - away_form["xga_per_match"]
        diff = home_xg_diff - away_xg_diff  # positive = home team better

        # Heuristic mapping: each 0.3 difference in xG_diff -> +3pp shift to home
        shift = max(-0.10, min(0.10, diff * 0.10))

        # Result-only form score (less predictive than xG but still informative)
        result_diff = home_form["form_score"] - away_form["form_score"]
        shift += max(-0.03, min(0.03, result_diff * 0.05))

        delta = (shift / 2, 0.0, -shift / 2)
        delta = normalize_delta(delta)

        confidence = 0.9 if (not home_form["missing"] and not away_form["missing"]) else 0.5

        return FeatureResult(
            delta=delta,
            confidence=confidence,
            raw={
                "home_form": home_form,
                "away_form": away_form,
                "xg_diff_diff": round(diff, 3),
                "form_score_diff": round(result_diff, 3),
            },
        )


def _team_form(team_id: int | None, team_name: str, season: int | None,
               last_n: int) -> dict[str, Any]:
    """Compute aggregate form for a team.

    Returns dict with: xg_per_match, xga_per_match, form_score, matches_count, missing.
    """
    out: dict[str, Any] = {
        "team_id": team_id, "team_name": team_name,
        "xg_per_match": 0.0, "xga_per_match": 0.0,
        "form_score": 0.5, "matches_count": 0, "missing": True,
    }

    fixtures = []
    if team_id:
        try:
            fixtures = get_team_last_fixtures(team_id, last_n=last_n, season=season)
        except Exception as exc:
            log.warning("get_team_last_fixtures failed for %s: %s", team_name, exc)

    # Fallback: football-data.org (free, current season)
    if not fixtures and team_id:
        try:
            from betbot.data.football_data_org import get_team_recent_matches
            fixtures = get_team_recent_matches(team_id, limit=last_n)
            if fixtures:
                log.debug("form fallback to football-data.org for %s", team_name)
        except Exception as exc:
            log.debug("football-data.org form fallback failed for %s: %s", team_name, exc)

    if not fixtures and team_name and season:
        xg_data = get_team_xg_by_name(team_name, season)
        if xg_data and xg_data.get("matches"):
            out.update({
                "xg_per_match": xg_data["xG_per_match"],
                "xga_per_match": xg_data["xGA_per_match"],
                "matches_count": xg_data["matches"],
                "missing": False,
            })
            return out

    if not fixtures:
        return out

    gf = ga = pts = 0
    n = 0
    for fx in fixtures:
        teams = fx.get("teams", {}) or {}
        goals = fx.get("goals", {}) or {}
        is_home = teams.get("home", {}).get("id") == team_id
        if is_home:
            team_gf = goals.get("home") or 0
            team_ga = goals.get("away") or 0
        else:
            team_gf = goals.get("away") or 0
            team_ga = goals.get("home") or 0
        gf += team_gf
        ga += team_ga
        if team_gf > team_ga:
            pts += 3
        elif team_gf == team_ga:
            pts += 1
        n += 1

    if n > 0:
        gpm = gf / n
        gapm = ga / n
        out["matches_count"] = n
        out["goals_per_match"] = gpm
        out["goals_conceded_per_match"] = gapm
        # Goals used as xG proxy when real xG unavailable
        out["xg_per_match"] = gpm
        out["xga_per_match"] = gapm
        out["form_score"] = pts / (3 * n)
        out["missing"] = False

    return out
