"""Streamlit authentication helper."""
from __future__ import annotations

import hmac
import os

import streamlit as st

from betbot.config import settings


def check_auth() -> bool:
    """Simple password-based authentication.

    Returns True if authenticated, otherwise displays login form.
    """
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("🔒 Betbot — Connexion")
    st.caption("Authentification requise pour accéder au dashboard.")
    with st.form("login_form"):
        username = st.text_input("Utilisateur")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter")
        if submitted:
            expected_user = settings.DASHBOARD_USER
            expected_pwd = settings.DASHBOARD_PASSWORD
            if hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_pwd):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Identifiants incorrects.")
    return False
