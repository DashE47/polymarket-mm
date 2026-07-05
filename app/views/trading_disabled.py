"""
Live Trading — intentionally disabled placeholder.

Real order placement is NOT implemented in this project. This page exists only
to make that explicit and to document the gate that any future live trading must
pass. It has no working controls.
"""

from __future__ import annotations

import streamlit as st

from config.settings import SETTINGS


def render() -> None:
    st.title("💸 Live Trading")
    st.error("Live trading is not implemented. This app is simulation-only.", icon="🚫")

    st.markdown(
        """
        Placing real orders requires work that is deliberately **not** part of this
        project yet:

        - V2 order **signing**, submission, and cancellation against the CLOB.
        - A funded wallet with **pUSD** and the right `SIGNATURE_TYPE`/allowances.
        - Hard gates so it can never fire by accident.

        **The gate any future live trading must pass**

        1. `MODE=live` in your `.env`, **and**
        2. `CONFIRM_LIVE=YES` in your `.env`.

        Only when both are set does `SETTINGS.is_live` become true. Until live
        trading is built, these flags do nothing and this page stays disabled.
        """
    )

    c1, c2 = st.columns(2)
    c1.metric("MODE", SETTINGS.mode.value)
    c2.metric("CONFIRM_LIVE", "YES" if SETTINGS.confirm_live else "NO")
    st.button("Place order", disabled=True, help="Disabled — live trading is not implemented.")
