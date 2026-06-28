"""Football-Data.co.uk loader — free CSV source for historical results + closing odds.

This is the free, no-API-quota source of historical data we'll use to train the ML
model. Each CSV contains:
- Final scores (FTHG, FTAG, FTR)
- Half-time scores
- Closing odds from major bookmakers (Bet365, Pinnacle, William Hill, etc.)
- Match stats (shots, corners, cards)

Endpoint pattern: https://www.football-data.co.uk/mmz4281/{YYZZ}/{LeagueCode}.csv
Where YYZZ is the season (e.g. 2324 = 2023/24).

League codes: E0 (EPL), E1 (Championship), SP1 (La Liga), D1 (Bundesliga),
              I1 (Serie A), F1 (Ligue 1), N1 (Eredivisie), P1 (Liga Portugal),
              B1 (Jupiler Pro League)
"""
from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from betbot.config import settings
from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get_session
from betbot.logging_setup import get_logger

log = get_logger(__name__)

BASE_URL = "https://www.football-data.co.uk/mmz4281"

# Map our API-Football league IDs to football-data.co.uk codes + league names
LEAGUE_MAP: dict[int, dict[str, str]] = {
    39:  {"code": "E0",  "name": "Premier League"},
    40:  {"code": "E1",  "name": "Championship"},
    61:  {"code": "F1",  "name": "Ligue 1"},
    62:  {"code": "F2",  "name": "Ligue 2"},
    78:  {"code": "D1",  "name": "Bundesliga"},
    79:  {"code": "D2",  "name": "Bundesliga 2"},
    135: {"code": "I1",  "name": "Serie A"},
    136: {"code": "I2",  "name": "Serie B"},
    140: {"code": "SP1", "name": "La Liga"},
    141: {"code": "SP2", "name": "La Liga 2"},
    88:  {"code": "N1",  "name": "Eredivisie"},
    94:  {"code": "P1",  "name": "Liga Portugal"},
    144: {"code": "B1",  "name": "Jupiler Pro League"},
}


def season_to_code(season: int) -> str:
    """Convert a calendar year to the YYZZ season code (e.g. 2023 -> '2324')."""
    yy = season % 100
    zz = (season + 1) % 100
    return f"{yy:02d}{zz:02d}"


def fetch_league_season(league_id: int, season: int) -> pd.DataFrame:
    """Fetch a single league+season CSV from football-data.co.uk. Cached 30 days."""
    info = LEAGUE_MAP.get(league_id)
    if not info:
        log.warning("League %s not available on football-data.co.uk", league_id)
        return pd.DataFrame()

    code = info["code"]
    season_code = season_to_code(season)
    url = f"{BASE_URL}/{season_code}/{code}.csv"

    cache_key = f"footballdata:{league_id}:{season}"
    cached = cache_get(cache_key)
    if cached is not None:
        try:
            return pd.read_csv(StringIO(cached))
        except Exception:
            pass

    try:
        log.info("Fetching %s season %s from football-data.co.uk", code, season)
        resp = get_session().get(url, timeout=30)
        if resp.status_code == 404:
            log.warning("No data for %s season %s (404)", code, season)
            return pd.DataFrame()
        resp.raise_for_status()
        cache_set(cache_key, "football_data_csv", resp.text, ttl_seconds=30 * 86400)
        return pd.read_csv(StringIO(resp.text))
    except Exception as exc:
        log.warning("Failed to fetch %s %s: %s", code, season, exc)
        return pd.DataFrame()


def fetch_multiple_seasons(league_id: int, seasons: list[int]) -> pd.DataFrame:
    """Fetch multiple seasons for a league, concat them."""
    dfs = []
    for s in seasons:
        df = fetch_league_season(league_id, s)
        if not df.empty:
            df = df.assign(__season=s)
            dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def fetch_all_target_leagues(seasons: list[int] | None = None) -> pd.DataFrame:
    """Fetch historical data for all target leagues."""
    if seasons is None:
        from datetime import datetime
        current_year = datetime.now().year
        current_month = datetime.now().month
        if current_month >= 7:
            current_season_start = current_year
        else:
            current_season_start = current_year - 1
        seasons = list(range(current_season_start - 3, current_season_start + 1))

    all_dfs = []
    for league_id in settings.TARGET_LEAGUES:
        if league_id not in LEAGUE_MAP:
            continue
        df = fetch_multiple_seasons(league_id, seasons)
        if not df.empty:
            df = df.assign(
                __league_id=league_id,
                __league_name=LEAGUE_MAP[league_id]["name"],
            )
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


def normalize_for_training(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the football-data.co.uk DataFrame to our training schema.

    Output columns: match_date, home_team, away_team, home_score, away_score,
                    outcome (0=away, 1=draw, 2=home), odds_home, odds_draw, odds_away,
                    over_25, under_25, league_id, season
    """
    if df.empty:
        return df

    df = df.copy()

    # Parse date — format is DD/MM/YYYY
    df["match_date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=["match_date"])

    df["home_score"] = pd.to_numeric(df.get("FTHG"), errors="coerce")
    df["away_score"] = pd.to_numeric(df.get("FTAG"), errors="coerce")
    df = df.dropna(subset=["home_score", "away_score"])

    # Outcome: 0=away win, 1=draw, 2=home win
    def outcome(row):
        if row["home_score"] > row["away_score"]:
            return 2
        elif row["home_score"] < row["away_score"]:
            return 0
        return 1
    df["outcome"] = df.apply(outcome, axis=1)

    # Closing odds — prefer Bet365, fall back to Pinnacle, then Avg
    for col_out, candidates in [
        ("odds_home", ["B365H", "PSH", "AvgH", "MaxH"]),
        ("odds_draw", ["B365D", "PSD", "AvgD", "MaxD"]),
        ("odds_away", ["B365A", "PSA", "AvgA", "MaxA"]),
        ("odds_over_25", ["B365>2.5", "P>2.5", "Avg>2.5", "Max>2.5"]),
        ("odds_under_25", ["B365<2.5", "P<2.5", "Avg<2.5", "Max<2.5"]),
    ]:
        for c in candidates:
            if c in df.columns:
                df[col_out] = pd.to_numeric(df[c], errors="coerce")
                if df[col_out].notna().sum() > 0:
                    break

    # Implied probabilities (de-vigged later)
    for side in ("home", "draw", "away"):
        df[f"implied_{side}"] = 1.0 / df[f"odds_{side}"].replace(0, float("nan"))

    # Rename teams to match our naming
    df = df.rename(columns={"HomeTeam": "home_team", "AwayTeam": "away_team"})

    # Keep only useful columns
    keep = [
        "match_date", "home_team", "away_team", "home_score", "away_score",
        "outcome", "odds_home", "odds_draw", "odds_away",
        "odds_over_25", "odds_under_25",
        "implied_home", "implied_draw", "implied_away",
        "__league_id", "__league_name", "__season",
    ]
    keep = [c for c in keep if c in df.columns]
    return df[keep].dropna(subset=["odds_home", "odds_draw", "odds_away"]).reset_index(drop=True)


def build_training_set(seasons: list[int] | None = None,
                        min_matches: int = 500) -> pd.DataFrame:
    """Build a normalized training set ready for ML.

    Returns DataFrame with our standard schema (compatible with build_training_dataframe
    in ml_model.py).
    """
    raw = fetch_all_target_leagues(seasons)
    if raw.empty:
        log.warning("No training data fetched from football-data.co.uk")
        return raw

    normalized = normalize_for_training(raw)
    if len(normalized) < min_matches:
        log.warning("Only %d matches available (need %d)", len(normalized), min_matches)
    log.info("Built training set with %d matches", len(normalized))
    return normalized
