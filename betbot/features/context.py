"""Feature 5: Match context — stakes, derby, congested schedule, manager change.

Stakes: derived from standings gap and league position context.
Derby: detected by city/region overlap or known rivalries.
Congested: count of matches in last 7 days vs opponent.
Manager change: would require news scraping — placeholder for now.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from betbot.data.api_football import get_standings
from betbot.db.repository import query
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class ContextFeature(Feature):
    name = "context"
    weight = 0.10

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")
        season = match.get("season")
        match_date = match.get("match_date")

        # --- Stakes (standings-based) ---
        stakes_delta = self._stakes_delta(home_id, away_id, league_id, season)

        # --- Derby / rivalry detection ---
        derby_delta = self._derby_delta(home_id, away_id, league_id, season)

        # --- Congested schedule ---
        fatigue_delta = self._congested_delta(home_id, away_id, match_date)

        # Combine
        combined = (
            stakes_delta[0] + derby_delta[0] + fatigue_delta[0],
            stakes_delta[1] + derby_delta[1] + fatigue_delta[1],
            stakes_delta[2] + derby_delta[2] + fatigue_delta[2],
        )
        delta = normalize_delta(combined)

        return FeatureResult(
            delta=delta,
            confidence=0.6,
            raw={
                "stakes": stakes_delta,
                "derby": derby_delta,
                "congested": fatigue_delta,
            },
        )

    def _stakes_delta(self, home_id: int | None, away_id: int | None,
                       league_id: int | None, season: int | None) -> tuple[float, float, float]:
        """Stakes: teams in relegation fight or title race have asymmetric motivation.

        Returns delta tuple. We compare position differences.
        """
        if not (home_id and away_id and league_id and season):
            return (0.0, 0.0, 0.0)
        try:
            standings = get_standings(league_id, season)
        except Exception:
            return (0.0, 0.0, 0.0)

        home_pos = None
        away_pos = None
        for entry in standings:
            tid = entry.get("team", {}).get("id")
            if tid == home_id:
                home_pos = entry.get("rank")
            elif tid == away_id:
                away_pos = entry.get("rank")

        if home_pos is None or away_pos is None:
            return (0.0, 0.0, 0.0)

        # Higher-stakes teams (top 4 / bottom 3) get a small motivation boost.
        # Mid-table teams have less to play for.
        n_teams = len(standings)
        high_stakes_positions = {1, 2, 3, 4, n_teams - 2, n_teams - 1, n_teams}
        home_stakes = home_pos in high_stakes_positions
        away_stakes = away_pos in high_stakes_positions

        if home_stakes and not away_stakes:
            return (0.02, 0.0, -0.02)
        if away_stakes and not home_stakes:
            return (-0.02, 0.0, 0.02)
        if home_stakes and away_stakes:
            return (0.0, 0.0, 0.0)
        return (-0.01, 0.0, 0.01)  # both mid-table: slightly more draws

    def _derby_delta(self, home_id: int | None, away_id: int | None,
                     league_id: int | None, season: int | None) -> tuple[float, float, float]:
        """Derby matches: more conservative, more draws, lower scoring.

        We approximate by H2H frequency in last 5y — if they've played >10 times,
        consider it a derby-like fixture.
        """
        if not (home_id and away_id):
            return (0.0, 0.0, 0.0)
        rows = query(
            """SELECT COUNT(*) AS c FROM matches
               WHERE ((home_team_id = ? AND away_team_id = ?)
                   OR (home_team_id = ? AND away_team_id = ?))
                   AND match_date >= date('now', '-5 years')""",
            (home_id, away_id, away_id, home_id),
        )
        h2h_count = rows[0]["c"] if rows else 0
        if h2h_count >= 12:
            return (-0.02, 0.03, -0.02)  # more draws
        return (0.0, 0.0, 0.0)

    def _congested_delta(self, home_id: int | None, away_id: int | None,
                         match_date: datetime | None) -> tuple[float, float, float]:
        """Congested schedule: team with more matches in last 7 days is more fatigued.

        Convention: in UEFA weeks, often one team plays midweek. Detect this.
        """
        if not (home_id and away_id and match_date):
            return (0.0, 0.0, 0.0)

        if isinstance(match_date, str):
            try:
                match_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            except ValueError:
                return (0.0, 0.0, 0.0)

        window_start = match_date - timedelta(days=7)
        window_end = match_date

        rows = query(
            """SELECT home_team_id, away_team_id FROM matches
               WHERE (home_team_id = ? OR away_team_id = ?
                   OR home_team_id = ? OR away_team_id = ?)
                   AND match_date BETWEEN ? AND ?
                   AND match_id != ?""",
            (home_id, home_id, away_id, away_id,
             window_start.isoformat(), window_end.isoformat(), -1),
        )
        home_matches = sum(1 for r in rows
                           if r["home_team_id"] == home_id or r["away_team_id"] == home_id)
        away_matches = sum(1 for r in rows
                           if r["home_team_id"] == away_id or r["away_team_id"] == away_id)

        # Home team has home advantage so being slightly more fatigued is OK;
        # the bigger signal is when AWAY has played fewer matches (rest advantage).
        diff = away_matches - home_matches
        if diff >= 2:
            return (-0.02, 0.01, 0.01)  # home is more fatigued, slight disadvantage
        elif diff <= -2:
            return (0.01, 0.01, -0.02)  # away more fatigued
        return (0.0, 0.0, 0.0)
