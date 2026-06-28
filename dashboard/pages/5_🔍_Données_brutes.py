"""Page 5: Données brutes par match — inspection complète de chaque feature, cote, blessure."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st

from betbot.db.repository import query
from dashboard.auth import check_auth

if not check_auth():
    st.stop()

st.set_page_config(page_title="Données brutes", page_icon="🔍", layout="wide")
st.title("🔍 Données brutes par match")

# ---------------------------------------------------------------------------
# Date + match selector
# ---------------------------------------------------------------------------
selected_date = st.date_input("Date", value=datetime.today().date())

matches = query(
    """
    SELECT m.match_id, m.match_date, m.league_id, m.season,
           t1.name AS home_team, t2.name AS away_team,
           m.home_score, m.away_score, m.status, m.referee, m.venue
    FROM matches m
    LEFT JOIN teams t1 ON t1.team_id = m.home_team_id
    LEFT JOIN teams t2 ON t2.team_id = m.away_team_id
    WHERE date(m.match_date) = date(?)
    ORDER BY m.match_date
    """,
    (selected_date.isoformat(),),
)

if not matches:
    st.info(f"Aucun match enregistré pour le {selected_date}.")
    st.caption("Les matchs sont enregistrés lors du pipeline quotidien (00h00).")
    st.stop()

match_labels = {
    f"{r['home_team']} vs {r['away_team']}  [id:{r['match_id']}]": dict(r)
    for r in matches
}
chosen_label = st.selectbox("Match", list(match_labels.keys()))
match = match_labels[chosen_label]
match_id = match["match_id"]

# ---------------------------------------------------------------------------
# Match header
# ---------------------------------------------------------------------------
st.divider()
home = match["home_team"] or "?"
away = match["away_team"] or "?"
st.subheader(f"{home}  —  {away}")

c1, c2, c3, c4, c5 = st.columns(5)
raw_date = match["match_date"] or ""
try:
    nice_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).strftime("%d/%m %H:%M")
except (ValueError, TypeError):
    nice_date = str(raw_date)

c1.metric("Date", nice_date)
c2.metric("Statut", match["status"] or "—")
score = (
    f"{match['home_score']} - {match['away_score']}"
    if match["home_score"] is not None
    else "À venir"
)
c3.metric("Score", score)
c4.metric("Arbitre", match["referee"] or "N/A")
c5.metric("Stade", match["venue"] or "N/A")

# ---------------------------------------------------------------------------
# Prédictions du modèle
# ---------------------------------------------------------------------------
st.divider()
st.subheader("📊 Prédictions du modèle")

preds = query(
    """
    SELECT market, selection, prob_model, confidence, best_odds, best_bookmaker,
           value, weighted_score, ml_score, features_json, created_at
    FROM predictions
    WHERE match_id = ?
    ORDER BY confidence DESC
    """,
    (match_id,),
)

features: dict | None = None

if preds:
    df_preds = pd.DataFrame([dict(r) for r in preds])
    display_cols = [c for c in [
        "market", "selection", "prob_model", "confidence",
        "best_odds", "best_bookmaker", "value", "weighted_score", "ml_score",
    ] if c in df_preds.columns]

    def _fmt(df: pd.DataFrame) -> pd.DataFrame:
        for col in ("prob_model", "confidence", "weighted_score", "ml_score", "value"):
            if col in df.columns:
                df[col] = df[col].apply(lambda x: f"{x:.2%}" if x is not None else "—")
        if "best_odds" in df.columns:
            df["best_odds"] = df["best_odds"].apply(lambda x: f"{x:.2f}" if x is not None else "—")
        return df

    st.dataframe(
        _fmt(df_preds[display_cols].copy()),
        use_container_width=True,
        hide_index=True,
    )

    raw_json = preds[0]["features_json"]
    if raw_json:
        try:
            features = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            features = None
else:
    st.info("Aucune prédiction enregistrée pour ce match.")

# ---------------------------------------------------------------------------
# Feature breakdown
# ---------------------------------------------------------------------------
st.divider()
st.subheader("🧩 Détail des features")

if features:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Δ Home", f"{features.get('delta_home', 0):+.4f}")
    m2.metric("Δ Draw", f"{features.get('delta_draw', 0):+.4f}")
    m3.metric("Δ Away", f"{features.get('delta_away', 0):+.4f}")
    m4.metric("Confiance globale", f"{features.get('confidence', 0):.2%}")

    missing = features.get("missing_features", [])
    if missing:
        st.warning(f"Features sans données : {', '.join(missing)}")

    breakdown = features.get("breakdown", {})
    if breakdown:
        st.markdown("---")
        st.caption("Cliquer sur une feature pour voir le détail complet")

        for feat_name, feat_data in sorted(breakdown.items()):
            is_missing = feat_data.get("missing", False)
            icon = "⚠️" if is_missing else "✅"

            if not is_missing:
                delta = feat_data.get("delta", [0.0, 0.0, 0.0])
                conf = feat_data.get("confidence", 0.0)
                weight = feat_data.get("weight", 0.0)
                header = (
                    f"{icon} **{feat_name}** — "
                    f"conf={conf:.0%} · poids={weight:.0%} · "
                    f"Δhome={delta[0]:+.3f} · Δdraw={delta[1]:+.3f} · Δaway={delta[2]:+.3f}"
                )
            else:
                header = f"{icon} **{feat_name}** — données manquantes"

            with st.expander(header, expanded=False):
                if not is_missing:
                    d = feat_data.get("delta", [0.0, 0.0, 0.0])
                    fc1, fc2, fc3, fc4 = st.columns(4)
                    fc1.metric("Δ Home", f"{d[0]:+.4f}")
                    fc2.metric("Δ Draw", f"{d[1]:+.4f}")
                    fc3.metric("Δ Away", f"{d[2]:+.4f}")
                    fc4.metric("Confiance", f"{feat_data.get('confidence', 0):.2%}")

                raw = feat_data.get("raw", {})
                if raw:
                    st.json(raw)
else:
    st.info("Aucune donnée feature disponible pour ce match.")

# ---------------------------------------------------------------------------
# Cotes du marché
# ---------------------------------------------------------------------------
st.divider()
st.subheader("💹 Cotes du marché")

odds_rows = query(
    """
    SELECT bookmaker, market, selection, odds, implied_prob, fetched_at
    FROM odds_history
    WHERE match_id = ?
    ORDER BY market, selection, odds DESC
    """,
    (match_id,),
)

if odds_rows:
    df_odds = pd.DataFrame([dict(r) for r in odds_rows])
    available_markets = sorted(df_odds["market"].unique().tolist())
    selected_markets = st.multiselect(
        "Filtrer par marché",
        options=available_markets,
        default=available_markets,
    )
    df_filtered = df_odds[df_odds["market"].isin(selected_markets)]
    if "implied_prob" in df_filtered.columns:
        df_filtered = df_filtered.copy()
        df_filtered["implied_prob"] = df_filtered["implied_prob"].apply(
            lambda x: f"{x:.2%}" if x is not None else "—"
        )
    st.dataframe(df_filtered, use_container_width=True, hide_index=True)
    st.caption(f"{len(df_filtered)} entrées · {df_odds['bookmaker'].nunique()} bookmakers")
else:
    st.info("Aucune cote enregistrée pour ce match.")

# ---------------------------------------------------------------------------
# Blessures / Suspensions
# ---------------------------------------------------------------------------
st.divider()
st.subheader("🏥 Blessures & Suspensions")

injuries = query(
    """
    SELECT t.name AS equipe, i.player_name AS joueur, i.reason AS raison,
           i.importance, i.expected_return AS retour
    FROM injuries i
    LEFT JOIN teams t ON t.team_id = i.team_id
    WHERE i.fixture_id = ?
    ORDER BY t.name, i.importance DESC
    """,
    (match_id,),
)

if injuries:
    df_inj = pd.DataFrame([dict(r) for r in injuries])
    st.dataframe(df_inj, use_container_width=True, hide_index=True)
else:
    st.info("Aucune blessure enregistrée pour ce match.")

# ---------------------------------------------------------------------------
# Paris placés
# ---------------------------------------------------------------------------
st.divider()
st.subheader("🎯 Paris placés sur ce match")

bets = query(
    """
    SELECT market, selection, odds, bookmaker, stake, confidence, value,
           status, profit, placed_at, settled_at
    FROM bets
    WHERE match_id = ?
    ORDER BY placed_at
    """,
    (match_id,),
)

if bets:
    df_bets = pd.DataFrame([dict(r) for r in bets])
    for col in ("confidence", "value"):
        if col in df_bets.columns:
            df_bets[col] = df_bets[col].apply(lambda x: f"{x:.2%}" if x is not None else "—")
    st.dataframe(df_bets, use_container_width=True, hide_index=True)
else:
    st.info("Aucun pari placé sur ce match.")

# ---------------------------------------------------------------------------
# JSON brut complet (debug)
# ---------------------------------------------------------------------------
st.divider()
with st.expander("🛠️ JSON brut complet (debug)", expanded=False):
    if features:
        st.json(features)
    else:
        st.info("Aucune donnée JSON disponible.")
