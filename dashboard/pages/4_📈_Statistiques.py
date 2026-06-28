import numpy as np
import pandas as pd
import streamlit as st

from dashboard.auth import check_auth
from dashboard.utils import get_bets_dataframe

if not check_auth():
    st.stop()

st.set_page_config(page_title="Statistiques", page_icon="📈", layout="wide")

st.title("📈 Statistiques")

df = get_bets_dataframe()
if df.empty:
    st.info("Pas encore de données.")
else:
    settled = df[df["status"].isin(["won", "lost"])].copy()
    if settled.empty:
        st.info("Aucun pari réglé pour l'instant.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("ROI par marché")
            roi_market = settled.groupby("market").agg(
                n=("id", "count"),
                won=("status", lambda x: (x == "won").sum()),
                profit=("profit", "sum"),
                stake=("stake", "sum"),
            )
            roi_market["roi"] = roi_market["profit"] / roi_market["stake"].replace(0, 1)
            roi_market["hit_rate"] = roi_market["won"] / roi_market["n"].replace(0, 1)
            roi_market = roi_market.round(4)
            st.dataframe(roi_market, use_container_width=True)

        with c2:
            st.subheader("Distribution des profits par pari")
            st.bar_chart(settled["profit"])

        st.divider()
        c3, c4 = st.columns(2)
        with c3:
            st.subheader("Courbe des profits cumulés")
            settled_sorted = settled.sort_values("placed_at")
            settled_sorted["cumulative"] = settled_sorted["profit"].cumsum()
            st.line_chart(settled_sorted, x="placed_at", y="cumulative")

        with c4:
            st.subheader("Distribution des cotes placées")
            st.bar_chart(settled["odds"])

        st.divider()
        st.subheader("Cotes vs Profit")
        if len(settled) > 5:
            st.scatter_chart(settled, x="odds", y="profit", color="status")

        st.divider()
        st.subheader("Métriques avancées")
        c5, c6, c7 = st.columns(3)
        with c5:
            avg_odds = settled["odds"].mean()
            st.metric("Cote moyenne", f"{avg_odds:.2f}")
        with c6:
            variance = settled["profit"].var()
            st.metric("Variance profit", f"{variance:.2f}")
        with c7:
            sharpe = (settled["profit"].mean() / settled["profit"].std() * np.sqrt(252)) \
                if settled["profit"].std() > 0 else 0
            st.metric("Sharpe annualisé", f"{sharpe:.2f}")
