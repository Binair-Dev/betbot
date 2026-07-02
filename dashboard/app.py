"""Betbot dashboard — entry point.

The bot is now a pure scraper. This dashboard shows:
- Vue d'ensemble: scraping status, league coverage, daily match volume,
  manual trigger buttons.
- Données brutes: every match + every bookmaker odds + final scores.

There are no predictions, no betting, no model output.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from betbot.config import settings
from betbot.db.repository import query
from dashboard.auth import check_auth

st.set_page_config(
    page_title="Betbot Scraper",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    if not check_auth():
        return

    with st.sidebar:
        st.title("⚽ Betbot Scraper")
        st.caption("Collecte de données brutes · pas de paris")
        st.divider()
        st.caption("**Sources**")
        st.caption("• football-data.org (fixtures, résultats)")
        st.caption("• The Odds API (cotes multi-bookmakers)")
        st.divider()
        st.caption("**Cron**")
        st.caption("00:00 — complet · 06/12/18/23h — cotes+résultats")
        st.divider()
        if st.button("🚪 Déconnexion"):
            st.session_state.authenticated = False
            st.rerun()

    st.title("⚽ Betbot Scraper")
    st.caption("Données brutes du football, sans modèle ni paris.")

    st.divider()

    # Headline numbers
    headline = query("""
        SELECT
            (SELECT COUNT(*) FROM matches) AS n_matches,
            (SELECT COUNT(*) FROM matches WHERE status='FT') AS n_finished,
            (SELECT COUNT(*) FROM matches WHERE status IN ('NS','1H','2H','HT')) AS n_upcoming,
            (SELECT COUNT(*) FROM odds_history) AS n_odds,
            (SELECT COUNT(*) FROM teams) AS n_teams,
            (SELECT COUNT(*) FROM leagues) AS n_leagues
    """)[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Matchs indexés", headline["n_matches"] or 0)
    col2.metric("Terminés", headline["n_finished"] or 0)
    col3.metric("À venir / live", headline["n_upcoming"] or 0)
    col4.metric("Cotes stockées", headline["n_odds"] or 0)

    col5, col6, _, _ = st.columns(4)
    col5.metric("Ligues", headline["n_leagues"] or 0)
    col6.metric("Équipes", headline["n_teams"] or 0)

    st.divider()
    st.subheader("🚀 Lancer un scrape")

    a, b, c, d = st.columns(4)
    with a:
        if st.button("🔄 Scrape complet", use_container_width=True):
            with st.spinner("Scrape en cours…"):
                try:
                    from betbot.scheduler.scrape import scrape_all
                    result = scrape_all(days_ahead=2)
                    st.success(
                        f"Fixtures: {sum(result['fixtures'].values())} · "
                        f"Résultats: {result['results']} · "
                        f"Cotes: {result['odds_matches']} match(s)"
                    )
                except Exception as exc:
                    st.error(f"Erreur: {exc}")
            st.rerun()
    with b:
        if st.button("📋 Fixtures", use_container_width=True):
            with st.spinner("Fixtures…"):
                try:
                    from betbot.scheduler.scrape import scrape_fixtures
                    result = scrape_fixtures(days_ahead=2)
                    st.success(f"{sum(result.values())} match(s) collecté(s)")
                except Exception as exc:
                    st.error(f"Erreur: {exc}")
            st.rerun()
    with c:
        if st.button("🏁 Résultats", use_container_width=True):
            with st.spinner("Résultats…"):
                try:
                    from betbot.scheduler.scrape import refresh_results
                    st.json(refresh_results())
                except Exception as exc:
                    st.error(f"Erreur: {exc}")
    with d:
        if st.button("💹 Cotes", use_container_width=True):
            with st.spinner("Cotes…"):
                try:
                    from betbot.scheduler.scrape import scrape_odds
                    n = scrape_odds(days_ahead=2)
                    st.success(f"{n} match(s) avec cotes")
                except Exception as exc:
                    st.error(f"Erreur: {exc}")

    st.divider()
    st.subheader("📅 Matchs à venir (7 prochains jours)")

    upcoming = query("""
        SELECT m.match_date, l.name AS league,
               th.name AS home_team, ta.name AS away_team, m.status
        FROM matches m
        LEFT JOIN teams th ON th.team_id = m.home_team_id
        LEFT JOIN teams ta ON ta.team_id = m.away_team_id
        LEFT JOIN leagues l ON l.league_id = m.league_id
        WHERE date(m.match_date) BETWEEN date('now') AND date('now', '+7 days')
        ORDER BY m.match_date
        LIMIT 50
    """)
    if upcoming:
        df = pd.DataFrame([dict(r) for r in upcoming])
        df["match_date"] = pd.to_datetime(df["match_date"]).dt.strftime("%d/%m %H:%M")
        df.columns = ["Date", "Ligue", "Domicile", "Extérieur", "Statut"]
        st.dataframe(df, use_container_width=True, hide_index=True, height=320)
    else:
        st.info("Aucun match à venir collecté. Lance un scrape.")

    st.divider()
    st.caption(
        "Pages : "
        "📊 Vue d'ensemble · "
        "🔍 Données brutes (chaque match + cotes par bookmaker)"
    )
    st.caption(f"Dernière mise à jour: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
