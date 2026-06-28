"""Statistical backtest using football-data.co.uk cached CSVs.

This is a SIMPLIFIED backtest that doesn't require API quota. It validates the
value betting strategy on ~19k historical matches with closing Bet365 odds.

Approach:
- For each match, compute our probability estimate using a Poisson model with
  league-average attack/defense ratings (since we don't have team-specific xG
  from football-data.co.uk).
- Compare our probability vs the implied probability from closing odds.
- Bet when value > 3% (model_prob * odds > 1.03).
- Track P&L using actual outcomes.

This is NOT a full backtest of the production model (which has access to live
xG, Elo, injuries, etc.) — it's a sanity check that the value-betting strategy
has positive expected value on historical data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from betbot.betting.value_calc import compute_value
from betbot.features.odds_features import remove_vig
from betbot.data.football_data.loader import build_training_set
from betbot.logging_setup import get_logger
from betbot.models.poisson import (
    estimate_lambdas,
    prob_outcome_1x2,
    prob_over_under,
)

log = get_logger(__name__)


# League-specific scoring rates (goals scored at home / away) — empirically known
LEAGUE_RATES: dict[str, tuple[float, float]] = {
    "Premier League": (1.55, 1.20),
    "Championship": (1.45, 1.15),
    "Ligue 1": (1.45, 1.10),
    "Ligue 2": (1.35, 1.05),
    "Bundesliga": (1.60, 1.25),
    "Bundesliga 2": (1.45, 1.15),
    "Serie A": (1.50, 1.20),
    "Serie B": (1.40, 1.10),
    "La Liga": (1.45, 1.10),
    "La Liga 2": (1.35, 1.05),
    "Eredivisie": (1.65, 1.30),
    "Liga Portugal": (1.40, 1.10),
    "Jupiler Pro League": (1.50, 1.20),
}


@dataclass
class BacktestRow:
    match_date: datetime
    league: str
    home: str
    away: str
    market: str
    selection: str
    model_prob: float
    odds: float
    implied: float
    value: float
    outcome: int  # 0/1
    profit: float
    stake: float


def run_quick_backtest(
    df: pd.DataFrame | None = None,
    confidence_threshold: float = 0.60,
    value_threshold: float = 0.03,
    stake: float = 5.0,
) -> dict:
    """Run the simplified backtest.

    Returns dict with summary stats and per-row data.
    """
    if df is None:
        df = build_training_set()
    if df.empty:
        log.error("No data for backtest")
        return {}

    df = df.sort_values("match_date").reset_index(drop=True)
    log.info("Backtest: %d matches from %s to %s",
             len(df), df["match_date"].min(), df["match_date"].max())

    rows: list[BacktestRow] = []
    n = len(df)

    # Track running stats
    bankroll = 5000.0
    bankroll_curve: list[float] = [bankroll]
    daily_pnl: dict[str, float] = {}

    for idx, row in df.iterrows():
        league = row.get("__league_name", "Unknown")
        rates = LEAGUE_RATES.get(league, (1.45, 1.15))
        lambda_home, lambda_away = rates

        # Estimate Poisson lambdas using league averages
        # Adjust slightly by odds (lower odds = stronger team)
        odds_h, odds_d, odds_a = row.get("odds_home", 2.5), row.get("odds_draw", 3.3), row.get("odds_away", 3.0)
        # Use market odds to estimate team strength (inverse relationship)
        # Stronger team = lower odds = more goals expected
        # Average "strength" = (1/odds) normalized
        imp_h = 1.0 / odds_h if odds_h > 1 else 0.4
        imp_d = 1.0 / odds_d if odds_d > 1 else 0.3
        imp_a = 1.0 / odds_a if odds_a > 1 else 0.3
        fair_probs = remove_vig([imp_h, imp_d, imp_a])
        fair_h, fair_d, fair_a = fair_probs

        # Our estimate: blend Poisson prior with market (de-vigged) probs
        # Pure Poisson: 1/1 - 1/X2 - 1/X2 with league avg gives roughly home ~50%, draw ~25%, away ~25%
        # Blend: 50% Poisson, 50% market
        p_home_pois, p_draw_pois, p_away_pois = prob_outcome_1x2(
            type("E", (), {"lambda_home": lambda_home, "lambda_away": lambda_away, "rho": -0.1})()
        )
        p_home = 0.5 * p_home_pois + 0.5 * fair_h
        p_draw = 0.5 * p_draw_pois + 0.5 * fair_d
        p_away = 0.5 * p_away_pois + 0.5 * fair_a
        # Normalize
        total = p_home + p_draw + p_away
        if total > 0:
            p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

        # Check value bets on 1X2
        actual_home, actual_away = int(row["home_score"]), int(row["away_score"])
        outcome_h = 1 if actual_home > actual_away else 0
        outcome_d = 1 if actual_home == actual_away else 0
        outcome_a = 1 if actual_home < actual_away else 0

        for sel_name, model_p, odds_val, actual_outcome in [
            ("home", p_home, odds_h, outcome_h),
            ("draw", p_draw, odds_d, outcome_d),
            ("away", p_away, odds_a, outcome_a),
        ]:
            if odds_val <= 1.0 or model_p <= 0:
                continue
            value = compute_value(model_p, odds_val)
            confidence = max(model_p, 1 - model_p) - sorted([p_home, p_draw, p_away])[1]

            if value >= value_threshold and confidence >= confidence_threshold - 0.05:
                # Place bet
                won = actual_outcome == 1
                profit = (stake * odds_val - stake) if won else -stake
                rows.append(BacktestRow(
                    match_date=row["match_date"],
                    league=league,
                    home=row.get("home_team", ""),
                    away=row.get("away_team", ""),
                    market="1X2",
                    selection=sel_name,
                    model_prob=float(model_p),
                    odds=float(odds_val),
                    implied=float(1.0 / odds_val),
                    value=float(value),
                    outcome=int(won),
                    profit=float(profit),
                    stake=float(stake),
                ))
                bankroll += profit
                day = pd.Timestamp(row["match_date"]).date().isoformat()
                daily_pnl[day] = daily_pnl.get(day, 0) + profit

        if idx % 2000 == 0:
            log.info("  %d/%d matches processed | bankroll=%.2f€ | bets=%d",
                     idx, n, bankroll, len(rows))

        bankroll_curve.append(bankroll)

    # Compute summary stats
    df_rows = pd.DataFrame([r.__dict__ for r in rows])
    summary = compute_summary(df_rows, bankroll_curve, daily_pnl, bankroll, n)
    summary["rows"] = df_rows  # include for inspection
    return summary


def compute_summary(df_rows: pd.DataFrame, bankroll_curve: list[float],
                    daily_pnl: dict[str, float], final_bankroll: float,
                    n_matches: int) -> dict:
    if df_rows.empty:
        return {
            "n_matches": n_matches, "n_bets": 0,
            "bankroll_start": 5000.0, "bankroll_end": 5000.0,
            "profit": 0.0, "roi": 0.0, "hit_rate": 0.0,
            "max_drawdown": 0.0, "sharpe": 0.0,
            "by_market": {}, "by_league": {},
        }

    total_bets = len(df_rows)
    won = int(df_rows["outcome"].sum())
    lost = total_bets - won
    total_stake = float(df_rows["stake"].sum())
    total_payout = float((df_rows["stake"] * df_rows["odds"] * df_rows["outcome"]).sum())
    profit = float(df_rows["profit"].sum())
    roi = profit / total_stake if total_stake else 0.0
    hit_rate = won / total_bets if total_bets else 0.0

    # Max drawdown
    peak = bankroll_curve[0]
    max_dd = 0.0
    for b in bankroll_curve:
        if b > peak:
            peak = b
        dd = (peak - b) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Sharpe (daily)
    pnl_list = list(daily_pnl.values())
    if pnl_list and np.std(pnl_list) > 0:
        sharpe = float(np.mean(pnl_list) / np.std(pnl_list) * np.sqrt(252))
    else:
        sharpe = 0.0

    # By market
    by_market = {}
    for m, sub in df_rows.groupby("market"):
        by_market[m] = {
            "n_bets": len(sub),
            "won": int(sub["outcome"].sum()),
            "stake": float(sub["stake"].sum()),
            "profit": float(sub["profit"].sum()),
            "roi": float(sub["profit"].sum() / sub["stake"].sum()) if sub["stake"].sum() else 0,
        }

    # By league
    by_league = {}
    for lg, sub in df_rows.groupby("league"):
        by_league[lg] = {
            "n_bets": len(sub),
            "won": int(sub["outcome"].sum()),
            "stake": float(sub["stake"].sum()),
            "profit": float(sub["profit"].sum()),
            "roi": float(sub["profit"].sum() / sub["stake"].sum()) if sub["stake"].sum() else 0,
        }

    return {
        "n_matches": n_matches,
        "n_bets": total_bets,
        "won": won,
        "lost": lost,
        "bankroll_start": 5000.0,
        "bankroll_end": round(final_bankroll, 2),
        "profit": round(profit, 2),
        "total_stake": round(total_stake, 2),
        "total_payout": round(total_payout, 2),
        "roi": round(roi, 4),
        "hit_rate": round(hit_rate, 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe": round(sharpe, 4),
        "by_market": by_market,
        "by_league": by_league,
    }
