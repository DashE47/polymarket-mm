"""
Save analytics charts to reports/ as PNG files.

We use matplotlib's non-interactive "Agg" backend so charts render to files
without needing a display — important on a headless run or inside a sweep.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # must be set before importing pyplot
import matplotlib.pyplot as plt  # noqa: E402

from config.settings import PROJECT_ROOT  # noqa: E402
from src.analytics import RunMetrics  # noqa: E402

REPORTS_DIR = PROJECT_ROOT / "reports"


def _ensure_dir() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_run_charts(metrics: RunMetrics, name: str, title: str = "") -> Path:
    """Three stacked panels: P&L curve, inventory, and mid price over time."""
    _ensure_dir()
    fig, (ax_pnl, ax_inv, ax_mid) = plt.subplots(
        3, 1, figsize=(10, 9), sharex=True, gridspec_kw={"height_ratios": [2, 1, 1]}
    )
    t = metrics.t

    ax_pnl.plot(t, metrics.total_series, label="total", color="black")
    ax_pnl.plot(t, metrics.realized_series, label="realized", color="green", alpha=0.7)
    ax_pnl.plot(t, metrics.unrealized_series, label="unrealized", color="orange", alpha=0.7)
    ax_pnl.axhline(0, color="grey", lw=0.5)
    ax_pnl.set_ylabel("P&L (pUSD)")
    ax_pnl.legend(loc="upper left")
    ax_pnl.set_title(title or "Run analysis")

    ax_inv.plot(t, metrics.position_series, color="purple")
    ax_inv.axhline(0, color="grey", lw=0.5)
    ax_inv.set_ylabel("inventory (shares)")

    ax_mid.plot(t, metrics.mid, color="steelblue")
    ax_mid.set_ylabel("mid price")
    ax_mid.set_xlabel("seconds from start")

    fig.tight_layout()
    out = REPORTS_DIR / f"{name}.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def save_sweep_chart(labels: list[str], totals: list[float], name: str) -> Path:
    """Horizontal bar chart of total P&L per parameter combination."""
    _ensure_dir()
    fig, ax = plt.subplots(figsize=(10, max(3, 0.4 * len(labels) + 1)))
    colors = ["green" if v >= 0 else "firebrick" for v in totals]
    ax.barh(labels, totals, color=colors)
    ax.axvline(0, color="grey", lw=0.5)
    ax.set_xlabel("total P&L (pUSD)")
    ax.set_title("Parameter sweep — total P&L by setting")
    fig.tight_layout()
    out = REPORTS_DIR / f"{name}.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out
