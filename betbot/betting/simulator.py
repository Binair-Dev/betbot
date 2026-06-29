"""Bet simulator — place simulated bets, update bankroll."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from betbot.betting.value_calc import ValueBet
from betbot.config import settings
from betbot.db.repository import execute, query, query_one
from betbot.logging_setup import get_logger

log = get_logger(__name__)


def get_current_bankroll() -> float:
    row = query_one("SELECT value FROM settings WHERE key = 'bankroll_current'")
    if row:
        try:
            return float(row["value"])
        except (TypeError, ValueError):
            pass
    row = query_one("SELECT balance FROM bankroll_log ORDER BY at DESC LIMIT 1")
    return float(row["balance"]) if row else settings.BANKROLL_START


def update_bankroll(delta: float, event: str, bet_id: int | None = None,
                    notes: str = "") -> float:
    """Update bankroll and log the change. Returns new balance."""
    new_balance = get_current_bankroll() + delta
    execute(
        """UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP
           WHERE key = 'bankroll_current'""",
        (str(new_balance),),
    )
    execute(
        """INSERT INTO bankroll_log (balance, delta, event, bet_id, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (new_balance, delta, event, bet_id, notes),
    )
    log.info("Bankroll updated: %.2f€ (%+0.2f€) event=%s", new_balance, delta, event)
    return new_balance


def place_bet(match_id: int, market: str, selection: str, odds: float,
              bookmaker: str, confidence: float, value: float,
              prediction_id: int | None = None, stake: float | None = None) -> int | None:
    """Place a simulated bet. Returns bet ID or None if rejected.

    Refuses if bankroll < stake.
    """
    stake = stake if stake is not None else settings.BET_SIZE
    bankroll = get_current_bankroll()
    if bankroll < stake:
        log.warning("Insufficient bankroll (%.2f€) for bet of %.2f€", bankroll, stake)
        return None

    existing = query(
        "SELECT id FROM bets WHERE match_id=? AND market=? AND selection=? AND status='pending'",
        (match_id, market, selection),
    )
    if existing:
        log.info("Bet already placed on match=%s %s %s — skipping", match_id, market, selection)
        return None

    now = datetime.now(datetime.UTC).isoformat() if hasattr(datetime, "UTC") else datetime.utcnow().isoformat()
    bet_id = execute(
        """INSERT INTO bets (match_id, prediction_id, market, selection, odds,
                             bookmaker, stake, confidence, value, status, placed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (match_id, prediction_id, market, selection, odds, bookmaker,
         stake, confidence, value, now),
    )
    update_bankroll(-stake, "bet_placed", bet_id=bet_id,
                    notes=f"{market} {selection} @ {odds}")
    log.info("BET PLACED: match=%s %s %s @%.2f (conf=%.2f%% value=%.2f%%) — id=%s",
             match_id, market, selection, odds, confidence * 100, value * 100, bet_id)
    return bet_id


def void_bet(bet_id: int, stake: float) -> None:
    """Void a bet (push / draw-no-bet draw) — refund the stake."""
    execute(
        """UPDATE bets SET status='void', payout=?, profit=0, settled_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (stake, bet_id),
    )
    update_bankroll(stake, "bet_settled", bet_id=bet_id, notes="void")
    log.info("Bet %s voided — stake %.2f€ refunded", bet_id, stake)


def settle_bet(bet_id: int, won: bool, odds: float, stake: float) -> None:
    """Settle a bet: mark won/lost and update bankroll."""
    if won:
        payout = stake * odds
        profit = payout - stake
        execute(
            """UPDATE bets SET status='won', payout=?, profit=?, settled_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (payout, profit, bet_id),
        )
        update_bankroll(payout, "bet_settled", bet_id=bet_id, notes="won")
    else:
        execute(
            """UPDATE bets SET status='lost', payout=0, profit=?, settled_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (-stake, bet_id),
        )
        update_bankroll(0, "bet_settled", bet_id=bet_id, notes="lost")

    log.info("Bet %s settled: %s (profit=%+.2f€)", bet_id, "won" if won else "lost",
             (stake * odds - stake) if won else -stake)


def record_prediction(match_id: int, market: str, selection: str,
                      prob_model: float, confidence: float,
                      best_odds: float | None, best_bookmaker: str | None,
                      market_avg_odds: float | None, value: float,
                      weighted_score: float | None, ml_score: float | None,
                      features_json: dict | None = None) -> int:
    """Store a prediction in the database. Returns prediction_id."""
    return execute(
        """INSERT INTO predictions
           (match_id, market, selection, prob_model, confidence, best_odds,
            best_bookmaker, market_avg_odds, value, weighted_score, ml_score, features_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (match_id, market, selection, prob_model, confidence, best_odds,
         best_bookmaker, market_avg_odds, value, weighted_score, ml_score,
         json.dumps(features_json or {}, default=str)),
    )
