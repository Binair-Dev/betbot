"""Settle pending bets by fetching match results.

Real implementation will:
1. Find all pending bets
2. Fetch each match's final score from API-Football
3. Determine the actual outcome of the bet
4. Mark the bet won/lost and update bankroll
"""
from __future__ import annotations

import json
from typing import Any

from betbot.betting.simulator import settle_bet
from betbot.data.api_football import get_fixture_by_id
from betbot.db.repository import execute, query, query_one
from betbot.logging_setup import get_logger

log = get_logger(__name__)


def settle_pending_bets() -> int:
    """Settle all pending bets whose matches are finished."""
    rows = query("""
        SELECT b.id AS bet_id, b.match_id, b.market, b.selection, b.odds, b.stake,
               m.home_score, m.away_score, m.status
        FROM bets b
        JOIN matches m ON m.match_id = b.match_id
        WHERE b.status = 'pending'
          AND m.status = 'FT'
          AND m.home_score IS NOT NULL
          AND m.away_score IS NOT NULL
    """)
    if not rows:
        log.info("No pending bets to settle")
        return 0

    count = 0
    for r in rows:
        won = _outcome_matches(r["market"], r["selection"],
                               r["home_score"], r["away_score"])
        settle_bet(r["bet_id"], won, r["odds"], r["stake"])
        count += 1
    log.info("Settled %d bets", count)
    return count


def settle_pending_bets_dry_run() -> dict[str, int]:
    """Settle pending bets based on stored match scores (used by backtest)."""
    rows = query("""
        SELECT b.id AS bet_id, b.market, b.selection, b.odds, b.stake,
               m.home_score, m.away_score
        FROM bets b
        JOIN matches m ON m.match_id = b.match_id
        WHERE b.status = 'pending'
          AND m.status = 'FT'
          AND m.home_score IS NOT NULL
          AND m.away_score IS NOT NULL
    """)
    summary = {"won": 0, "lost": 0, "void": 0}
    for r in rows:
        won = _outcome_matches(r["market"], r["selection"],
                               r["home_score"], r["away_score"])
        if won:
            summary["won"] += 1
        else:
            summary["lost"] += 1
    return summary


def _outcome_matches(market: str, selection: str, home: int, away: int) -> bool:
    """Determine if a bet wins given the actual score."""
    if market == "1X2":
        if selection == "home":
            return home > away
        if selection == "draw":
            return home == away
        if selection == "away":
            return home < away
    elif market == "over_under":
        # selection format: "over_2.5" or "under_2.5"
        try:
            _, threshold_str = selection.split("_")
            threshold = float(threshold_str)
        except (ValueError, AttributeError):
            return False
        total = home + away
        if selection.startswith("over"):
            return total > threshold
        return total < threshold
    elif market == "btts":
        # selection: "btts_yes" / "btts_no"
        both = home >= 1 and away >= 1
        return (selection == "btts_yes" and both) or (selection == "btts_no" and not both)
    elif market == "double_chance":
        # selection: "1X" / "X2" / "12"
        h = home > away
        d = home == away
        a = home < away
        if selection == "1X":
            return h or d
        if selection == "X2":
            return d or a
        if selection == "12":
            return h or a
    elif market == "correct_score":
        # selection: "2-1" etc.
        return selection == f"{home}-{away}"
    elif market == "draw_no_bet":
        # selection: "dnb_home" / "dnb_away"
        if home == away:
            return False  # push → void
        if selection == "dnb_home":
            return home > away
        if selection == "dnb_away":
            return home < away
    return False
