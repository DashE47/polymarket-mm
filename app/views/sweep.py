"""
Parameter Sweep: run the strategy across a grid of spread / size / skew on one
data source, then rank and compare. Reuses src.runner.run_sweep so it matches the
CLI exactly. Shows a sortable table, a Plotly bar chart, and a CSV download.
"""

from __future__ import annotations

import streamlit as st

from app import charts, state
from src import runner
from src.history import VALID_INTERVALS
from config.settings import PROJECT_ROOT

_DF = "sweep_df"


def _floats(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _recordings() -> list:
    return sorted((PROJECT_ROOT / "data" / "recordings").glob("*.jsonl"))


def render() -> None:
    st.title("🧮 Parameter Sweep")
    st.caption("Compare many settings on identical data — the right way to tune. "
               "Same optimistic fill model caveats apply.")

    source = st.radio("Data source", ["History (fetch now)", "Recording"], horizontal=True)

    src_kwargs: dict = {}
    if source == "History (fetch now)":
        default_tok = state.selected_token() or ""
        token_id = st.text_input("Token id", value=default_tok)
        c1, c2 = st.columns(2)
        interval = c1.selectbox("Interval", sorted(VALID_INTERVALS),
                                index=sorted(VALID_INTERVALS).index("1d"))
        fidelity = c2.number_input("Fidelity (minutes)", 1, 60, 5)
        src_kwargs = {"token_id": token_id.strip(), "interval": interval, "fidelity": int(fidelity)}
    else:
        recs = _recordings()
        if not recs:
            st.info("No recordings yet — capture one on the Recorder page.")
            return
        path = st.selectbox("Recording", recs, format_func=lambda p: p.name)
        src_kwargs = {"recording": str(path)}

    st.markdown("**Sweep grid** (comma-separated)")
    c1, c2, c3 = st.columns(3)
    spreads = c1.text_input("spreads", "0.01,0.02,0.04")
    sizes = c2.text_input("sizes", "50")
    skews = c3.text_input("skews", "0,0.005,0.01")
    c4, c5 = st.columns(2)
    widen = c4.number_input("widen", 0.0, 0.2, 0.005, step=0.001, format="%.3f")
    requote = c5.number_input("requote", 0.0, 0.1, 0.002, step=0.001, format="%.3f")

    if st.button("Run sweep", type="primary"):
        if "token_id" in src_kwargs and not src_kwargs["token_id"]:
            st.warning("Enter a token id (or select a market in Market Explorer).")
        else:
            try:
                grids = dict(spreads=_floats(spreads), sizes=_floats(sizes), skews=_floats(skews))
                n = len(grids["spreads"]) * len(grids["sizes"]) * len(grids["skews"])
            except ValueError:
                st.error("Grids must be comma-separated numbers, e.g. 0.01,0.02,0.04")
                grids = None
            if grids:
                with st.spinner(f"Running {n} combinations…"):
                    try:
                        df = runner.run_sweep(widen=widen, requote=requote, **grids, **src_kwargs)
                        st.session_state[_DF] = df
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Sweep failed: {exc}")

    df = st.session_state.get(_DF)
    if df is not None and not df.empty:
        st.divider()
        st.subheader("Results (ranked by total P&L)")
        st.dataframe(df, hide_index=True, width="stretch")
        st.plotly_chart(charts.sweep_bar_fig(df), width="stretch")
        best = df.iloc[0]
        st.success(f"Best: spread {best.spread} / size {best.size:g} / skew {best.skew} "
                   f"→ total P&L {best.total_pnl:+.3f}")
        st.download_button("⬇️ Download CSV", df.to_csv(index=False).encode(),
                           file_name="sweep.csv", mime="text/csv")
