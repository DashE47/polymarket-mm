"""
Live Order Book page: stream the selected token's book and show best bid/ask/
mid/spread, a depth ladder, and a live mid-price line. Streaming is handled by a
LiveSession (app/live.py) on a background thread; this page just reads snapshots
and re-renders once a second via st.fragment.
"""

from __future__ import annotations

import streamlit as st

from app import charts, state
from app.live import LiveSession

_SESSION = "ob_session"


def _fmt(x, dp: int = 4) -> str:
    return "—" if x is None else f"{x:.{dp}f}"


def render() -> None:
    st.title("📖 Live Order Book")

    token = state.selected_token()
    if not token:
        st.info("Select a market in the Market Explorer first.")
        return
    st.caption(state.selected_label())

    sess: LiveSession | None = st.session_state.get(_SESSION)
    # If the selection changed, stop the old stream before starting a new one.
    if sess and sess.token_id != token:
        sess.stop()
        sess = None
        st.session_state[_SESSION] = None

    c1, c2 = st.columns(2)
    if c1.button("▶ Start streaming", type="primary", disabled=bool(sess and sess.running)):
        s = LiveSession(token, depth=12)
        s.start()
        st.session_state[_SESSION] = s
        st.rerun()
    if c2.button("⏹ Stop", disabled=not (sess and sess.running)):
        sess.stop()
        st.rerun()

    if not sess:
        st.info("Press Start to stream the live order book.")
        return

    # Live panel: re-renders itself every second without a full-page rerun.
    @st.fragment(run_every="1s")
    def _panel() -> None:
        snap = sess.snapshot()
        m = st.columns(4)
        m[0].metric("Best bid", _fmt(snap["best_bid"]))
        m[1].metric("Best ask", _fmt(snap["best_ask"]))
        m[2].metric("Mid", _fmt(snap["mid"]))
        m[3].metric("Spread", _fmt(snap["spread"]))

        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.depth_fig(snap["bids"], snap["asks"]), width="stretch")
        c2.plotly_chart(charts.mid_history_fig(snap["mid_times"], snap["mid_vals"]),
                        width="stretch")
        status = "🟢 live" if sess.running else "⏹ stopped"
        st.caption(f"{status} · {snap['updates']} updates · tick {_fmt(snap['tick'], 4)}")

    _panel()
