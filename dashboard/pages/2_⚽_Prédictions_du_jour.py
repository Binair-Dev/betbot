import datetime as dt

import streamlit as st

from dashboard.auth import check_auth
from dashboard.utils import get_predictions_dataframe

if not check_auth():
    st.stop()

st.set_page_config(page_title="Prédictions du jour", page_icon="⚽", layout="wide")
st.title("⚽ Prédictions")

c1, c2 = st.columns([1, 3])
with c1:
    selected_date = st.date_input("Date du match", value=dt.date.today())
with c2:
    min_conf = st.slider("Confiance minimale", 0.0, 1.0, 0.0, 0.05,
                         format="%.0f%%", help="Filtrer les prédictions peu confiantes")

df = get_predictions_dataframe(
    match_date=dt.datetime.combine(selected_date, dt.datetime.min.time())
)
if not df.empty:
    df = df[df["confidence"] >= min_conf]

if df.empty:
    st.info(f"Aucune prédiction pour le {selected_date} (confiance ≥ {min_conf:.0%}).")
    st.caption("Le bot tourne à 00:00 heure belge pour analyser les matchs du lendemain.")
    st.stop()

st.caption(f"{len(df)} prédiction(s) pour le {selected_date}")

DISPLAY_COLS = [
    ("match", "Match"),
    ("league", "Ligue"),
    ("market", "Marché"),
    ("selection", "Sélection"),
    ("prob_model_pct", "Prob. modèle"),
    ("confidence_pct", "Confiance"),
    ("best_odds", "Cote"),
    ("best_bookmaker", "Bookmaker"),
    ("value_pct", "Value"),
]
display = df[[c for c, _ in DISPLAY_COLS if c in df.columns]].copy()
display.columns = [label for c, label in DISPLAY_COLS if c in df.columns]
if "Cote" in display.columns:
    display["Cote"] = display["Cote"].astype(float).round(2)
for col in ("Prob. modèle", "Confiance", "Value"):
    if col in display.columns:
        display[col] = display[col].astype(str) + "%"

st.dataframe(display, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Pourquoi ces prédictions ?")
st.caption("Confiance = probabilité que la sélection se réalise, calculée par le modèle.")
st.caption(
    "Value = (probabilité modèle × cote) - 1. Une value > 0% indique un edge vs le bookmaker. "
    "On parie uniquement si confiance ≥ 60% ET value ≥ 3%."
)

if "market" in df.columns:
    st.divider()
    st.subheader("Répartition par marché")
    counts = df["market"].value_counts().reset_index()
    counts.columns = ["Marché", "Nombre"]
    st.dataframe(counts, hide_index=True, use_container_width=True)