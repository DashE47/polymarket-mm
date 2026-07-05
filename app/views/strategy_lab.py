"""
Strategy Lab: run the market-making strategy in SIMULATION against the LIVE book.

Two modes, same machinery (a LiveSession with a SimEngine attached):
  * Fixed duration — set seconds; it auto-stops and you read the result.
  * Continuous     — runs until you press Stop, charts updating live.

Everything streams in a background thread; the panel re-renders each second via
st.fragment. Respects the risk limits and the kill switch (toggling the kill
switch on the Home page halts a running sim). No real orders are ever sent.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import charts, state
from app.live import LiveSession
from config.settings import SETTINGS
from src.analytics import compute_metrics
from src.strategy import StrategyConfig

_SESSION = "sim_session"


def _params() -> StrategyConfig:
    c1, c2, c3 = st.columns(3)
    spread = c1.number_input("spread", 0.001, 0.5, 0.02, step=0.002, format="%.3f")
    size = c1.number_input("size (shares)", 1.0, 10000.0, 100.0, step=10.0)
    skew = c2.number_input("inventory skew", 0.0, 0.2, 0.005, step=0.001, format="%.3f")
    widen = c2.number_input("inventory widen", 0.0, 0.2, 0.005, step=0.001, format="%.3f")
    requote = c3.number_input("requote threshold", 0.0, 0.1, 0.002, step=0.001, format="%.3f")
    return StrategyConfig(spread=spread, size=size, inventory_skew=skew,
                          inventory_widen=widen, requote_threshold=requote)


def render() -> None:
    st.title("🧪 Strategy Lab — live simulation")
    st.caption("Simulated fills against the REAL live book. No real orders. "
               "Optimistic fill model — treat P&L as a comparison tool, not a promise.")

    token = state.selected_token()
    if not token:
        st.info("Select a market in the Market Explorer first.")
        return
    st.caption(state.selected_label())

    cfg = _params()
    c1, c2 = st.columns(2)
    duration = c1.number_input("Duration (seconds, 0 = until Stop)", 0, 3600, 60, step=10)
    st.caption(f"Risk limits (from .env): max position ${SETTINGS.max_position_usd:g} · "
               f"max daily loss ${SETTINGS.max_daily_loss_usd:g}")

    sess: LiveSession | None = st.session_state.get(_SESSION)
    if sess and sess.token_id != token:
        sess.stop()
        sess = None
        st.session_state[_SESSION] = None

    b1, b2 = st.columns(2)
    if b1.button("▶ Start simulation", type="primary", disabled=bool(sess and sess.running)):
        s = LiveSession(token, cfg=cfg, to_file=True)
        s.start(duration=float(duration) or None)
        st.session_state[_SESSION] = s
        st.rerun()
    if b2.button("⏹ Stop", disabled=not (sess and sess.running)):
        sess.stop()
        st.rerun()

    if not sess:
        st.info("Set parameters and press Start.")
        return

    @st.fragment(run_every="1s")
    def _panel() -> None:
        es = sess.engine_snapshot()
        if not es or es["summary"] is None:
            st.info("Waiting for the first book update…")
            return
        s = es["summary"]
        metrics = compute_metrics(es["events"])

        cols = st.columns(5)
        cols[0].metric("Position", f"{s['position']:+.0f}")
        cols[1].metric("Realized", f"{s['realized_pnl']:+.4f}")
        cols[2].metric("Unrealized", f"{s['unrealized_pnl']:+.4f}")
        cols[3].metric("Total P&L", f"{s['total_pnl']:+.4f}")
        cols[4].metric("Fills", f"{s['fills']}")

        if s["halted"]:
            st.error(f"HALTED: {s['halt_reason']}", icon="🛑")
        st.caption(f"{'🟢 running' if sess.running else '⏹ stopped'} · "
                   f"{metrics.fills} fills · win rate {metrics.win_rate:.0%}")

        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.pnl_fig(metrics), width="stretch")
        c2.plotly_chart(charts.inventory_fig(metrics), width="stretch")

        # Recent fills (newest first).
        fills = [e for e in es["events"] if e.get("type") == "fill"][-10:]
        if fills:
            df = pd.DataFrame([
                {"side": f["side"], "price": f["price"], "size": f["size"],
                 "position": f["position"], "realized": f["realized_pnl"]}
                for f in reversed(fills)
            ])
            st.dataframe(df, hide_index=True, width="stretch")

    _panel()
