"""
Shared UI state and the sidebar.

Streamlit reruns the whole script on every interaction, so anything that must
survive across reruns (the selected market, a running live session) lives in
`st.session_state`. This module centralises the keys we use and the helpers to
read/write them, so pages don't poke at session_state with ad-hoc string keys.
"""

from __future__ import annotations

import streamlit as st

from config.settings import SETTINGS, Mode
from src import safety

# session_state keys (one place, so a typo can't create a silent second key)
SEL_MARKET = "sel_market"        # gamma.Market object
SEL_OUTCOME = "sel_outcome"      # e.g. "Yes" / "No" / "Up"
SEL_TOKEN = "sel_token_id"       # resolved token id (str)
LIVE_SESSION = "live_session"    # app.live.LiveSession or None (added in the live pages)


def init() -> None:
    """Set default values for our session_state keys (idempotent)."""
    st.session_state.setdefault(SEL_MARKET, None)
    st.session_state.setdefault(SEL_OUTCOME, None)
    st.session_state.setdefault(SEL_TOKEN, None)
    st.session_state.setdefault(LIVE_SESSION, None)


# --- selection helpers ----------------------------------------------------

def set_selection(market, outcome: str, token_id: str) -> None:
    st.session_state[SEL_MARKET] = market
    st.session_state[SEL_OUTCOME] = outcome
    st.session_state[SEL_TOKEN] = token_id


def selected_token() -> str | None:
    return st.session_state.get(SEL_TOKEN)


def selected_label() -> str:
    """A short human label for the current selection, for headers/sidebar."""
    market = st.session_state.get(SEL_MARKET)
    outcome = st.session_state.get(SEL_OUTCOME)
    if market is None:
        return "(no market selected)"
    return f"{market.question}  [{outcome}]"


# --- sidebar --------------------------------------------------------------

def render_sidebar() -> None:
    """Global sidebar: mode badge, kill-switch status, and current selection."""
    with st.sidebar:
        st.markdown("### Polymarket MM")

        # Mode badge. Simulation is the safe default; live trading isn't built.
        mode = SETTINGS.mode.value
        if SETTINGS.mode == Mode.SIMULATION:
            st.success(f"MODE: {mode}", icon="🧪")
        elif SETTINGS.mode == Mode.READONLY:
            st.info(f"MODE: {mode}", icon="👁️")
        else:  # live
            st.warning(f"MODE: {mode}", icon="⚠️")
        st.caption("Simulation-only app — no real orders are sent.")

        # Kill-switch status (toggled on the Home page).
        if safety.kill_switch_engaged():
            st.error("KILL switch ENGAGED", icon="🛑")
        else:
            st.caption("Kill switch: off")

        st.divider()
        st.caption("Selected market")
        token = selected_token()
        if token:
            st.write(selected_label())
            st.code(token, language=None)
        else:
            st.write("_none — pick one in Market Explorer_")
