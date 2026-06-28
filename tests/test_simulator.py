"""Tests for the simulator.

These tests use a temporary SQLite database to avoid polluting the real one.
We bypass the global settings DB_PATH by monkeypatching the get_db_path function.
"""
from __future__ import annotations

import pytest

from betbot.betting import simulator as sim_mod
from betbot.betting.simulator import (
    get_current_bankroll,
    place_bet,
    record_prediction,
    settle_bet,
    update_bankroll,
)
from betbot.db import repository as db_repository
from betbot.db.repository import execute, init_db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Use a temporary DB for each test."""
    db_path = str(tmp_path / "test.db")

    # Patch the get_db_path function in repository module
    from pathlib import Path
    monkeypatch.setattr(db_repository, "get_db_path", lambda: Path(db_path))
    # Patch settings globally — apply to all modules that imported it
    from dataclasses import replace
    new_settings = replace(sim_mod.settings,
                           DB_PATH=db_path,
                           BANKROLL_START=100.0,
                           BET_SIZE=5.0)
    monkeypatch.setattr(sim_mod, "settings", new_settings)
    monkeypatch.setattr(db_repository, "settings", new_settings)

    init_db()
    # Insert dummy teams + match for FK constraints
    execute("INSERT INTO teams (team_id, name) VALUES (1, 'Home')")
    execute("INSERT INTO teams (team_id, name) VALUES (2, 'Away')")
    execute(
        """INSERT INTO matches (match_id, match_date, home_team_id, away_team_id, status)
           VALUES (?, ?, ?, ?, ?)""",
        (999, "2099-01-01 20:00:00", 1, 2, "FT"),
    )
    yield


def test_bankroll_initial_value():
    assert get_current_bankroll() == 100.0


def test_update_bankroll():
    new_balance = update_bankroll(-5.0, "test_event", notes="test")
    assert new_balance == 95.0
    assert get_current_bankroll() == 95.0


def test_place_bet_decreases_bankroll():
    bet_id = place_bet(
        match_id=999, market="1X2", selection="home",
        odds=2.0, bookmaker="test", confidence=0.7, value=0.05,
    )
    assert bet_id is not None
    assert get_current_bankroll() == 95.0


def test_place_bet_insufficient_funds():
    update_bankroll(-99.0, "test")
    bet_id = place_bet(
        match_id=999, market="1X2", selection="home",
        odds=2.0, bookmaker="test", confidence=0.7, value=0.05,
    )
    assert bet_id is None


def test_settle_bet_won():
    bet_id = place_bet(
        match_id=999, market="1X2", selection="home",
        odds=2.5, bookmaker="test", confidence=0.7, value=0.05,
    )
    assert get_current_bankroll() == 95.0
    settle_bet(bet_id, won=True, odds=2.5, stake=5.0)
    assert get_current_bankroll() == pytest.approx(107.5)


def test_settle_bet_lost():
    bet_id = place_bet(
        match_id=999, market="1X2", selection="home",
        odds=2.5, bookmaker="test", confidence=0.7, value=0.05,
    )
    settle_bet(bet_id, won=False, odds=2.5, stake=5.0)
    assert get_current_bankroll() == pytest.approx(95.0)


def test_record_prediction():
    pid = record_prediction(
        match_id=999, market="1X2", selection="home",
        prob_model=0.6, confidence=0.7,
        best_odds=1.95, best_bookmaker="test",
        market_avg_odds=1.90, value=0.17,
        weighted_score=0.65, ml_score=None,
    )
    assert pid > 0
