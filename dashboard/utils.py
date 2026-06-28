"""Shared utilities for the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

from betbot.db.repository import query


def get_bets_dataframe(status: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM bets"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY placed_at DESC"
    rows = query(sql, params)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    return df


def get_predictions_dataframe(match_date: datetime | None = None) -> pd.DataFrame:
    sql = """
        SELECT p.*, m.match_date, m.home_team_id, m.away_team_id, m.status AS match_status
        FROM predictions p
        JOIN matches m ON m.match_id = p.match_id
    """
    params: tuple = ()
    if match_date:
        sql += " WHERE date(m.match_date) = date(?)"
        params = (match_date.date().isoformat(),)
    sql += " ORDER BY p.confidence DESC"
    rows = query(sql, params)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_kpi_metrics() -> dict[str, float]:
    bankroll_row = query("SELECT balance FROM bankroll_log ORDER BY at DESC LIMIT 1")
    current_bankroll = bankroll_row[0]["balance"] if bankroll_row else 0.0

    totals = query("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) AS won,
            SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) AS lost,
            COALESCE(SUM(stake), 0) AS total_stake,
            COALESCE(SUM(profit), 0) AS total_profit
        FROM bets
    """)
    row = totals[0] if totals else None
    if not row:
        return {"bankroll": 0.0, "total": 0, "won": 0, "lost": 0,
                "hit_rate": 0.0, "roi": 0.0, "profit": 0.0, "total_stake": 0.0}

    total = row["total"] or 0
    won = row["won"] or 0
    lost = row["lost"] or 0
    profit = row["total_profit"] or 0.0
    stake = row["total_stake"] or 0.0
    roi = (profit / stake) if stake else 0.0
    hit_rate = (won / total) if total else 0.0

    return {
        "bankroll": current_bankroll,
        "total": total,
        "won": won,
        "lost": lost,
        "hit_rate": hit_rate,
        "roi": roi,
        "profit": profit,
        "total_stake": stake,
    }


def get_date_range(days: int = 7) -> Iterable[datetime]:
    today = datetime.utcnow().date()
    for i in range(days):
        yield datetime.combine(today - timedelta(days=i), datetime.min.time())
