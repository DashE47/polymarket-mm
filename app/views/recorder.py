"""
Recorder page: capture a token's live order-book feed to data/recordings/ so it
can be replayed/backtested later. Recording runs in a background RecorderSession
(see app/live.py) so it survives Streamlit reruns; the event counter updates live
via an st.fragment.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import state
from app.live import RecorderSession
from config.settings import PROJECT_ROOT

_SESSION = "recorder_session"
_REC_DIR = PROJECT_ROOT / "data" / "recordings"


def _existing_recordings() -> None:
    st.subheader("Existing recordings")
    recs = sorted(_REC_DIR.glob("*.jsonl"), reverse=True)
    if not recs:
        st.write("_none yet_")
        return
    rows = [{"file": p.name, "size (KB)": round(p.stat().st_size / 1024, 1)} for p in recs]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render() -> None:
    st.title("⏺️ Recorder")
    st.caption("Capture a live feed for faithful (full order-book) backtests later.")

    sess: RecorderSession | None = st.session_state.get(_SESSION)

    default_tok = state.selected_token() or ""
    token = st.text_input("Token id", value=default_tok,
                          help="Pick a market in Market Explorer to autofill this.")
    duration = st.number_input("Duration (seconds)", min_value=10, max_value=3600,
                               value=300, step=10)

    busy = bool(sess and sess.running)
    c1, c2 = st.columns(2)
    start = c1.button("⏺️ Start recording", type="primary",
                      disabled=busy or not token.strip())
    stop = c2.button("⏹️ Stop", disabled=not busy)

    if start:
        s = RecorderSession(token.strip(), float(duration))
        s.start()
        st.session_state[_SESSION] = s
        st.rerun()
    if stop and sess:
        sess.stop()
        st.rerun()

    # Live status panel — refreshes itself once a second while we're on the page.
    if sess:
        @st.fragment(run_every="1s")
        def _status() -> None:
            st.metric("Events captured", sess.count)
            if sess.running:
                st.info(f"Recording… writing to {sess.path.name}")
            else:
                st.success(f"Saved {sess.count} events → {sess.path}")
        _status()

    st.divider()
    _existing_recordings()
