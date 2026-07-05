"""
Plotly figure builders for the UI (interactive, in-browser).

Kept separate from src/charts.py (which saves static matplotlib PNGs for reports)
so the web app can have zoom/hover/legend-toggle without touching the report
pipeline. Every function returns a go.Figure; pages render it with
st.plotly_chart(fig, width="stretch").
"""

from __future__ import annotations

import plotly.graph_objects as go

from src.analytics import RunMetrics

_LAYOUT = dict(margin=dict(l=10, r=10, t=30, b=10), height=320,
               legend=dict(orientation="h", yanchor="bottom", y=1.02))


def pnl_fig(m: RunMetrics) -> go.Figure:
    """Total / realized / unrealized P&L over (market) time."""
    fig = go.Figure()
    fig.add_scatter(x=m.t, y=m.total_series, name="total", line=dict(color="#111", width=2))
    fig.add_scatter(x=m.t, y=m.realized_series, name="realized", line=dict(color="#2ca02c"))
    fig.add_scatter(x=m.t, y=m.unrealized_series, name="unrealized", line=dict(color="#ff7f0e"))
    fig.add_hline(y=0, line_width=1, line_color="grey")
    fig.update_layout(title="P&L (pUSD)", xaxis_title="seconds", **_LAYOUT)
    return fig


def inventory_fig(m: RunMetrics) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=m.t, y=m.position_series, name="position", line=dict(color="#9467bd"))
    fig.add_hline(y=0, line_width=1, line_color="grey")
    fig.update_layout(title="Inventory (shares)", xaxis_title="seconds", **_LAYOUT)
    return fig


def price_fig(m: RunMetrics) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=m.t, y=m.mid, name="mid", line=dict(color="#1f77b4"))
    fig.update_layout(title="Mid price", xaxis_title="seconds", **_LAYOUT)
    return fig


def mid_history_fig(times: list[float], mids: list[float]) -> go.Figure:
    """Live mid-price line for the order-book page."""
    fig = go.Figure()
    fig.add_scatter(x=times, y=mids, name="mid", line=dict(color="#1f77b4"))
    fig.update_layout(title="Mid price (live)", xaxis_title="seconds", **_LAYOUT)
    return fig


def depth_fig(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> go.Figure:
    """Horizontal depth ladder: bid sizes (green) and ask sizes (red) by price."""
    fig = go.Figure()
    if bids:
        fig.add_bar(y=[f"{p:.4f}" for p, _ in bids], x=[s for _, s in bids],
                    orientation="h", name="bids", marker_color="#2ca02c")
    if asks:
        fig.add_bar(y=[f"{p:.4f}" for p, _ in asks], x=[s for _, s in asks],
                    orientation="h", name="asks", marker_color="#d62728")
    # Highest price at the top so it reads like a real ladder (asks above bids).
    fig.update_layout(title="Depth", xaxis_title="size",
                      yaxis=dict(categoryorder="category descending"), **_LAYOUT)
    return fig


def sweep_bar_fig(df) -> go.Figure:
    """Total P&L per (spread/size/skew) combination, best at the top."""
    labels = [f"s{r.spread}/z{r.size:g}/k{r.skew}" for r in df.itertuples()]
    totals = list(df["total_pnl"])
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in totals]
    fig = go.Figure(go.Bar(x=totals, y=labels, orientation="h", marker_color=colors))
    fig.add_vline(x=0, line_width=1, line_color="grey")
    # Best (top of the sorted df) at the top of the chart.
    fig.update_layout(title="Total P&L by setting", xaxis_title="total P&L (pUSD)",
                      yaxis=dict(autorange="reversed"),
                      margin=dict(l=10, r=10, t=30, b=10),
                      height=max(300, 26 * len(labels) + 80))
    return fig
