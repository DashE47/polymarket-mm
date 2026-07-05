"""
Market Explorer: keyword-search markets and pick one to work with.

Search results and the picked market are kept in st.session_state so the page
survives Streamlit's reruns (selecting an outcome doesn't trigger a re-search).
The chosen market+outcome → token_id is stored via app.state so every other page
(Order Book, Strategy Lab, Recorder) can use it without re-typing a token id.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import state
from src.gamma import search_markets

# session_state keys local to this page
_Q = "explorer_query"
_RESULTS = "explorer_results"


def render() -> None:
    st.title("🔎 Market Explorer")
    st.caption("Search Polymarket via the Gamma API, then pick a market and outcome.")

    # --- search form (a form so it only fires on submit, not every keystroke) --
    with st.form("market_search"):
        query = st.text_input(
            "Search", value=st.session_state.get(_Q, ""),
            placeholder="e.g. bitcoin, world cup, election",
        )
        c1, c2 = st.columns(2)
        limit = c1.number_input("Max results", min_value=1, max_value=50, value=20)
        tradeable_only = c2.checkbox("Tradeable only", value=True,
                                     help="Hide closed / non-order-book markets.")
        submitted = st.form_submit_button("Search", type="primary")

    if submitted and query.strip():
        with st.spinner("Searching Gamma…"):
            try:
                results = search_markets(query.strip(), limit=int(limit),
                                         tradeable_only=tradeable_only)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Search failed: {exc}")
                results = []
        st.session_state[_Q] = query.strip()
        st.session_state[_RESULTS] = results

    results = st.session_state.get(_RESULTS)
    if not results:
        st.info("Search for a market to begin.")
        return

    # --- results table -----------------------------------------------------
    st.subheader(f"{len(results)} result(s)")
    table = pd.DataFrame([
        {
            "question": m.question,
            "volume ($)": round(m.volume),
            "outcomes": ", ".join(m.tokens.keys()),
            "tradeable": m.tradeable,
            "condition_id": m.condition_id,
        }
        for m in results
    ])
    st.dataframe(table, hide_index=True, width="stretch")

    # --- pick a market + outcome ------------------------------------------
    st.subheader("Select a market")
    idx = st.selectbox(
        "Market", options=range(len(results)),
        format_func=lambda i: f"{i + 1}. {results[i].question}",
    )
    market = results[idx]
    outcome = st.radio("Outcome", options=list(market.tokens.keys()), horizontal=True)
    token_id = market.tokens[outcome]

    st.write("Token id for the chosen outcome:")
    st.code(token_id, language=None)
    if not market.tradeable:
        st.warning("This market isn't currently tradeable (closed or no live book).")

    if st.button("✅ Use this market", type="primary"):
        state.set_selection(market, outcome, token_id)
        st.success(f"Selected: {market.question}  [{outcome}] — now available on the other pages.")
