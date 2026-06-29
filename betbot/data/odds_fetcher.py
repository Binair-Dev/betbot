"""Odds fetching — pull latest odds for upcoming matches from The Odds API."""
from __future__ import annotations

import json
from typing import Any

from betbot.config import settings
from betbot.data.odds_api import find_soccer_keys, get_odds_for_sport
from betbot.db.repository import execute
from betbot.features.odds_features import persist_odds_snapshot
from betbot.logging_setup import get_logger

log = get_logger(__name__)


# Mapping of API-Football league IDs to The Odds API sport_keys
LEAGUE_TO_SPORT_KEY: dict[int, str] = {
    39: "soccer_epl",
    40: "soccer_england_championship",
    61: "soccer_france_ligue_one",
    62: "soccer_france_ligue_two",
    78: "soccer_germany_bundesliga",
    79: "soccer_germany_bundesliga_2",
    135: "soccer_italy_serie_a",
    136: "soccer_italy_serie_b",
    140: "soccer_spain_la_liga",
    141: "soccer_spain_segunda_division",
    88: "soccer_netherlands_eredivisie",
    94: "soccer_portugal_primeira_liga",
    144: "soccer_belgium_first_div",
    2: "soccer_uefa_champs_league",
    3: "soccer_uefa_europa_league",
    848: "soccer_uefa_europa_conference_league",
    1: "soccer_fifa_world_cup",
    4: "soccer_euro_championship",
    5: "soccer_uefa_nations_league",
}


def fetch_odds_for_today(matches: list[dict]) -> dict[int, list[dict]]:
    """Fetch odds for all upcoming matches. Returns match_id -> [odds rows]."""
    if not settings.ODDS_API_KEY:
        log.warning("ODDS_API_KEY not set — skipping odds fetch")
        return {}

    result: dict[int, list[dict]] = {}
    sport_keys_used: set[str] = set()

    for fx in matches:
        league_id = fx.get("league", {}).get("id")
        if league_id not in LEAGUE_TO_SPORT_KEY:
            continue
        sport_keys_used.add(LEAGUE_TO_SPORT_KEY[league_id])

    log.info("Fetching odds for %d leagues", len(sport_keys_used))

    for sport_key in sport_keys_used:
        events = None
        for markets in ("h2h,totals,btts,double_chance,correct_score", "h2h,totals,btts", "h2h"):
            try:
                events = get_odds_for_sport(sport_key, markets=markets, regions="eu,uk")
                break
            except Exception as exc:
                if "422" in str(exc) or "Unprocessable" in str(exc):
                    log.debug("Markets %r unsupported for %s, retrying with fewer", markets, sport_key)
                    continue
                log.warning("Failed to fetch odds for %s: %s", sport_key, exc)
                break
        if not events:
            continue
        for ev in events:
            odds_rows = _normalize_event_odds(ev)
            match_id = _find_match_id(ev, matches)
            if match_id:
                result[match_id] = odds_rows
                _persist_event_odds(match_id, ev, odds_rows)

    log.info("Fetched odds for %d matches", len(result))
    return result


def _normalize_event_odds(event: dict) -> list[dict]:
    """Convert The Odds API event format to a flat list of (market, selection, odds, bookmaker)."""
    rows = []
    event_id = event.get("id")
    for bookmaker in event.get("bookmakers", []) or []:
        book_name = bookmaker.get("title", bookmaker.get("key", ""))
        for market in bookmaker.get("markets", []) or []:
            market_key = market.get("key", "")
            for outcome in market.get("outcomes", []) or []:
                rows.append({
                    "event_id": event_id,
                    "bookmaker": book_name,
                    "market": _map_market_key(market_key),
                    "selection": _map_selection(outcome),
                    "odds": float(outcome.get("price", 0)),
                    "point": outcome.get("point"),
                })
    return rows


def _map_market_key(key: str) -> str:
    """Normalize market key to our internal vocabulary."""
    mapping = {
        "h2h": "h2h",
        "totals": "totals",
        "spreads": "spreads",
        "btts": "btts",
        "double_chance": "double_chance",
        "draw_no_bet": "draw_no_bet",
        "correct_score": "correct_score",
    }
    return mapping.get(key, key)


def _map_selection(outcome: dict) -> str:
    """Normalize selection name."""
    name = outcome.get("name", "")
    point = outcome.get("point")
    if point is not None:
        if "Over" in name:
            return f"over_{point}"
        if "Under" in name:
            return f"under_{point}"
    return name.lower()


def _find_match_id(event: dict, matches: list[dict]) -> int | None:
    """Cross-reference an Odds API event with API-Football matches by team names."""
    home_name = event.get("home_team", "").lower()
    away_name = event.get("away_team", "").lower()
    for fx in matches:
        h = (fx.get("teams", {}).get("home", {}) or {}).get("name", "").lower()
        a = (fx.get("teams", {}).get("away", {}) or {}).get("name", "").lower()
        if (home_name in h or h in home_name) and (away_name in a or a in away_name):
            return fx.get("fixture", {}).get("id")
    return None


def _persist_event_odds(match_id: int, event: dict, rows: list[dict]) -> None:
    """Persist the full odds snapshot to the database for the match."""
    # Group by bookmaker + market + selection
    by_bm: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        bm = row["bookmaker"]
        m = row["market"]
        s = row["selection"]
        by_bm.setdefault(bm, {}).setdefault(m, {})[s] = row["odds"]
    for bm, markets in by_bm.items():
        for m, sels in markets.items():
            imp = {s: 1 / o if o > 1 else 0 for s, o in sels.items()}
            persist_odds_snapshot(match_id, m, bm, sels, imp)
