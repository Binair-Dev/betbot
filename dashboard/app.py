"""Betbot Streamlit dashboard — entry point."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from betbot.config import settings
from betbot.db.repository import query
from dashboard.auth import check_auth

st.set_page_config(
    page_title="Betbot Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    if not check_auth():
        return

    with st.sidebar:
        st.title("⚽ Betbot")
        st.caption(f"Bankroll: {settings.BANKROLL_START:.0f}€ · Mise: {settings.BET_SIZE:.0f}€")
        st.divider()
        st.caption("**Seuils**")
        st.caption(f"Confiance ≥ {settings.CONFIDENCE_THRESHOLD:.0%}")
        st.caption(f"Value ≥ {settings.VALUE_THRESHOLD:.0%}")
        st.divider()
        if st.button("🚪 Déconnexion"):
            st.session_state.authenticated = False
            st.rerun()

    st.title("⚽ Betbot Dashboard")
    st.caption(f"Bot de value betting automatisé · TZ: {settings.TIMEZONE}")

    st.divider()

    bankroll_row = query("SELECT balance FROM bankroll_log ORDER BY at DESC LIMIT 1")
    current_bankroll = bankroll_row[0]["balance"] if bankroll_row else settings.BANKROLL_START

    bets_total_row = query("SELECT COUNT(*) AS c FROM bets")
    bets_total = bets_total_row[0]["c"] if bets_total_row else 0

    bets_won_row = query("SELECT COUNT(*) AS c FROM bets WHERE status='won'")
    bets_won = bets_won_row[0]["c"] if bets_won_row else 0

    profit_row = query("SELECT COALESCE(SUM(profit), 0) AS p FROM bets WHERE status IN ('won','lost')")
    profit = profit_row[0]["p"] if profit_row else 0.0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Bankroll", f"{current_bankroll:.2f}€",
                  delta=f"{current_bankroll - settings.BANKROLL_START:.2f}€")
    with col2:
        st.metric("Paris placés", bets_total)
    with col3:
        hit_rate = (bets_won / bets_total) if bets_total else 0.0
        st.metric("Hit rate", f"{hit_rate:.1%}")
    with col4:
        st.metric("Profit", f"{profit:.2f}€")

    st.divider()
    st.subheader("Évolution bankroll")

    history = query("SELECT at, balance FROM bankroll_log ORDER BY at")
    if history:
        df = pd.DataFrame([dict(r) for r in history])
        df["at"] = pd.to_datetime(df["at"])
        st.line_chart(df, x="at", y="balance")
    else:
        st.info("Aucune donnée — le bot n'a pas encore tourné.")

    st.divider()
    st.subheader("Actions manuelles")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("🔄 Analyse du jour", use_container_width=True):
            with st.spinner("Analyse en cours…"):
                try:
                    from betbot.scheduler.jobs import job_analyze_and_bet
                    job_analyze_and_bet()
                    st.success("Analyse terminée — voir les prédictions du jour.")
                except Exception as exc:
                    st.error(f"Erreur: {exc}")
    with col_b:
        if st.button("⚖️ Régler les résultats", use_container_width=True):
            with st.spinner("Règlement en cours…"):
                try:
                    from betbot.scheduler.jobs import job_settle_results
                    job_settle_results()
                    st.success("Règlement terminé.")
                except Exception as exc:
                    st.error(f"Erreur: {exc}")
    with col_c:
        if st.button("📊 Recalculer Elo", use_container_width=True):
            with st.spinner("Recalcul Elo en cours…"):
                try:
                    from betbot.scheduler.jobs import job_recompute_elo
                    job_recompute_elo()
                    st.success("Elo mis à jour.")
                except Exception as exc:
                    st.error(f"Erreur: {exc}")

    col_d, _ = st.columns([1, 2])
    with col_d:
        if st.button("🗑️ Vider le cache API", use_container_width=True):
            try:
                from betbot.data.cache import _raw_connect
                conn = _raw_connect()
                cur = conn.execute("DELETE FROM api_cache")
                deleted = cur.rowcount
                conn.commit()
                conn.close()
                st.success(f"Cache vidé — {deleted} entrées supprimées.")
            except Exception as exc:
                st.error(f"Erreur: {exc}")

    st.divider()
    st.subheader("État du système")

    c1, c2 = st.columns(2)
    with c1:
        st.caption("**Calendrier des jobs**")
        st.code("""
00:00 Europe/Brussels — Analyse & paris du jour
06:00 — Recalcul Elo ratings
23:00 — Règlement des résultats
        """, language="yaml")
    with c2:
        st.caption("**Pages**")
        st.markdown("""
        - 📊 Vue d'ensemble : KPIs globaux
        - ⚽ Prédictions du jour : prédictions en cours
        - 💰 Historique : tous les paris
        - 📈 Statistiques : ROI par marché/ligue
        """)

    st.divider()
    st.caption(f"Dernière mise à jour: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
