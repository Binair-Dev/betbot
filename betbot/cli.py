"""CLI scripts for manual operations: backfill, backtest, train, run-once."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from betbot.config import settings
from betbot.data.backfill import backfill_fixtures, backfill_understat_for_season
from betbot.db.repository import init_db
from betbot.logging_setup import setup_logging, get_logger


def cmd_backfill(args) -> int:
    setup_logging()
    log = get_logger("cli.backfill")
    init_db()

    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=args.days)
    log.info("Backfilling from %s to %s (%d days)", start_date, end_date, args.days)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.min.time())
    n_fixtures = backfill_fixtures(start_dt, end_dt)

    season = args.season or end_date.year - 1  # default: last season
    n_xg = backfill_understat_for_season(season)

    log.info("Backfill complete: %d fixtures, %d xG records", n_fixtures, n_xg)
    return 0


def cmd_backtest(args) -> int:
    """Backtest (kept for future use with paid APIs).

    Note: with free APIs, backtest gives misleading results because we can't
    reconstruct team-specific features (xG, Elo, injuries) for historical matches.
    The quick CSV version gave ROI -19.70% on 18,925 matches — it proved the
    market is efficient when we have no informational edge, which is what happens
    when we don't have team-specific features.

    Use this only if you upgrade to a paid plan and backfill historical data.
    """
    setup_logging()
    log = get_logger("cli.backtest")
    init_db()
    log.warning("Backtest results on free APIs are not representative of the strategy.")
    log.warning("See README — backtest needs team-specific features unavailable in free tier.")

    from betbot.models.backtest import run_backtest
    end_date = datetime.utcnow().date() - timedelta(days=args.skip_recent)
    start_date = end_date - timedelta(days=args.days)
    log.info("Running API-based backtest from %s to %s (%d days)", start_date, end_date, args.days)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.min.time())
    report = run_backtest(start_dt, end_dt, train_first=not args.no_train)
    log.info("Backtest result: %s", report.notes)
    return 0


def cmd_train(args) -> int:
    setup_logging()
    log = get_logger("cli.train")
    init_db()

    from betbot.models.ml_model import MLModel, build_training_dataframe

    log.info("Building training dataset (using football-data.co.uk, free, no API quota)...")
    df = build_training_dataframe(use_football_data=not getattr(args, "use_sqlite", False))
    if df.empty or len(df) < 50:
        log.error("Not enough training data (%d rows)", len(df))
        return 1

    log.info("Training ML model on %d matches...", len(df))
    ml = MLModel()
    metrics = ml.train(df)
    log.info("Training complete: accuracy=%.3f log_loss=%.3f n=%d",
             metrics["accuracy"], metrics["log_loss"], metrics["n_train"])
    return 0


def cmd_setup(args) -> int:
    """One-shot setup: pull football-data.co.uk data and train ML. No API quotas used."""
    setup_logging()
    log = get_logger("cli.setup")
    init_db()

    log.info("=" * 60)
    log.info("Betbot SETUP — no API quotas consumed")
    log.info("=" * 60)

    from betbot.models.ml_model import MLModel, build_training_dataframe

    log.info("Step 1/2: Pulling 4 seasons from football-data.co.uk (free CSVs)...")
    df = build_training_dataframe()
    if df.empty:
        log.error("Could not fetch training data")
        return 1
    log.info("  → %d matches across %d leagues", len(df),
             df["__league_name"].nunique() if "__league_name" in df.columns else 0)

    log.info("Step 2/2: Training ML model...")
    ml = MLModel()
    metrics = ml.train(df)
    log.info("  → accuracy=%.3f, log_loss=%.3f", metrics["accuracy"], metrics["log_loss"])

    log.info("=" * 60)
    log.info("Setup complete! Le bot peut maintenant tourner.")
    log.info("Dashboard: http://localhost:8501")
    log.info("=" * 60)
    return 0


def cmd_run_once(args) -> int:
    setup_logging()
    log = get_logger("cli.run_once")
    init_db()

    from betbot.scheduler.run_daily import run_daily_analysis
    run_daily_analysis()
    return 0


def cmd_settle(args) -> int:
    setup_logging()
    init_db()
    from betbot.betting.results import settle_pending_bets
    n = settle_pending_bets()
    print(f"Settled {n} bets")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="betbot", description="Betbot CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backfill", help="Backfill historical data via API (uses API quota)")
    p.add_argument("--days", type=int, default=180, help="Number of days to backfill")
    p.add_argument("--season", type=int, default=None, help="Season year for Understat")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("backtest", help="Run backtest (paid APIs only — see warning)")
    p.add_argument("--days", type=int, default=180, help="Backtest period in days")
    p.add_argument("--skip-recent", type=int, default=2, help="Skip last N days")
    p.add_argument("--no-train", action="store_true", help="Skip ML training")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("train", help="Train ML model on historical data (football-data.co.uk)")
    p.add_argument("--use-sqlite", action="store_true",
                   help="Use SQLite data instead of football-data.co.uk (requires API backfill)")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("setup", help="One-shot setup: pull CSVs + train ML (no API quotas)")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("run-once", help="Run the daily pipeline once (debug)")
    p.set_defaults(func=cmd_run_once)

    p = sub.add_parser("settle", help="Settle pending bets")
    p.set_defaults(func=cmd_settle)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
