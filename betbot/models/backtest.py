"""Backtest the betting strategy on historical data.

Iterates over a historical period day-by-day:
1. For each day, fetch fixtures and odds
2. Compute features and predictions
3. Decide whether to bet
4. Track PnL using actual results
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from betbot.betting.decision import DecisionEngine
from betbot.betting.simulator import (
    get_current_bankroll,
    record_prediction,
    update_bankroll,
)
from betbot.config import settings
from betbot.data.api_football import get_fixtures_by_date
from betbot.db.repository import execute, query
from betbot.logging_setup import get_logger
from betbot.models.confidence import ConfidenceAggregator
from betbot.models.markets import compute_all_markets
from betbot.models.ml_model import MLModel, build_training_dataframe
from betbot.models.poisson import estimate_lambdas, team_ratings_from_xg

log = get_logger(__name__)


@dataclass
class BacktestReport:
    period_start: datetime
    period_end: datetime
    total_bets: int = 0
    won: int = 0
    lost: int = 0
    void: int = 0
    total_stake: float = 0.0
    total_payout: float = 0.0
    profit: float = 0.0
    roi: float = 0.0
    hit_rate: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    by_market: dict[str, dict[str, float]] = field(default_factory=dict)
    by_league: dict[str, dict[str, float]] = field(default_factory=dict)
    bankroll_curve: list[tuple[datetime, float]] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_bets": self.total_bets,
            "won": self.won, "lost": self.lost, "void": self.void,
            "total_stake": round(self.total_stake, 2),
            "total_payout": round(self.total_payout, 2),
            "profit": round(self.profit, 2),
            "roi": round(self.roi, 4),
            "hit_rate": round(self.hit_rate, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe": round(self.sharpe, 4),
            "by_market": self.by_market,
            "by_league": self.by_league,
            "notes": self.notes,
        }


def run_backtest(start_date: datetime, end_date: datetime,
                 train_first: bool = True) -> BacktestReport:
    """Run a backtest from start_date to end_date (inclusive)."""
    log.info("Starting backtest from %s to %s", start_date.date(), end_date.date())

    report = BacktestReport(period_start=start_date, period_end=end_date)
    bankroll = settings.BANKROLL_START

    if train_first:
        # Train ML model on data BEFORE the backtest period (avoid lookahead bias)
        log.info("Training ML model on pre-backtest data...")
        try:
            df_train = build_training_dataframe()
            if len(df_train) > 100:
                train_end = start_date - timedelta(days=1)
                df_pre = df_train[df_train["match_date"] < pd.Timestamp(train_end)]
                if len(df_pre) > 50:
                    ml = MLModel()
                    ml.train(df_pre)
        except Exception as exc:
            log.warning("ML training skipped: %s", exc)

    decision_engine = DecisionEngine()
    confidence_agg = ConfidenceAggregator()
    orchestrator = __import__("betbot.features.orchestrator", fromlist=["FeatureOrchestrator"]).FeatureOrchestrator()

    cur_date = start_date
    daily_pnl: list[float] = []
    daily_dates: list[datetime] = []

    while cur_date <= end_date:
        try:
            fixtures = get_fixtures_by_date(cur_date)
        except Exception as exc:
            log.warning("Failed to fetch fixtures for %s: %s", cur_date.date(), exc)
            cur_date += timedelta(days=1)
            continue

        fixtures = [fx for fx in fixtures
                    if fx.get("league", {}).get("id") in settings.TARGET_LEAGUES]

        day_bets = 0
        day_pnl = 0.0

        for fx in fixtures:
            fixture = fx.get("fixture", {})
            league = fx.get("league", {})
            teams = fx.get("teams", {})
            goals = fx.get("goals", {}) or {}
            if fixture.get("status", {}).get("short") != "FT":
                continue

            home_score = goals.get("home")
            away_score = goals.get("away")
            if home_score is None or away_score is None:
                continue

            # Build match dict for features
            match = {
                "match_id": fixture.get("id"),
                "league_id": league.get("id"),
                "season": league.get("season"),
                "match_date": fixture.get("date"),
                "home_team_id": teams.get("home", {}).get("id"),
                "away_team_id": teams.get("away", {}).get("id"),
                "home_team_name": teams.get("home", {}).get("name"),
                "away_team_name": teams.get("away", {}).get("name"),
                "venue": (fixture.get("venue") or {}).get("name"),
                "referee": fixture.get("referee"),
                "home_score": home_score,
                "away_score": away_score,
            }

            # Compute features (may have errors on historical; tolerate)
            try:
                feature_bundle = orchestrator.run(match)
            except Exception:
                feature_bundle = None

            # Estimate Poisson lambdas from simple proxies
            lambda_home, lambda_away = _estimate_lambdas_for_match(match)
            from betbot.models.poisson import GoalExpectation
            exp = GoalExpectation(lambda_home=lambda_home, lambda_away=lambda_away)
            markets = compute_all_markets(match["match_id"], exp)

            # Use the feature bundle's max delta as confidence proxy
            conf_map = {
                "1X2": max(feature_bundle.confidence, markets.p_1, markets.p_x, markets.p_2) if feature_bundle else 0.5,
                "btts": max(markets.btts),
                "double_chance": max(markets.double_chance.values()),
                "correct_score": markets.exact_score[0][1] if markets.exact_score else 0.0,
                "draw_no_bet": max(markets.dnb),
            }
            for threshold in markets.over_under:
                conf_map[f"over_under_{threshold}"] = max(markets.over_under[threshold])

            # Use closing odds from API-Football (already in odds_history table)
            odds_history = _load_odds_for_match(match["match_id"])
            if not odds_history:
                continue

            decision = decision_engine.decide(match, markets, conf_map, odds_history)
            if not decision.should_bet() or not decision.selected:
                continue

            # Evaluate the bet outcome
            won = _evaluate_outcome(decision.selected.market, decision.selected.selection,
                                    home_score, away_score)
            stake = settings.BET_SIZE
            payout = stake * decision.selected.best_odds if won else 0
            profit = payout - stake
            bankroll += profit

            report.total_bets += 1
            report.total_stake += stake
            report.total_payout += payout
            report.profit += profit
            if won:
                report.won += 1
            else:
                report.lost += 1
            day_bets += 1
            day_pnl += profit

            # Track by market
            m = decision.selected.market
            if m not in report.by_market:
                report.by_market[m] = {"bets": 0, "won": 0, "profit": 0.0, "stake": 0.0}
            report.by_market[m]["bets"] += 1
            report.by_market[m]["stake"] += stake
            report.by_market[m]["profit"] += profit
            if won:
                report.by_market[m]["won"] += 1

            # Track by league
            lg = league.get("name", "unknown")
            if lg not in report.by_league:
                report.by_league[lg] = {"bets": 0, "won": 0, "profit": 0.0, "stake": 0.0}
            report.by_league[lg]["bets"] += 1
            report.by_league[lg]["stake"] += stake
            report.by_league[lg]["profit"] += profit
            if won:
                report.by_league[lg]["won"] += 1

        if day_bets > 0:
            daily_pnl.append(day_pnl)
            daily_dates.append(cur_date)
            report.bankroll_curve.append((cur_date, bankroll))
        cur_date += timedelta(days=1)

    # Final metrics
    if report.total_bets:
        report.hit_rate = report.won / report.total_bets
        report.roi = report.profit / report.total_stake if report.total_stake else 0.0

    # Max drawdown
    if report.bankroll_curve:
        peak = report.bankroll_curve[0][1]
        max_dd = 0.0
        for _, bal in report.bankroll_curve:
            if bal > peak:
                peak = bal
            dd = (peak - bal) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        report.max_drawdown = max_dd

    # Sharpe ratio (daily)
    if daily_pnl:
        import numpy as np
        daily_pnl_arr = np.array(daily_pnl)
        if daily_pnl_arr.std() > 0:
            report.sharpe = float(daily_pnl_arr.mean() / daily_pnl_arr.std() * (365 ** 0.5))

    report.notes = (f"Backtest over {(end_date - start_date).days} days. "
                    f"Bankroll: {settings.BANKROLL_START:.0f}€ → {bankroll:.2f}€ "
                    f"(profit {report.profit:+.2f}€, ROI {report.roi:+.2%}).")
    log.info("Backtest complete: %s", report.notes)

    # Persist
    _save_backtest_report(report)
    return report


def _estimate_lambdas_for_match(match: dict[str, Any]) -> tuple[float, float]:
    """Crude fallback for backtest when full features aren't available.

    Uses league average + simple ELO-based adjustment.
    """
    # Default league averages
    league_avg = {
        39: (1.50, 1.20), 40: (1.45, 1.15),  # England
        61: (1.45, 1.10), 62: (1.40, 1.05),  # France
        78: (1.55, 1.20), 79: (1.45, 1.15),  # Germany
        135: (1.50, 1.15), 136: (1.40, 1.10),  # Italy
        140: (1.45, 1.10), 141: (1.40, 1.05),  # Spain
    }
    lg_id = match.get("league_id")
    base_home, base_away = league_avg.get(lg_id, (1.45, 1.15))

    # Apply ELO-based adjustment if available
    home_id = match.get("home_team_id")
    away_id = match.get("away_team_id")
    if home_id and away_id:
        rows = query("SELECT elo FROM teams WHERE team_id IN (?, ?)", (home_id, away_id))
        elos = {r["team_id"] if "team_id" in r.keys() else None: r["elo"] for r in rows}
        # Re-fetch with team_id
        rows = query("SELECT team_id, elo FROM teams WHERE team_id IN (?, ?)", (home_id, away_id))
        elo_map = {r["team_id"]: r["elo"] for r in rows}
        if elo_map:
            home_elo = elo_map.get(home_id, 1500)
            away_elo = elo_map.get(away_id, 1500)
            # Adjust based on ELO diff: each 100 ELO points = ~10% more goals
            diff = (home_elo - away_elo) / 1000.0
            base_home = base_home * (1 + diff)
            base_away = base_away * (1 - diff)

    return max(0.3, min(4.5, base_home)), max(0.3, min(4.5, base_away))


def _load_odds_for_match(match_id: int) -> list[dict]:
    rows = query(
        """SELECT bookmaker, market, selection, odds, fetched_at
           FROM odds_history WHERE match_id = ?""",
        (match_id,),
    )
    return [dict(r) for r in rows]


def _evaluate_outcome(market: str, selection: str, home: int, away: int) -> bool:
    if market == "1X2":
        if selection == "home":
            return home > away
        if selection == "draw":
            return home == away
        if selection == "away":
            return home < away
    elif market == "over_under":
        try:
            _, t = selection.split("_")
            th = float(t)
        except (ValueError, AttributeError):
            return False
        total = home + away
        return (total > th) if selection.startswith("over") else (total < th)
    elif market == "btts":
        both = home >= 1 and away >= 1
        return (selection == "btts_yes" and both) or (selection == "btts_no" and not both)
    elif market == "double_chance":
        if selection == "1X":
            return home > away or home == away
        if selection == "X2":
            return home == away or home < away
        if selection == "12":
            return home != away
    elif market == "correct_score":
        return selection == f"{home}-{away}"
    return False


def _save_backtest_report(report: BacktestReport) -> None:
    execute(
        """INSERT INTO backtest_results
           (period_start, period_end, total_bets, won_bets, lost_bets,
            total_stake, total_payout, profit, roi, hit_rate, max_drawdown, config_json, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report.period_start.date().isoformat(),
            report.period_end.date().isoformat(),
            report.total_bets, report.won, report.lost,
            report.total_stake, report.total_payout, report.profit,
            report.roi, report.hit_rate, report.max_drawdown,
            json.dumps(report.to_dict(), default=str),
            report.notes,
        ),
    )
