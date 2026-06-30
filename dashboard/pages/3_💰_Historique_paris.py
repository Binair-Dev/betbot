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
    status_filter = st.selectbox(
        "Statut",
        ["all", "won", "lost", "pending", "void"],
        index=0,
        format_func=lambda s: {
            "all": "Tous", "won": "✓ Gagnés", "lost": "✗ Perdus",
            "pending": "⏳ En attente", "void": "↩ Remboursés",
        }.get(s, s),
    )
with c2:
    market_filter = st.selectbox(
        "Marché",
        ["all", "1X2", "over_under", "btts", "double_chance",
         "correct_score", "draw_no_bet"],
        index=0,
        format_func=lambda s: "Tous" if s == "all" else s,
    )
with c3:
    sort_by = st.selectbox(
        "Trier par",
        ["placed_at", "match_date", "stake", "odds", "profit"],
        index=0,
    )

df = get_bets_dataframe(status=None if status_filter == "all" else status_filter)
if market_filter != "all" and not df.empty and "market" in df.columns:
    df = df[df["market"] == market_filter]

if df.empty:
    st.info("Aucun pari correspondant.")
    st.stop()

df = df.sort_values(sort_by, ascending=False, na_position="last")
st.caption(f"{len(df)} pari(s)")

DISPLAY_COLS = [
    ("placed_at", "Date"),
    ("match", "Match"),
    ("league", "Ligue"),
    ("market", "Marché"),
    ("selection", "Sélection"),
    ("odds", "Cote"),
    ("stake", "Mise"),
    ("score", "Score final"),
    ("result", "Résultat"),
    ("payout", "Payout"),
    ("profit", "Profit"),
    ("value", "Value"),
    ("confidence", "Confiance"),
]
display = df[[c for c, _ in DISPLAY_COLS if c in df.columns]].copy()
display.columns = [label for c, label in DISPLAY_COLS if c in df.columns]

if "value" in display.columns:
    display["value"] = (display["value"].astype(float) * 100).round(1).astype(str) + "%"
if "confidence" in display.columns:
    display["Confiance"] = (display["Confiance"].astype(float) * 100).round(1).astype(str) + "%"
if "Cote" in display.columns:
    display["Cote"] = display["Cote"].astype(float).round(2)
if "Mise" in display.columns:
    display["Mise"] = display["Mise"].astype(float).round(2).astype(str) + "€"
if "Payout" in display.columns:
    display["Payout"] = display["Payout"].apply(
        lambda x: "—" if pd.isna(x) else f"{x:.2f}€"
    )
if "Profit" in display.columns:
    display["Profit"] = display["Profit"].apply(
        lambda x: "—" if pd.isna(x) else f"{x:+.2f}€"
    )

st.dataframe(display, use_container_width=True, hide_index=True)

st.divider()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Paris", len(df))
m2.metric("Mise totale", f"{df['stake'].sum():.2f}€")
m3.metric("Profit cumulé", f"{df['profit'].sum():+.2f}€")
settled_mask = df["status"].isin(["won", "lost"])
if settled_mask.any():
    roi = df.loc[settled_mask, "profit"].sum() / df.loc[settled_mask, "stake"].sum()
    m4.metric("ROI", f"{roi:+.1%}")
else:
    m4.metric("ROI", "—")