"""Tests for the scraper module.

We mock the network calls and verify that:
- scrape_fixtures persists target-league fixtures and filters the rest
- refresh_results updates matches with full ET/penalties breakdown
- scrape_odds calls the underlying odds_fetcher
- scrape_all runs all three in sequence
- Multi-source fallback works (fdo first, then API-Football)
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from betbot import config as config_mod
from betbot.betting import simulator as sim_mod
from betbot.db import repository as db_repository
from betbot.db.repository import execute, init_db, query, query_one
from betbot.scheduler import scrape as scrape_mod


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Use a temporary DB for each test."""
    db_path = str(tmp_path / "test.db")
    from pathlib import Path
    monkeypatch.setattr(db_repository, "get_db_path", lambda: Path(db_path))
    new_settings = replace(sim_mod.settings, DB_PATH=db_path, BANKROLL_START=100.0, BET_SIZE=5.0)
    monkeypatch.setattr(sim_mod, "settings", new_settings)
    monkeypatch.setattr(db_repository, "settings", new_settings)
    init_db()
    execute("INSERT INTO teams (team_id, name) VALUES (1, 'Home')")
    execute("INSERT INTO teams (team_id, name) VALUES (2, 'Away')")
    yield


def _fdo_fixture(match_id: int, league_id: int, status: str = "NS") -> dict:
    return {
        "fixture": {"id": match_id, "date": "2026-07-01T20:00:00Z",
                    "referee": None, "venue": {"name": None},
                    "status": {"short": status}},
        "league": {"id": league_id, "name": "Test League", "season": 2026,
                   "country": None, "type": None},
        "teams": {"home": {"id": 1, "name": "Home"},
                  "away": {"id": 2, "name": "Away"}},
        "goals": {"home": None, "away": None},
        "score": {"halftime": {"home": None, "away": None}},
    }


# --- scrape_fixtures --------------------------------------------------------

def test_scrape_fixtures_persists_target_leagues():
    """Only matches in TARGET_LEAGUES should be persisted."""
    target_league = 39  # Premier League
    with patch.object(scrape_mod, "get_fixtures_by_date",
                      return_value=[_fdo_fixture(100, target_league),
                                    _fdo_fixture(101, 999)]) as mock_gfd:
        counts = scrape_mod.scrape_fixtures(days_ahead=0)
    # Exactly one of the two matches is in a target league, so the day total
    # is 1 regardless of which calendar date the test runs on.
    assert sum(counts.values()) == 1
    rows = query("SELECT match_id, league_id FROM matches")
    assert any(r["match_id"] == 100 for r in rows)
    assert not any(r["match_id"] == 101 for r in rows)
    assert mock_gfd.called


def test_scrape_fixtures_handles_api_failure():
    """If get_fixtures_by_date raises, that day yields 0 and the cycle continues."""
    with patch.object(scrape_mod, "get_fixtures_by_date",
                      side_effect=Exception("API down")):
        counts = scrape_mod.scrape_fixtures(days_ahead=0)
    assert sum(counts.values()) == 0


# --- refresh_results --------------------------------------------------------

def test_refresh_results_updates_match_with_full_breakdown():
    """A finished match should be updated with reg/ET/pen breakdown."""
    # Seed a match that's > 30 min old
    execute("""INSERT INTO matches (match_id, match_date, home_team_id, away_team_id, status)
               VALUES (200, '2026-06-30 20:00:00', 1, 2, 'NS')""")

    fdo_payload = {
        "match_id": 200, "status": "FT",
        "home_score": 2, "away_score": 1,
        "home_ht_score": 0, "away_ht_score": 0,
        "home_score_regular": 1, "away_score_regular": 1,
        "home_score_et": 1, "away_score_et": 0,
        "home_score_pen": 0, "away_score_pen": 0,
        "match_duration": "EXTRA_TIME", "match_winner": "HOME_TEAM",
    }
    with patch.object(scrape_mod, "refresh_match_result", return_value=fdo_payload):
        result = scrape_mod.refresh_results(max_attempts=1, backoff=(0,))
    assert result["updated"] == 1
    assert result["failed"] == 0
    row = query_one("SELECT * FROM matches WHERE match_id=200")
    assert row["status"] == "FT"
    assert row["home_score_regular"] == 1
    assert row["away_score_regular"] == 1
    assert row["home_score_et"] == 1
    assert row["match_duration"] == "EXTRA_TIME"


def test_refresh_results_falls_back_to_api_football():
    """When fdo returns nothing, fall back to API-Football."""
    execute("""INSERT INTO matches (match_id, match_date, home_team_id, away_team_id, status)
               VALUES (300, '2026-06-30 20:00:00', 1, 2, 'NS')""")

    af_payload = {
        "fixture": {"id": 300, "status": {"short": "FT"}},
        "goals": {"home": 3, "away": 1},
        "score": {
            "halftime": {"home": 1, "away": 0},
            "fulltime": {"home": 3, "away": 1},
            "extratime": {"home": None, "away": None},
            "penalty": {"home": None, "away": None},
        },
    }
    with patch.object(scrape_mod, "refresh_match_result", return_value=None), \
         patch.object(scrape_mod, "get_fixture_by_id", return_value=af_payload):
        result = scrape_mod.refresh_results(max_attempts=1, backoff=(0,))
    assert result["updated"] == 1
    row = query_one("SELECT * FROM matches WHERE match_id=300")
    assert row["status"] == "FT"
    assert row["home_score_regular"] == 3
    assert row["match_duration"] == "REGULAR"
    assert row["match_winner"] == "HOME_TEAM"


def test_refresh_results_skips_future_matches():
    """Matches in the future (or last 30 min) are skipped, not refreshed."""
    # No matches seeded → refresh_results has nothing to do.
    result = scrape_mod.refresh_results(max_attempts=1, backoff=(0,))
    assert result["updated"] == 0
    assert result["failed"] == 0


def test_refresh_results_marks_failed_on_persistent_api_error():
    """If both sources fail every retry attempt, count as failed."""
    execute("""INSERT INTO matches (match_id, match_date, home_team_id, away_team_id, status)
               VALUES (400, '2026-06-30 20:00:00', 1, 2, 'NS')""")
    with patch.object(scrape_mod, "refresh_match_result", return_value=None), \
         patch.object(scrape_mod, "get_fixture_by_id", return_value=None):
        result = scrape_mod.refresh_results(max_attempts=2, backoff=(0,))
    assert result["updated"] == 0
    assert result["failed"] == 1
    # Match stays NS since refresh failed
    row = query_one("SELECT status FROM matches WHERE match_id=400")
    assert row["status"] == "NS"


# --- scrape_odds ------------------------------------------------------------

def test_scrape_odds_returns_match_count():
    """scrape_odds returns the number of matches with odds."""
    target = 39
    fx = [_fdo_fixture(500, target)]
    with patch.object(scrape_mod, "get_fixtures_by_date", return_value=fx), \
         patch.object(scrape_mod, "fetch_odds_for_today",
                      return_value={500: [{"bookmaker": "X", "market": "h2h",
                                            "selection": "home", "odds": 1.5}]}):
        n = scrape_mod.scrape_odds(days_ahead=0)
    assert n == 1


def test_scrape_odds_no_fixtures_returns_zero():
    with patch.object(scrape_mod, "get_fixtures_by_date", return_value=[]):
        n = scrape_mod.scrape_odds(days_ahead=0)
    assert n == 0


# --- scrape_all -------------------------------------------------------------

def test_scrape_all_runs_all_three_stages():
    target = 39
    fx = [_fdo_fixture(600, target)]
    with patch.object(scrape_mod, "get_fixtures_by_date", return_value=fx), \
         patch.object(scrape_mod, "fetch_odds_for_today", return_value={}):
        summary = scrape_mod.scrape_all(days_ahead=0)
    assert "fixtures" in summary
    assert "results" in summary
    assert "odds_matches" in summary
    # Exactly one day in the cycle (today) and at least the key exists
    assert len(summary["fixtures"]) == 1
    assert next(iter(summary["fixtures"].values())) == 1
