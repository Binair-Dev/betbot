"""Shared utilities for the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

from betbot.db.repository import query


def _team_name_map() -> dict[int, str]:
    """team_id → display name."""
    return {r["team_id"]: r["name"] for r in query("SELECT team_id, name FROM teams")}


def _league_name_map() -> dict[int, str]:
    return {r["league_id"]: r["name"] for r in query("SELECT league_id, name FROM leagues")}


def _format_score(row) -> str:
    """Render the score with ET / penalty breakdown if the match had them."""
    h = row.get("home_score")
    a = row.get("away_score")
    if h is None or a is None:
        return "—"
    reg_h = row.get("home_score_regular")
    reg_a = row.get("away_score_regular")
    et_h = row.get("home_score_et") or 0
    et_a = row.get("away_score_et") or 0
    pen_h = row.get("home_score_pen") or 0
    pen_a = row.get("home_score_pen") or 0
    duration = row.get("match_duration")
    if duration == "PENALTY_SHOOTOUT" and reg_h is not None:
        return f"{reg_h}-{reg_a} (a.p.) {h}-{a} tab {pen_h}-{pen_a}"
    if duration == "EXTRA_TIME" and reg_h is not None and (reg_h, reg_a) != (h, a):
        return f"{reg_h}-{reg_a} (a.p.) {h}-{a}"
    return f"{h}-{a}"


def get_bets_dataframe(status: str | None = None) -> pd.DataFrame:
    """Bets joined with matches + teams + leagues for clear display."""
    sql = """
        SELECT b.id, b.placed_at, b.market, b.selection, b.odds, b.bookmaker,
               b.stake, b.confidence, b.value, b.status, b.payout, b.profit,
               b.settled_at, b.notes,
               m.match_id, m.match_date, m.status AS match_status,
               m.home_score, m.away_score, m.home_ht_score, m.away_ht_score,
               m.home_score_regular, m.away_score_regular,
               m.home_score_et, m.away_score_et,
               m.home_score_pen, m.away_score_pen,
               m.match_duration, m.match_winner,
               m.home_team_id, m.away_team_id, m.league_id
        FROM bets b
        JOIN matches m ON m.match_id = b.match_id
    """
    params: tuple = ()
    if status:
        sql += " WHERE b.status = ?"
        params = (status,)
    sql += " ORDER BY b.placed_at DESC"
    rows = query(sql, params)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    teams = _team_name_map()
    leagues = _league_name_map()
    df["match"] = df.apply(
        lambda r: f"{teams.get(r['home_team_id'], '?')} vs {teams.get(r['away_team_id'], '?')}",
        axis=1,
    )
    df["league"] = df["league_id"].map(lambda x: leagues.get(x, ""))
    df["score"] = df.apply(_format_score, axis=1)
    df["result"] = df["status"].map({"won": "✓ Gagné", "lost": "✗ Perdu",
                                      "pending": "⏳ En attente", "void": "↩ Remboursé"})
    return df


def get_predictions_dataframe(match_date: datetime | None = None) -> pd.DataFrame:
    """Predictions joined with matches + teams + leagues."""
    sql = """
        SELECT p.id, p.match_id, p.market, p.selection, p.prob_model, p.confidence,
               p.best_odds, p.best_bookmaker, p.value,
               p.weighted_score, p.ml_score, p.created_at,
               m.match_date, m.home_team_id, m.away_team_id,
               m.status AS match_status,
               m.league_id, m.home_score, m.away_score
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
    df = pd.DataFrame([dict(r) for r in rows])
    teams = _team_name_map()
    leagues = _league_name_map()
    df["match"] = df.apply(
        lambda r: f"{teams.get(r['home_team_id'], '?')} vs {teams.get(r['away_team_id'], '?')}",
        axis=1,
    )
    df["league"] = df["league_id"].map(lambda x: leagues.get(x, ""))
    df["prob_model_pct"] = (df["prob_model"] * 100).round(1)
    df["confidence_pct"] = (df["confidence"] * 100).round(1)
    df["value_pct"] = (df["value"] * 100).round(1)
    return df


def get_kpi_metrics() -> dict[str, float]:
    bankroll_row = query("SELECT balance FROM bankroll_log ORDER BY at DESC LIMIT 1")
    current_bankroll = bankroll_row[0]["balance"] if bankroll_row else 0.0

    totals = query("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) AS won,
            SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) AS lost,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status='void' THEN 1 ELSE 0 END) AS voided,
            COALESCE(SUM(stake), 0) AS total_stake,
            COALESCE(SUM(profit), 0) AS total_profit
        FROM bets
    """)
    row = totals[0] if totals else None
    if not row:
        return {"bankroll": 0.0, "total": 0, "won": 0, "lost": 0,
                "pending": 0, "voided": 0,
                "hit_rate": 0.0, "roi": 0.0, "profit": 0.0, "total_stake": 0.0}

    total = row["total"] or 0
    won = row["won"] or 0
    lost = row["lost"] or 0
    settled = (won or 0) + (lost or 0)
    profit = row["total_profit"] or 0.0
    stake = row["total_stake"] or 0.0
    roi = (profit / stake) if stake else 0.0
    hit_rate = (won / settled) if settled else 0.0

    return {
        "bankroll": current_bankroll,
        "total": total,
        "won": won,
        "lost": lost,
        "pending": row["pending"] or 0,
        "voided": row["voided"] or 0,
        "hit_rate": hit_rate,
        "roi": roi,
        "profit": profit,
        "total_stake": stake,
    }


def get_date_range(days: int = 7) -> Iterable[datetime]:
    today = datetime.utcnow().date()
    for i in range(days):
        yield datetime.combine(today - timedelta(days=i), datetime.min.time())