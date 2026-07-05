"""
Home & Safety page: what is this bot configured to do, and how do I stop it.

Shows the resolved (redacted) configuration, the risk limits, a kill-switch
toggle, and an on-demand read-only account panel (pUSD balance + open positions).
Nothing here places an order; the account read is authenticated but read-only.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import SETTINGS, Mode
from src import safety


def _config_panel() -> None:
    st.subheader("Configuration")
    st.caption("Secrets are redacted — the private key is never shown.")
    cfg = SETTINGS.redacted()  # already masks funder, omits the key entirely
    # Render as a simple two-column key/value table.
    df = pd.DataFrame({"setting": list(cfg.keys()), "value": [str(v) for v in cfg.values()]})
    st.dataframe(df, hide_index=True, width="stretch")


def _kill_switch_panel() -> None:
    st.subheader("Kill switch")
    st.caption("Creates/removes the KILL file. Any running simulation halts when it's on.")
    engaged = safety.kill_switch_engaged()
    new_state = st.toggle("Halt all quoting", value=engaged, key="kill_toggle")
    if new_state and not engaged:
        safety.engage_kill_switch("engaged via UI")
        st.rerun()
    elif not new_state and engaged:
        safety.KILL_FILE.unlink(missing_ok=True)
        st.rerun()
    if engaged:
        st.error("KILL switch is ENGAGED — quoting is halted.", icon="🛑")
    else:
        st.success("Kill switch is off — quoting allowed.", icon="✅")


def _account_panel() -> None:
    st.subheader("Account (read-only)")
    if not SETTINGS.private_key:
        st.info("Set PRIVATE_KEY in your .env to view your pUSD balance and positions.")
        return
    if SETTINGS.mode == Mode.READONLY:
        st.info("MODE=readonly: authenticated balance reads are disabled. Use simulation.")
        return

    st.caption("Authenticated read — runs L1→L2 auth against the CLOB. No funds move.")
    if not st.button("Load balance & positions"):
        return

    # Imported lazily so the page (and the rest of the app) loads even if the
    # SDK/auth path has an issue; only this button exercises it.
    from src.account import get_positions, get_pusd_balance
    from src.connection import build_clob_client

    with st.spinner("Authenticating and fetching account…"):
        try:
            client = build_clob_client()
            bal = get_pusd_balance(client)
        except Exception as exc:  # noqa: BLE001 - surface any auth/network error
            st.error(f"Could not read balance: {exc}")
            return

    c1, c2 = st.columns(2)
    c1.metric("pUSD balance", f"{bal['balance_pusd']:.4f}")
    c2.metric("Allowance", f"{bal['allowance_pusd']:.4f}")
    if bal["allowance_pusd"] <= 0:
        st.warning("Allowance is 0 — you'd hit 'not enough allowance' when trading.")

    address = SETTINGS.funder_address
    if not address:
        st.info("FUNDER_ADDRESS is unset, so positions can't be queried.")
        return
    try:
        positions = get_positions(address)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read positions: {exc}")
        return
    if not positions:
        st.write("No open positions above the size threshold.")
        return
    cols = ["outcome", "size", "avgPrice", "curPrice", "currentValue", "title"]
    rows = [{c: p.get(c) for c in cols} for p in positions]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render() -> None:
    st.title("🏠 Home & Safety")
    st.caption("Simulation-only environment — this app never sends a real order.")

    _config_panel()
    st.divider()
    _kill_switch_panel()
    st.divider()
    _account_panel()
