r"""
Streamlit entry point for the Polymarket market-making UI.

Launch from the project root with:
    .\.venv\Scripts\python.exe -m streamlit run app/main.py

Design notes:
- Streamlit puts the SCRIPT's directory (app/) on sys.path, not the project
  root, so we insert the project root first — then `from src...`, `from config...`
  and `from app...` all resolve.
- We use the modern st.navigation / st.Page API: each page is just a `render()`
  function from a module in app/views/. Shared state (selected market, live
  sessions) lives in st.session_state via app/state.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Project root = parent of this file's parent (…/polymarket-mm).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app import state  # noqa: E402
from app.views import (  # noqa: E402
    analytics,
    explorer,
    home,
    order_book,
    recorder,
    strategy_lab,
    sweep,
    trading_disabled,
)

st.set_page_config(page_title="Polymarket MM", page_icon="📈", layout="wide")

# Initialise session_state defaults and draw the global sidebar.
state.init()
state.render_sidebar()

# Grouped navigation. Each st.Page wraps a view module's render() function.
# NOTE: every page function is named `render`, so Streamlit would infer the SAME
# url pathname for all of them and raise a "URL pathnames must be unique" error.
# We give each Page an explicit, unique `url_path` to avoid that.
navigation = st.navigation(
    {
        "Markets": [
            st.Page(home.render, title="Home & Safety", icon="🏠", url_path="home", default=True),
            st.Page(explorer.render, title="Market Explorer", icon="🔎", url_path="explorer"),
            st.Page(order_book.render, title="Live Order Book", icon="📖", url_path="order-book"),
        ],
        "Strategy": [
            st.Page(strategy_lab.render, title="Strategy Lab", icon="🧪", url_path="strategy-lab"),
            st.Page(analytics.render, title="Backtest & Analytics", icon="📊", url_path="analytics"),
            st.Page(sweep.render, title="Parameter Sweep", icon="🧮", url_path="sweep"),
        ],
        "Data": [
            st.Page(recorder.render, title="Recorder", icon="⏺️", url_path="recorder"),
        ],
        "Trading": [
            st.Page(trading_disabled.render, title="Live Trading", icon="💸", url_path="trading"),
        ],
    }
)
navigation.run()
