"""CLI for the scraper: manual scrape, backfill."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from betbot.config import settings
from betbot.data.backfill import backfill_fixtures, backfill_understat_for_season
from betbot.db.repository import init_db
from betbot.logging_setup import setup_logging, get_logger
from betbot.scheduler.scrape import (
    refresh_results,
    scrape_all,
    scrape_fixtures,
    scrape_odds,
)


def cmd_scrape(args) -> int:
    """Run a full scrape cycle (or just one piece via flags)."""
    setup_logging()
    log = get_logger("cli.scrape")
    init_db()
    if args.fixtures_only:
        log.info("CLI: scrape_fixtures only (days_ahead=%d)", args.days)
        print(scrape_fixtures(days_ahead=args.days))
    elif args.results_only:
        log.info("CLI: refresh_results only")
        print(refresh_results())
    elif args.odds_only:
        log.info("CLI: scrape_odds only (days_ahead=%d)", args.days)
        print(scrape_odds(days_ahead=args.days))
    else:
        log.info("CLI: full scrape cycle (days_ahead=%d)", args.days)
        print(scrape_all(days_ahead=args.days))
    return 0


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
    season = args.season or end_date.year - 1
    n_xg = backfill_understat_for_season(season)
    log.info("Backfill complete: %d fixtures, %d xG records", n_fixtures, n_xg)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="betbot", description="Betbot scraper CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scrape", help="Run a scrape cycle (fixtures + odds + results)")
    p.add_argument("--days", type=int, default=2, help="Days ahead to fetch fixtures/odds for")
    p.add_argument("--fixtures-only", action="store_true",
                   help="Only pull fixtures, skip results and odds")
    p.add_argument("--results-only", action="store_true",
                   help="Only refresh results for finished matches")
    p.add_argument("--odds-only", action="store_true",
                   help="Only pull odds for upcoming matches")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("backfill", help="Backfill historical data via API (uses API quota)")
    p.add_argument("--days", type=int, default=180, help="Number of days to backfill")
    p.add_argument("--season", type=int, default=None, help="Season year for Understat")
    p.set_defaults(func=cmd_backfill)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
