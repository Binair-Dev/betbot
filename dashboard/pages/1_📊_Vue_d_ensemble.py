import streamlit as st

from dashboard.auth import check_auth
from dashboard.utils import get_kpi_metrics

if not check_auth():
    st.stop()

st.set_page_config(page_title="Vue d'ensemble", page_icon="📊", layout="wide")

st.title("📊 Vue d'ensemble")

kpis = get_kpi_metrics()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Bankroll actuelle", f"{kpis['bankroll']:.2f}€")
c2.metric("Paris totaux", kpis["total"])
c3.metric("Hit rate", f"{kpis['hit_rate']:.1%}")
c4.metric("ROI global", f"{kpis['roi']:.2%}")

st.divider()

c5, c6, c7, c8 = st.columns(4)
c5.metric("Paris gagnés", kpis["won"])
c6.metric("Paris perdus", kpis["lost"])
c7.metric("Mise totale", f"{kpis['total_stake']:.2f}€")
c8.metric("Profit net", f"{kpis['profit']:.2f}€")

st.divider()
st.subheader("📈 Statistiques détaillées")

c9, c10 = st.columns(2)
with c9:
    st.metric("Mise moyenne", f"{kpis['total_stake'] / max(1, kpis['total']):.2f}€")
    if kpis['total']:
        avg_odds = 0.0
        # We'd need to query avg odds; keep simple
        st.caption("Profit moyen / pari:", f"{kpis['profit'] / max(1, kpis['won'] + kpis['lost']):.2f}€")
with c10:
    if kpis['roi'] > 0:
        st.success(f"✅ Stratégie profitable (ROI +{kpis['roi']:.2%})")
    elif kpis['total'] > 0:
        st.warning(f"⚠️ ROI négatif ({kpis['roi']:.2%})")
    else:
        st.info("Aucun pari enregistré pour le moment.")
