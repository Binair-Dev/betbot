import pandas as pd
import streamlit as st

from dashboard.auth import check_auth
from dashboard.utils import get_bets_dataframe

if not check_auth():
    st.stop()

st.set_page_config(page_title="Historique paris", page_icon="💰", layout="wide")

st.title("💰 Historique des paris")

c1, c2, c3 = st.columns(3)
with c1:
    status_filter = st.selectbox("Statut", ["all", "pending", "won", "lost", "void"], index=0)
with c2:
    market_filter = st.selectbox(
        "Marché", ["all", "1X2", "over_under", "btts", "double_chance",
                   "correct_score", "draw_no_bet"],
        index=0,
    )
with c3:
    sort_by = st.selectbox("Trier par", ["placed_at", "stake", "odds", "profit"], index=0)

df = get_bets_dataframe(status=None if status_filter == "all" else status_filter)
if market_filter != "all" and not df.empty and "market" in df.columns:
    df = df[df["market"] == market_filter]

if df.empty:
    st.info("Aucun pari correspondant.")
else:
    df = df.sort_values(sort_by, ascending=False)
    st.caption(f"{len(df)} paris")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", len(df))
    if "stake" in df.columns:
        c2.metric("Mise cumulée", f"{df['stake'].sum():.2f}€")
    if "profit" in df.columns:
        c3.metric("Profit cumulé", f"{df['profit'].sum():.2f}€")
