"""Page 5: Raw scraped data — every match + every bookmaker + every score.

This page is the entire purpose of the bot: show what we've actually
collected from the APIs, with no predictions, no model, no bets.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from betbot.db.repository import query
from dashboard.auth import check_auth

if not check_auth():
    st.stop()

st.set_page_config(page_title="Données brutes", page_icon="🔍", layout="wide")
st.title("🔍 Données brutes")
st.caption("Tout ce que le bot a scrapé. Pas de modèle, pas de pari — juste les données.")


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

f1, f2, f3 = st.columns([1, 1, 2])
with f1:
    days_back = st.selectbox("Période", [1, 2, 3, 7, 14, 30], index=2,
                             format_func=lambda d: f"{d} jour(s)")
with f2:
    league_filter = st.selectbox(
        "Ligue",
        ["Toutes"] + [r["name"] for r in query(
            "SELECT DISTINCT l.name FROM leagues l "
            "JOIN matches m ON m.league_id = l.league_id "
            "ORDER BY l.name"
        )],
    )
with f3:
    status_filter = st.multiselect(
        "Statut",
        ["NS", "1H", "HT", "2H", "FT", "AET", "PEN"],
        default=["NS", "FT", "AET", "PEN"],
    )

# ---------------------------------------------------------------------------
# Big matches table
# ---------------------------------------------------------------------------

since = (datetime.utcnow() - timedelta(days=days_back)).date().isoformat()
params: list = [since]
where_extra = ""
if league_filter != "Toutes":
    where_extra += " AND l.name = ?"
    params.append(league_filter)
if status_filter:
    placeholders = ",".join("?" * len(status_filter))
    where_extra += f" AND m.status IN ({placeholders})"
    params.extend(status_filter)

matches = query(
    f"""
    SELECT m.match_id, m.match_date,
           l.name AS league, m.season,
           th.name AS home_team, ta.name AS away_team,
           m.status, m.home_score, m.away_score,
           m.home_ht_score, m.away_ht_score,
           m.home_score_regular, m.away_score_regular,
           m.home_score_et, m.away_score_et,
           m.home_score_pen, m.away_score_pen,
           m.match_duration, m.match_winner
    FROM matches m
    LEFT JOIN teams th ON th.team_id = m.home_team_id
    LEFT JOIN teams ta ON ta.team_id = m.away_team_id
    LEFT JOIN leagues l ON l.league_id = m.league_id
    WHERE date(m.match_date) >= date(?)
    {where_extra}
    ORDER BY m.match_date DESC
    """,
    tuple(params),
)

if not matches:
    st.info(f"Aucun match pour ces filtres.")
    st.stop()

df = pd.DataFrame([dict(r) for r in matches])


def _fmt_score(row):
    h, a = row.get("home_score"), row.get("away_score")
    if h is None or a is None:
        return "—"
    reg_h = row.get("home_score_regular")
    reg_a = row.get("away_score_regular")
    et_h, et_a = row.get("home_score_et") or 0, row.get("away_score_et") or 0
    pen_h, pen_a = row.get("home_score_pen") or 0, row.get("away_score_pen") or 0
    dur = row.get("match_duration")
    if dur == "PENALTY_SHOOTOUT" and reg_h is not None:
        return f"{reg_h}-{reg_a} → {h}-{a} (tab {pen_h}-{pen_a})"
    if dur == "EXTRA_TIME" and reg_h is not None and (reg_h, reg_a) != (h, a):
        return f"{reg_h}-{reg_a} → {h}-{a} (a.p.)"
    return f"{h}-{a}"


def _fmt_status(row):
    s = row.get("status") or "—"
    if s in ("FT", "AET", "PEN"):
        return f"✓ {s}"
    if s in ("1H", "2H", "HT"):
        return f"🟢 {s} live"
    return f"⏳ {s}"


df["Score"] = df.apply(_fmt_score, axis=1)
df["Statut"] = df.apply(_fmt_status, axis=1)
df["Date"] = pd.to_datetime(df["match_date"]).dt.strftime("%d/%m %H:%M")
df["Winner"] = df["match_winner"].fillna("—")

display = df[["Date", "league", "home_team", "away_team", "Score", "Statut", "Winner"]].copy()
display.columns = ["Date", "Ligue", "Domicile", "Extérieur", "Score", "Statut", "Vainqueur"]
st.caption(f"{len(display)} match(s)")
st.dataframe(display, use_container_width=True, hide_index=True, height=420)


# ---------------------------------------------------------------------------
# Match drill-down: odds, breakdown
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Détail d'un match")

match_labels = {
    f"{r['Date']} — {r['home_team']} vs {r['away_team']}  [{r['status']}]": r["match_id"]
    for _, r in df.iterrows()
}
if not match_labels:
    st.stop()

chosen = st.selectbox("Match", list(match_labels.keys()))
match_id = match_labels[chosen]

# Header
header_row = df[df["match_id"] == match_id].iloc[0]
hc1, hc2, hc3, hc4 = st.columns(4)
hc1.metric("Domicile", header_row["home_team"])
hc2.metric("Score", header_row["Score"] or "—")
hc3.metric("Extérieur", header_row["away_team"])
hc4.metric("Statut", f"{header_row['status']} ({header_row.get('match_duration') or '—'})")

# Odds comparison across bookmakers
st.divider()
st.subheader("💹 Cotes par bookmaker")

odds_rows = query(
    """
    SELECT bookmaker, market, selection, odds, implied_prob, fetched_at
    FROM odds_history
    WHERE match_id = ?
    ORDER BY market, selection, bookmaker, odds DESC
    """,
    (match_id,),
)

if odds_rows:
    df_odds = pd.DataFrame([dict(r) for r in odds_rows])
    markets_avail = sorted(df_odds["market"].unique().tolist())
    chosen_markets = st.multiselect("Filtrer marchés", markets_avail, default=markets_avail)
    df_odds = df_odds[df_odds["market"].isin(chosen_markets)]

    if df_odds.empty:
        st.info("Aucun résultat pour les marchés sélectionnés.")
    else:
        # Pivot: for each market+selection, show odds from each bookmaker
        pivot = df_odds.pivot_table(
            index=["market", "selection"],
            columns="bookmaker",
            values="odds",
            aggfunc="max",
        )
        # Add best-odds column
        pivot["BEST"] = pivot.max(axis=1)
        pivot["% implied"] = (1 / pivot["BEST"]).map(lambda x: f"{x:.1%}")
        pivot = pivot.reset_index()
        st.dataframe(pivot, use_container_width=True, hide_index=True)
        st.caption(f"{len(odds_rows)} entrées · {df_odds['bookmaker'].nunique()} bookmaker(s)")

        # Best-odds summary per market
        st.markdown("**Meilleure cote par marché/sélection :**")
        best = (
            df_odds.sort_values("odds", ascending=False)
            .groupby(["market", "selection"], as_index=False)
            .first()[["market", "selection", "bookmaker", "odds", "implied_prob"]]
        )
        best["implied_prob"] = best["implied_prob"].map(
            lambda x: f"{x:.1%}" if x is not None else "—"
        )
        best.columns = ["Marché", "Sélection", "Bookmaker", "Cote", "Prob. implicite"]
        st.dataframe(best, use_container_width=True, hide_index=True)
else:
    st.info("Aucune cote enregistrée pour ce match.")


# ---------------------------------------------------------------------------
# KPI footer
# ---------------------------------------------------------------------------

st.divider()
kpi = query("""
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN status='FT' THEN 1 ELSE 0 END) AS ft,
        SUM(CASE WHEN status IN ('NS','1H','2H','HT') THEN 1 ELSE 0 END) AS upcoming,
        COUNT(DISTINCT league_id) AS leagues
    FROM matches
    WHERE date(match_date) >= date(?)
""", (since,))[0]

k1, k2, k3, k4 = st.columns(4)
k1.metric("Matchs (période)", kpi["total"] or 0)
k2.metric("Terminés", kpi["ft"] or 0)
k3.metric("À venir / live", kpi["upcoming"] or 0)
k4.metric("Ligues", kpi["leagues"] or 0)

n_odds = query("SELECT COUNT(*) AS c FROM odds_history")[0]["c"] or 0
n_teams = query("SELECT COUNT(*) AS c FROM teams")[0]["c"] or 0
st.caption(f"Base : {n_odds} cotes · {n_teams} équipes indexées · scraper tourne en cron toutes les 6h")
