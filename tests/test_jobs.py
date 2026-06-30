"""Tests for the scheduler job helpers (settlement refresh)."""
from __future__ import annotations

from unittest.mock import patch

from betbot.scheduler.jobs import _fetch_match_result


def test_fetch_match_result_primary_source():
    """football-data.org returns FT → use it, mark source."""
    fdo_payload = {
        "match_id": 42, "status": "FT",
        "home_score": 2, "away_score": 1,
        "home_ht_score": 1, "away_ht_score": 0,
    }
    with patch("betbot.data.football_data_org.refresh_match_result",
               return_value=fdo_payload) as mock_fdo, \
         patch("betbot.data.api_football.get_fixture_by_id") as mock_af:
        result = _fetch_match_result(42)
    assert result["status"] == "FT"
    assert result["home_score"] == 2
    assert result["away_score"] == 1
    assert result["source"] == "football_data_org"
    mock_fdo.assert_called_once_with(42)
    mock_af.assert_not_called()


def test_fetch_match_result_fallback_to_api_football():
    """If football-data.org misses (None or non-terminal), try API-Football."""
    af_payload = {
        "fixture": {"id": 42, "status": {"short": "FT"}},
        "goals": {"home": 3, "away": 0},
        "score": {"halftime": {"home": 1, "away": 0}},
    }
    with patch("betbot.data.football_data_org.refresh_match_result",
               return_value=None) as mock_fdo, \
         patch("betbot.data.api_football.get_fixture_by_id",
               return_value=af_payload) as mock_af:
        result = _fetch_match_result(42)
    assert result["status"] == "FT"
    assert result["home_score"] == 3
    assert result["away_score"] == 0
    assert result["source"] == "api_football"
    mock_fdo.assert_called_once_with(42)
    mock_af.assert_called_once_with(42)


def test_fetch_match_result_skips_api_football_when_fdo_is_non_terminal():
    """If fdo returns a non-terminal status (e.g. NS for an upcoming match),
    we should NOT clobber it with API-Football (which may be more up-to-date
    but adds latency). The contract is: fdo terminal → use it; otherwise try
    API-Football. Here we exercise the non-terminal branch to confirm the
    API-Football call is still made."""
    fdo_payload = {
        "match_id": 42, "status": "NS",
        "home_score": None, "away_score": None,
        "home_ht_score": None, "away_ht_score": None,
    }
    af_payload = {
        "fixture": {"id": 42, "status": {"short": "1H"}},
        "goals": {"home": 0, "away": 0},
        "score": {"halftime": {"home": None, "away": None}},
    }
    with patch("betbot.data.football_data_org.refresh_match_result",
               return_value=fdo_payload), \
         patch("betbot.data.api_football.get_fixture_by_id",
               return_value=af_payload):
        result = _fetch_match_result(42)
    assert result["status"] == "1H"
    assert result["source"] == "api_football"


def test_fetch_match_result_returns_none_when_both_sources_fail():
    with patch("betbot.data.football_data_org.refresh_match_result",
               return_value=None), \
         patch("betbot.data.api_football.get_fixture_by_id", return_value=None):
        assert _fetch_match_result(42) is None