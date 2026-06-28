"""Understat.com scraper for xG/xGA data.

Scrapes https://understat.com/league/{league}/{season} for team-level xG data.
This is the most reliable free source for xG. Limited to ~1 req per 2s to respect site.
"""
from __future__ import annotations

import time
from typing import Any

from bs4 import BeautifulSoup

from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get_session
from betbot.logging_setup import get_logger

log = get_logger(__name__)

BASE_URL = "https://understat.com"
LEAGUE_PATHS: dict[str, str] = {
    "EPL": "EPL",
    "La_liga": "La_liga",
    "Bundesliga": "Bundesliga",
    "Serie_A": "Serie_A",
    "Ligue_1": "Ligue_1",
    "RFPL": "RFPL",
}


def _scrape(url: str, ttl: int = 86400) -> str:
    key = f"understat:{url}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    log.info("GET %s", url)
    resp = get_session().get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    text = resp.text
    cache_set(key, url, text, ttl_seconds=ttl)
    time.sleep(2)  # be polite
    return text


def get_league_season_data(league: str, season: int) -> list[dict[str, Any]]:
    """Get team-level xG stats for a league season.

    Returns a list of dicts with: team, xG, xGA, xG_diff, scored, missed, matches, npxG, npxGA.
    """
    if league not in LEAGUE_PATHS:
        log.warning("League %s not supported by Understat", league)
        return []
    url = f"{BASE_URL}/league/{LEAGUE_PATHS[league]}/{season}"
    try:
        html = _scrape(url)
    except Exception as exc:
        log.error("Failed to fetch Understat %s %s: %s", league, season, exc)
        return []

    soup = BeautifulSoup(html, "lxml")
    scripts = soup.find_all("script")
    teams_data: list[dict[str, Any]] = []

    for script in scripts:
        text = script.string or ""
        if "teamsData" not in text:
            continue
        # Parse the embedded JSON
        try:
            start = text.index('JSON.parse(\'')
            json_str = text[start + len('JSON.parse(\''):]
            end = json_str.rindex('\')')
            json_str = json_str[:end]
            # unescape
            json_str = json_str.encode().decode("unicode_escape")
            import json
            payload = json.loads(json_str)
        except (ValueError, json.JSONDecodeError) as exc:
            log.error("Parse error in Understat data for %s %s: %s", league, season, exc)
            continue

        for team_id, info in payload.items():
            history = info.get("history", [])
            if not history:
                continue
            n = len(history)
            xg = sum(float(m.get("xG", 0) or 0) for m in history)
            xga = sum(float(m.get("xGA", 0) or 0) for m in history)
            scored = sum(int(m.get("scored", 0) or 0) for m in history)
            missed = sum(int(m.get("missed", 0) or 0) for m in history)
            teams_data.append({
                "team": info.get("title", team_id),
                "team_id_understat": team_id,
                "matches": n,
                "xG": round(xg, 2),
                "xGA": round(xga, 2),
                "xG_per_match": round(xg / n, 2) if n else 0.0,
                "xGA_per_match": round(xga / n, 2) if n else 0.0,
                "goals_scored": scored,
                "goals_conceded": missed,
                "season": season,
                "league": league,
            })
        break

    return teams_data


def get_team_last_matches(league: str, season: int, team_name: str, last_n: int = 10) -> list[dict]:
    """Get individual match-level xG for a team (last N matches)."""
    if league not in LEAGUE_PATHS:
        return []
    url = f"{BASE_URL}/league/{LEAGUE_PATHS[league]}/{season}"
    try:
        html = _scrape(url)
    except Exception as exc:
        log.error("Failed to fetch team matches from Understat: %s", exc)
        return []

    soup = BeautifulSoup(html, "lxml")
    scripts = soup.find_all("script")
    matches: list[dict] = []

    for script in scripts:
        text = script.string or ""
        if "datesData" not in text:
            continue
        try:
            start = text.index('JSON.parse(\'')
            json_str = text[start + len('JSON.parse(\''):]
            end = json_str.rindex('\')')
            json_str = json_str[:end]
            json_str = json_str.encode().decode("unicode_escape")
            import json
            payload = json.loads(json_str)
        except (ValueError, json.JSONDecodeError):
            continue

        for row in payload.values():
            if not isinstance(row, dict):
                continue
            if row.get("a", {}).get("title") == team_name or row.get("h", {}).get("title") == team_name:
                matches.append({
                    "date": row.get("datetime"),
                    "home_team": row.get("h", {}).get("title"),
                    "away_team": row.get("a", {}).get("title"),
                    "home_goals": row.get("goals", {}).get("h"),
                    "away_goals": row.get("goals", {}).get("a"),
                    "home_xg": row.get("xG", {}).get("h"),
                    "away_xg": row.get("xG", {}).get("a"),
                })
        break

    matches.sort(key=lambda m: m.get("date") or "", reverse=True)
    return matches[:last_n]
