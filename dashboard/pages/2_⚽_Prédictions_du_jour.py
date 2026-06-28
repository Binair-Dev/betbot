import datetime as dt

import pandas as pd
import streamlit as st

from dashboard.auth import check_auth
from dashboard.utils import get_predictions_dataframe

if not check_auth():
    st.stop()

st.set_page_config(page_title="Prédictions du jour", page_icon="⚽", layout="wide")

st.title("⚽ Prédictions du jour")

today = st.date_input("Date du match", value=dt.date.today())

df = get_predictions_dataframe(match_date=dt.datetime.combine(today, dt.datetime.min.time()))

if df.empty:
    st.info(f"Aucune prédiction pour le {today}.")
    st.caption("Le bot tourne à 00:00 heure belge pour analyser les matchs du lendemain.")
else:
    st.caption(f"{len(df)} prédictions trouvées")
    cols_to_show = [c for c in [
        "match_id", "market", "selection", "prob_model", "confidence",
        "best_odds", "best_bookmaker", "value", "weighted_score", "ml_score",
    ] if c in df.columns]
    st.dataframe(
        df[cols_to_show].sort_values("confidence", ascending=False),
        use_container_width=True, hide_index=True,
    )

    if "confidence" in df.columns:
        st.divider()
        st.subheader("Distribution des confiances")
        st.bar_chart(df["confidence"])

    if "market" in df.columns:
        st.divider()
        st.subheader("Prédictions par marché")
        mkt_counts = df["market"].value_counts().reset_index()
        mkt_counts.columns = ["market", "count"]
        st.dataframe(mkt_counts, hide_index=True, use_container_width=True)
