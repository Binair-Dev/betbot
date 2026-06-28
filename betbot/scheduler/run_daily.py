"""Daily analysis pipeline — runs at 00:00 to analyse & place bets."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytz

from betbot.betting.decision import DecisionEngine
from betbot.betting.simulator import place_bet, record_prediction
from betbot.betting.value_calc import compute_value
from betbot.config import settings
from betbot.data.api_football import get_fixtures_by_date, get_fixture_by_id
from betbot.data.backfill import _upsert_fixture
from betbot.data.odds_fetcher import fetch_odds_for_today
from betbot.db.repository import execute, query
from betbot.features.orchestrator import FeatureOrchestrator
from betbot.logging_setup import get_logger
from betbot.models.confidence import ConfidenceAggregator
from betbot.models.markets import compute_all_markets
from betbot.models.ml_model import MLModel
from betbot.models.poisson import GoalExpectation, estimate_lambdas, team_ratings_from_xg

log = get_logger(__name__)


def run_daily_analysis() -> None:
    """Main daily pipeline. Called by scheduler at 00:00 Europe/Brussels."""
    tz = pytz.timezone(settings.TIMEZONE)
    now = datetime.now(tz)
    log.info("Starting daily analysis pipeline at %s", now.isoformat())

    today = now.date()
    tomorrow = today + timedelta(days=1)

    # Step 1: fetch fixtures for today and tomorrow
    fixtures = []
    for d in (today, tomorrow):
        try:
            day_fixtures = get_fixtures_by_date(datetime.combine(d, datetime.min.time()))
            fixtures.extend(day_fixtures)
        except Exception as exc:
            log.error("Fixture fetch failed for %s: %s", d, exc)

    fixtures = [
        fx for fx in fixtures
        if fx.get("league", {}).get("id") in settings.TARGET_LEAGUES
    ]
    log.info("Found %d fixtures in target leagues", len(fixtures))

    # Persist fixtures to DB
    for fx in fixtures:
        try:
            _upsert_fixture(fx)
        except Exception as exc:
            log.warning("Fixture persist failed: %s", exc)

    if not fixtures:
        log.info("No fixtures — nothing to do")
        return

    # Step 2: fetch odds
    odds_by_match = fetch_odds_for_today(fixtures)
    log.info("Got odds for %d matches", len(odds_by_match))

    # Step 3: load pre-match features per match and decide
    orchestrator = FeatureOrchestrator()
    decision_engine = DecisionEngine()
    confidence_agg = ConfidenceAggregator()
    ml_model = MLModel()

    matches_analyzed = 0
    matches_bet = 0
    for fx in fixtures:
        try:
            bet_id = _process_match(
                fx, orchestrator, decision_engine, confidence_agg, ml_model,
                odds_by_match,
            )
            matches_analyzed += 1
            if bet_id is not None:
                matches_bet += 1
        except Exception as exc:
            log.exception("Failed to process fixture %s: %s", fx.get("fixture", {}).get("id"), exc)

    log.info("Daily analysis complete: %d matches analyzed, %d bets placed",
             matches_analyzed, matches_bet)


def _process_match(fx: dict, orchestrator: FeatureOrchestrator,
                   decision_engine: DecisionEngine,
                   confidence_agg: ConfidenceAggregator,
                   ml_model: MLModel,
                   odds_by_match: dict[int, list[dict]]) -> int | None:
    """Process a single fixture. Returns bet_id if bet placed, else None."""
    fixture = fx.get("fixture", {})
    league = fx.get("league", {})
    teams = fx.get("teams", {})

    match_id = fixture.get("id")
    if not match_id:
        return None

    match = {
        "match_id": match_id,
        "league_id": league.get("id"),
        "season": league.get("season"),
        "match_date": fixture.get("date"),
        "home_team_id": teams.get("home", {}).get("id"),
        "away_team_id": teams.get("away", {}).get("id"),
        "home_team_name": teams.get("home", {}).get("name"),
        "away_team_name": teams.get("away", {}).get("name"),
        "venue": (fixture.get("venue") or {}).get("name"),
        "referee": fixture.get("referee"),
    }

    # Compute features
    feature_bundle = orchestrator.run(match)

    # Estimate Poisson lambdas (heuristic when xG data unavailable)
    home_xg = feature_bundle.breakdown.get("xg_form", {}).get("raw", {}).get("home_form", {}).get("xg_per_match", 1.3)
    away_xg = feature_bundle.breakdown.get("xg_form", {}).get("raw", {}).get("away_form", {}).get("xg_per_match", 1.1)
    home_xga = feature_bundle.breakdown.get("xg_form", {}).get("raw", {}).get("home_form", {}).get("xga_per_match", 1.1)
    away_xga = feature_bundle.breakdown.get("xg_form", {}).get("raw", {}).get("away_form", {}).get("xga_per_match", 1.3)
    home_att, home_def, away_att, away_def = team_ratings_from_xg(
        home_xg, home_xga
    )
    home_att2, home_def2, away_att2, away_def2 = team_ratings_from_xg(
        away_xg, away_xga
    )
    # Average attack/defense pairs
    avg_home_att = (home_att + away_def2) / 2
    avg_home_def = (home_def + away_att2) / 2
    avg_away_att = (away_att + home_def2) / 2
    avg_away_def = (away_def + home_att2) / 2
    exp = estimate_lambdas(avg_home_att, avg_home_def, avg_away_att, avg_away_def)

    # Compute all markets
    markets = compute_all_markets(match_id, exp)

    # Compute confidence per market
    feature_conf = feature_bundle.confidence
    poisson_max = max(markets.p_1, markets.p_x, markets.p_2)
    conf_map = {
        "1X2": max(feature_conf, poisson_max),
        "btts": max(markets.btts),
        "double_chance": max(markets.double_chance.values()),
        "correct_score": markets.exact_score[0][1] if markets.exact_score else 0.0,
        "draw_no_bet": max(markets.dnb),
    }
    for threshold, (po, pu) in markets.over_under.items():
        conf_map[f"over_under_{threshold}"] = max(po, pu)

    # Load odds from DB (just-fetched or cached)
    odds_history = _load_odds_for_match(match_id)
    if not odds_history:
        log.debug("No odds for match %s — skipping", match_id)
        return None

    # Decide
    decision = decision_engine.decide(match, markets, conf_map, odds_history)

    # Store ALL predictions for transparency
    for cand in decision.all_candidates:
        record_prediction(
            match_id=match_id,
            market=cand.market,
            selection=cand.selection,
            prob_model=cand.model_prob,
            confidence=cand.confidence,
            best_odds=cand.best_odds,
            best_bookmaker=cand.bookmaker,
            market_avg_odds=None,
            value=cand.value,
            weighted_score=feature_conf,
            ml_score=None,
            features_json=feature_bundle.to_dict(),
        )

    if not decision.should_bet() or not decision.selected:
        log.debug("No bet on match %s: %s", match_id, decision.reason)
        return None

    # Place bet
    sel = decision.selected
    bet_id = place_bet(
        match_id=match_id,
        market=sel.market,
        selection=sel.selection,
        odds=sel.best_odds,
        bookmaker=sel.bookmaker,
        confidence=sel.confidence,
        value=sel.value,
    )
    return bet_id


def _load_odds_for_match(match_id: int) -> list[dict]:
    rows = query(
        """SELECT bookmaker, market, selection, odds, fetched_at
           FROM odds_history WHERE match_id = ?
           AND fetched_at = (SELECT MAX(fetched_at) FROM odds_history WHERE match_id = ?)""",
        (match_id, match_id),
    )
    return [dict(r) for r in rows]
