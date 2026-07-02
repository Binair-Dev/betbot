import datetime as dt

import pandas as pd
import streamlit as st

from betbot.db.repository import query
from dashboard.auth import check_auth

if not check_auth():
    st.stop()

st.set_page_config(page_title="Vue d'ensemble", page_icon="📊", layout="wide")

st.title("📊 Vue d'ensemble")
st.caption("Statut du scraper et volume de données collectées. Pas de paris, pas de modèle.")


# --- Headline numbers -------------------------------------------------------

headline = query("""
    SELECT
        (SELECT COUNT(*) FROM matches) AS n_matches,
        (SELECT COUNT(*) FROM matches WHERE status='FT') AS n_finished,
        (SELECT COUNT(*) FROM matches WHERE status IN ('NS','1H','2H','HT')) AS n_upcoming,
        (SELECT COUNT(*) FROM odds_history) AS n_odds,
        (SELECT COUNT(*) FROM teams) AS n_teams,
        (SELECT COUNT(*) FROM leagues) AS n_leagues
""")[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Matchs indexés", headline["n_matches"] or 0)
c2.metric("Terminés", headline["n_finished"] or 0)
c3.metric("À venir / live", headline["n_upcoming"] or 0)
c4.metric("Cotes stockées", headline["n_odds"] or 0)

c5, c6, _, _ = st.columns(4)
c5.metric("Ligues", headline["n_leagues"] or 0)
c6.metric("Équipes", headline["n_teams"] or 0)


# --- Per-league breakdown ---------------------------------------------------

st.divider()
st.subheader("📚 Couverture par ligue")

per_league = query("""
    SELECT l.name AS ligue, l.country AS pays,
           COUNT(m.match_id) AS matchs,
           SUM(CASE WHEN m.status='FT' THEN 1 ELSE 0 END) AS terminés,
           SUM(CASE WHEN m.status IN ('NS','1H','2H','HT') THEN 1 ELSE 0 END) AS à_venir
    FROM leagues l
    LEFT JOIN matches m ON m.league_id = l.league_id
    GROUP BY l.league_id
    ORDER BY matchs DESC
""")
if per_league:
    df_leagues = pd.DataFrame([dict(r) for r in per_league])
    df_leagues.columns = ["Ligue", "Pays", "Matchs", "Terminés", "À venir"]
    st.dataframe(df_leagues, use_container_width=True, hide_index=True)


# --- Coverage over time -----------------------------------------------------

st.divider()
st.subheader("📆 Matchs collectés par jour")

by_day = query("""
    SELECT date(match_date) AS jour, COUNT(*) AS n
    FROM matches
    GROUP BY date(match_date)
    ORDER BY jour
""")
if by_day:
    df_days = pd.DataFrame([dict(r) for r in by_day])
    df_days["jour"] = pd.to_datetime(df_days["jour"])
    st.line_chart(df_days, x="jour", y="n", height=220)


# --- Manual trigger ---------------------------------------------------------

st.divider()
st.subheader("🚀 Lancer un scrape maintenant")

b1, b2, b3, b4 = st.columns(4)
with b1:
    if st.button("🔄 Scrape complet", use_container_width=True):
        with st.spinner("Scrape complet en cours…"):
            from betbot.scheduler.scrape import scrape_all
            result = scrape_all(days_ahead=2)
        st.success(f"Fixtures: {result['fixtures']} · Résultats: {result['results']} · Cotes: {result['odds_matches']} match(s)")
        st.rerun()
with b2:
    if st.button("📋 Fixtures seulement", use_container_width=True):
        with st.spinner("Fixtures…"):
            from betbot.scheduler.scrape import scrape_fixtures
            result = scrape_fixtures(days_ahead=2)
        st.success(f"{sum(result.values())} match(s) collecté(s)")
        st.rerun()
with b3:
    if st.button("🏁 Résultats seulement", use_container_width=True):
        with st.spinner("Résultats…"):
            from betbot.scheduler.scrape import refresh_results
            st.json(refresh_results())
with b4:
    if st.button("💹 Cotes seulement", use_container_width=True):
        with st.spinner("Cotes…"):
            from betbot.scheduler.scrape import scrape_odds
            n = scrape_odds(days_ahead=2)
        st.success(f"{n} match(s) avec cotes")


# --- Footer -----------------------------------------------------------------

st.divider()
st.caption(
    "Scraper : football-data.org (fixtures + résultats) + The Odds API (cotes). "
    "Cron : 00:00 complet · 06:00, 12:00, 18:00, 23:00 cotes + résultats. "
    "Pas de paris, pas de modèle, pas de ML — juste les données."
)
