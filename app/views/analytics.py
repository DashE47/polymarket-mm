"""
Backtest & Analytics: run the strategy on history or a recording (or load a
saved run log), then show the performance scorecard and interactive charts.

All the heavy lifting is reused: src.runner for backtests, src.analytics for the
scorecard, app.charts for the Plotly figures. Results are stashed in
st.session_state so they persist while you fiddle with other widgets.
"""

from __future__ import annotations

import streamlit as st

from app import charts, state
from config.settings import PROJECT_ROOT
from src import runner
from src.analytics import compute_metrics, load_events
from src.history import VALID_INTERVALS
from src.strategy import StrategyConfig

_RESULT = "analytics_result"  # (label, RunMetrics) kept across reruns


def _strategy_inputs() -> StrategyConfig:
    st.markdown("**Strategy parameters**")
    c1, c2, c3 = st.columns(3)
    spread = c1.number_input("spread", 0.001, 0.5, 0.02, step=0.002, format="%.3f")
    size = c1.number_input("size (shares)", 1.0, 10000.0, 100.0, step=10.0)
    skew = c2.number_input("inventory skew", 0.0, 0.2, 0.005, step=0.001, format="%.3f")
    widen = c2.number_input("inventory widen", 0.0, 0.2, 0.005, step=0.001, format="%.3f")
    requote = c3.number_input("requote threshold", 0.0, 0.1, 0.002, step=0.001, format="%.3f")
    return StrategyConfig(spread=spread, size=size, inventory_skew=skew,
                          inventory_widen=widen, requote_threshold=requote)


def _recordings() -> list:
    return sorted((PROJECT_ROOT / "data" / "recordings").glob("*.jsonl"))


def _logs() -> list:
    return sorted((PROJECT_ROOT / "logs").glob("mm_*.jsonl"))


def _scorecard(m) -> None:
    c = st.columns(3)
    c[0].metric("Total P&L", f"{m.total_pnl:+.4f}")
    c[1].metric("Realized", f"{m.realized_pnl:+.4f}")
    c[2].metric("Unrealized", f"{m.unrealized_pnl:+.4f}")
    c = st.columns(3)
    c[0].metric("Fills", f"{m.fills}  ({m.buys}/{m.sells})")
    c[1].metric("Win rate", f"{m.win_rate:.0%}")
    c[2].metric("Fills / min", f"{m.fills_per_min:.2f}")
    c = st.columns(3)
    c[0].metric("Max |inventory|", f"{m.max_abs_inventory:.0f}")
    c[1].metric("Max drawdown", f"{m.max_drawdown:.4f}")
    c[2].metric("Sharpe (per-step)", f"{m.sharpe:.3f}")
    if m.halted:
        st.error(f"Run halted: {m.halt_reason}", icon="🛑")


def render() -> None:
    st.title("📊 Backtest & Analytics")
    st.caption("Fill model is the optimistic touch-cross model — simulated P&L "
               "overstates reality, and a frozen-touch market shows 0 fills.")

    source = st.radio("Data source", ["History (fetch now)", "Recording", "Saved run log"],
                      horizontal=True)

    if source == "History (fetch now)":
        default_tok = state.selected_token() or ""
        token_id = st.text_input("Token id", value=default_tok,
                                 help="Pick a market in Market Explorer to autofill this.")
        c1, c2 = st.columns(2)
        interval = c1.selectbox("Interval", sorted(VALID_INTERVALS), index=sorted(VALID_INTERVALS).index("1d"))
        fidelity = c2.number_input("Fidelity (minutes)", 1, 60, 5)
        cfg = _strategy_inputs()
        if st.button("Run backtest", type="primary"):
            if not token_id.strip():
                st.warning("Enter a token id (or select a market in Market Explorer).")
            else:
                with st.spinner("Fetching history and replaying…"):
                    try:
                        res = runner.backtest_history(token_id.strip(), interval, int(fidelity), cfg)
                        st.session_state[_RESULT] = (f"history {interval}@{fidelity}m", res.metrics)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Backtest failed: {exc}")

    elif source == "Recording":
        recs = _recordings()
        if not recs:
            st.info("No recordings yet — capture one on the Recorder page.")
        else:
            path = st.selectbox("Recording", recs, format_func=lambda p: p.name)
            cfg = _strategy_inputs()
            if st.button("Run backtest", type="primary"):
                with st.spinner("Replaying recording…"):
                    try:
                        res = runner.backtest_recording(str(path), cfg)
                        st.session_state[_RESULT] = (path.name, res.metrics)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Backtest failed: {exc}")

    else:  # Saved run log
        logs = _logs()
        if not logs:
            st.info("No run logs yet — run a sim/backtest first.")
        else:
            path = st.selectbox("Run log", logs, format_func=lambda p: p.name)
            if st.button("Analyse log", type="primary"):
                try:
                    st.session_state[_RESULT] = (path.name, compute_metrics(load_events(path)))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not analyse log: {exc}")

    # --- render the latest result ----------------------------------------
    result = st.session_state.get(_RESULT)
    if result:
        label, metrics = result
        st.divider()
        st.subheader(f"Results — {label}")
        _scorecard(metrics)
        st.plotly_chart(charts.pnl_fig(metrics), width="stretch")
        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.inventory_fig(metrics), width="stretch")
        c2.plotly_chart(charts.price_fig(metrics), width="stretch")
