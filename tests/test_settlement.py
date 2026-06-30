"""Tests for bet settlement on matches with extra time / penalties.

Knockout matches (e.g. World Cup) are decided in 90+30+penalties, but
standard markets (1X2, O/U, BTTS, DC, DNB, correct score) settle on the
90-minute regulation score. This is the same convention as major
bookmakers (Bet365, Pinnacle, etc.).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from betbot.betting import results as res_mod
from betbot.betting import simulator as sim_mod
from betbot.betting.simulator import place_bet, settle_bet
from betbot.betting.results import settle_pending_bets
from betbot.db import repository as db_repository
from betbot.db.repository import execute, init_db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Use a temporary DB for each test."""
    db_path = str(tmp_path / "test.db")
    from pathlib import Path
    monkeypatch.setattr(db_repository, "get_db_path", lambda: Path(db_path))

    new_settings = replace(sim_mod.settings,
                           DB_PATH=db_path,
                           BANKROLL_START=100.0,
                           BET_SIZE=5.0)
    monkeypatch.setattr(sim_mod, "settings", new_settings)
    monkeypatch.setattr(db_repository, "settings", new_settings)
    monkeypatch.setattr(res_mod, "settings", new_settings)

    init_db()
    # Teams + a generic match
    execute("INSERT INTO teams (team_id, name) VALUES (1, 'Home')")
    execute("INSERT INTO teams (team_id, name) VALUES (2, 'Away')")
    yield


def _insert_match(match_id: int, status: str,
                  home_full: int, away_full: int,
                  home_reg: int | None = None, away_reg: int | None = None,
                  home_et: int | None = None, away_et: int | None = None,
                  home_pen: int | None = None, away_pen: int | None = None,
                  duration: str | None = None, winner: str | None = None):
    execute(
        """INSERT INTO matches (match_id, match_date, home_team_id, away_team_id,
                               status, home_score, away_score,
                               home_score_regular, away_score_regular,
                               home_score_et, away_score_et,
                               home_score_pen, away_score_pen,
                               match_duration, match_winner)
           VALUES (?, '2026-06-29 20:00:00', 1, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (match_id, status, home_full, away_full,
         home_reg, away_reg, home_et, away_et, home_pen, away_pen,
         duration, winner),
    )


def test_1x2_draw_after_extra_time_and_penalties_wins():
    """Germany vs Paraguay WC: regular 1-1, ET 0-0, pen 3-4.
    Bet '1X2 draw' @ 5.5 → must WIN (settled on 90-min score)."""
    _insert_match(537415, "FT",
                  home_full=1, away_full=1,
                  home_reg=1, away_reg=1,
                  home_et=0, away_et=0,
                  home_pen=3, away_pen=4,
                  duration="PENALTY_SHOOTOUT", winner="AWAY_TEAM")
    bet_id = place_bet(match_id=537415, market="1X2", selection="draw",
                       odds=5.5, bookmaker="test", confidence=0.7, value=0.05)
    n = settle_pending_bets()
    assert n == 1
    b = db_repository.query_one("SELECT status, payout, profit FROM bets WHERE id=?", (bet_id,))
    assert b["status"] == "won"
    assert b["payout"] == pytest.approx(27.5)
    assert b["profit"] == pytest.approx(22.5)


def test_1x2_home_lost_when_only_penalties_decided():
    """Same scenario, but bet on 'home'. Regulation 1-1 = draw → home bet LOST."""
    _insert_match(537416, "FT",
                  home_full=1, away_full=1,
                  home_reg=1, away_reg=1,
                  home_et=0, away_et=0,
                  home_pen=3, away_pen=4,
                  duration="PENALTY_SHOOTOUT", winner="AWAY_TEAM")
    bet_id = place_bet(match_id=537416, market="1X2", selection="home",
                       odds=2.0, bookmaker="test", confidence=0.7, value=0.05)
    settle_pending_bets()
    b = db_repository.query_one("SELECT status, profit FROM bets WHERE id=?", (bet_id,))
    assert b["status"] == "lost"
    assert b["profit"] == pytest.approx(-5.0)


def test_1x2_extra_time_no_penalties():
    """Match decided in ET (no penalties): 2-1 at 90 (home wins), ET 0-0.
    1X2 bet on 'home' must WIN regardless of ET being played."""
    _insert_match(537417, "FT",
                  home_full=2, away_full=1,
                  home_reg=2, away_reg=1,
                  home_et=0, away_et=0,
                  duration="EXTRA_TIME", winner="HOME_TEAM")
    bet_id = place_bet(match_id=537417, market="1X2", selection="home",
                       odds=2.5, bookmaker="test", confidence=0.7, value=0.05)
    settle_pending_bets()
    b = db_repository.query_one("SELECT status FROM bets WHERE id=?", (bet_id,))
    assert b["status"] == "won"


def test_over_under_uses_regular_time():
    """Bet over_2.5 — even if ET pushes total past 2.5, regulation total wins."""
    # 1-1 at 90 (total 2), 2-1 after ET (total 3). Regulation over_2.5 LOST.
    _insert_match(537418, "FT",
                  home_full=2, away_full=1,
                  home_reg=1, away_reg=1,
                  home_et=1, away_et=0,
                  duration="EXTRA_TIME", winner="HOME_TEAM")
    bet_id = place_bet(match_id=537418, market="over_under", selection="over_2.5",
                       odds=2.0, bookmaker="test", confidence=0.7, value=0.05)
    settle_pending_bets()
    b = db_repository.query_one("SELECT status FROM bets WHERE id=?", (bet_id,))
    assert b["status"] == "lost"


def test_draw_no_bet_push_on_regular_time_draw():
    """1-1 at 90 → DNB voided (push), stake refunded."""
    _insert_match(537419, "FT",
                  home_full=1, away_full=1,
                  home_reg=1, away_reg=1,
                  home_et=0, away_et=0,
                  home_pen=3, away_pen=4,
                  duration="PENALTY_SHOOTOUT", winner="AWAY_TEAM")
    bet_id = place_bet(match_id=537419, market="draw_no_bet", selection="dnb_home",
                       odds=2.0, bookmaker="test", confidence=0.7, value=0.05)
    settle_pending_bets()
    b = db_repository.query_one("SELECT status, payout, profit FROM bets WHERE id=?", (bet_id,))
    assert b["status"] == "void"
    assert b["payout"] == pytest.approx(5.0)
    assert b["profit"] == 0.0


def test_regular_league_match_unchanged():
    """Standard league match: regular = full. Old behaviour preserved."""
    _insert_match(537420, "FT",
                  home_full=2, away_full=0,
                  home_reg=2, away_reg=0,
                  duration="REGULAR", winner="HOME_TEAM")
    bet_id = place_bet(match_id=537420, market="1X2", selection="home",
                       odds=2.0, bookmaker="test", confidence=0.7, value=0.05)
    settle_pending_bets()
    b = db_repository.query_one("SELECT status FROM bets WHERE id=?", (bet_id,))
    assert b["status"] == "won"


def test_legacy_match_without_breakdown_still_works():
    """Matches where we never stored regular/et/pen (legacy data):
    settlement must fall back to fullTime and behave correctly."""
    _insert_match(537421, "FT", home_full=3, away_full=1)
    bet_id = place_bet(match_id=537421, market="1X2", selection="home",
                       odds=2.0, bookmaker="test", confidence=0.7, value=0.05)
    settle_pending_bets()
    b = db_repository.query_one("SELECT status FROM bets WHERE id=?", (bet_id,))
    assert b["status"] == "won"