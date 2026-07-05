"""
Turn a run's event log into performance metrics and time series.

Input is the list of event dicts a SimLogger produces (either from its in-memory
`.events`, or read back from a logs/mm_*.jsonl file). We reconstruct the
strategy's state over time and compute the standard market-making scorecard:

    PnL over time   — realized, unrealized, and total, sampled at every event.
    fill rate       — fills per minute (how busy the strategy was).
    spread captured — average realized P&L per closing trade (the edge we kept).
    inventory       — position over time, and the largest |position| reached.
    max drawdown    — worst peak-to-trough drop in total P&L.
    Sharpe          — mean / std of per-step P&L changes (NOT annualised; it's a
                      relative quality score for comparing settings).
    win rate        — fraction of closing trades that were profitable.

Why reconstruct from events rather than trust one running number? Because the
log is the source of truth a backtest and a live run share, so the same analysis
works on both, and on data you recorded weeks ago.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


def load_events(path: str | Path) -> list[dict]:
    """Read a logs/mm_*.jsonl file back into a list of event dicts."""
    events = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


@dataclass
class RunMetrics:
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fills: int = 0
    buys: int = 0
    sells: int = 0
    closing_trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    avg_spread_captured: float = 0.0  # mean realized P&L per closing trade
    max_abs_inventory: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    duration_min: float = 0.0
    fills_per_min: float = 0.0
    final_position: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    # time series for charting (parallel lists)
    t: list[float] = field(default_factory=list)          # seconds from start
    mid: list[float] = field(default_factory=list)
    total_series: list[float] = field(default_factory=list)
    realized_series: list[float] = field(default_factory=list)
    unrealized_series: list[float] = field(default_factory=list)
    position_series: list[float] = field(default_factory=list)

    def summary_row(self) -> dict:
        """Just the scalar metrics (for a sweep comparison table)."""
        return {
            "total_pnl": round(self.total_pnl, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "fills": self.fills,
            "win_rate": round(self.win_rate, 3),
            "avg_spread_captured": round(self.avg_spread_captured, 5),
            "max_abs_inventory": round(self.max_abs_inventory, 1),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe": round(self.sharpe, 3),
            "fills_per_min": round(self.fills_per_min, 2),
            "final_position": round(self.final_position, 1),
            "halted": self.halted,
        }


def compute_metrics(events: list[dict]) -> RunMetrics:
    m = RunMetrics()

    # Running state, updated from fill events (which carry the resulting state).
    position = 0.0
    avg_price = 0.0
    realized = 0.0
    prev_realized = 0.0
    t0 = None         # first timestamp (seconds), in MARKET time if available
    t_last = None

    # Choose ONE clock for the whole run. If any event carries a market
    # timestamp we use market time throughout (and ignore events that lack it,
    # like run_start); otherwise we use wall-clock mono. Mixing the two would
    # subtract a ~0 wall-clock start from a Unix-epoch end and give nonsense.
    use_market_time = any(ev.get("mkt_ts") is not None for ev in events)

    def _tsec(ev: dict) -> float | None:
        if use_market_time:
            mkt = ev.get("mkt_ts")
            return mkt / 1000.0 if mkt is not None else None
        mono = ev.get("mono")
        return mono if mono is not None else None

    for ev in events:
        etype = ev.get("type")
        tsec = _tsec(ev)
        if tsec is not None:
            if t0 is None:
                t0 = tsec
            t_last = tsec

        if etype == "fill":
            m.fills += 1
            if ev.get("side") == "BUY":
                m.buys += 1
            else:
                m.sells += 1
            position = ev.get("position", position)
            avg_price = ev.get("avg_price", avg_price)
            realized = ev.get("realized_pnl", realized)
            # A change in realized P&L means this fill CLOSED part of a position.
            delta = realized - prev_realized
            if abs(delta) > 1e-12:
                m.closing_trades += 1
                if delta > 0:
                    m.wins += 1
            prev_realized = realized

        # Sample the equity curve at any event that knows the current mid.
        mid = ev.get("mid")
        if mid is not None:
            unreal = (mid - avg_price) * position
            total = realized + unreal
            t = (tsec - t0) if (tsec is not None and t0 is not None) else 0.0
            m.t.append(round(t, 3))
            m.mid.append(mid)
            m.realized_series.append(realized)
            m.unrealized_series.append(unreal)
            m.total_series.append(total)
            m.position_series.append(position)
            m.max_abs_inventory = max(m.max_abs_inventory, abs(position))

        if etype == "halt":
            m.halted = True
            m.halt_reason = ev.get("reason", "")

    # Finalise scalar metrics.
    m.realized_pnl = realized
    m.final_position = position
    if m.total_series:
        m.total_pnl = m.total_series[-1]
        m.unrealized_pnl = m.unrealized_series[-1]
        m.max_drawdown = _max_drawdown(m.total_series)
        m.sharpe = _sharpe(m.total_series)
    if m.closing_trades:
        m.win_rate = m.wins / m.closing_trades
        m.avg_spread_captured = m.realized_pnl / m.closing_trades
    if t0 is not None and t_last is not None:
        m.duration_min = (t_last - t0) / 60.0
        if m.duration_min > 0:
            m.fills_per_min = m.fills / m.duration_min
    return m


def _max_drawdown(series: list[float]) -> float:
    """Largest peak-to-trough drop in the total-P&L curve (a positive number)."""
    peak = series[0]
    worst = 0.0
    for v in series:
        peak = max(peak, v)
        worst = max(worst, peak - v)
    return worst


def _sharpe(series: list[float]) -> float:
    """Mean/std of per-step P&L changes. Not annualised — a relative score."""
    if len(series) < 3:
        return 0.0
    deltas = [series[i] - series[i - 1] for i in range(1, len(series))]
    mean = sum(deltas) / len(deltas)
    var = sum((d - mean) ** 2 for d in deltas) / (len(deltas) - 1)
    std = math.sqrt(var)
    return (mean / std) if std > 1e-12 else 0.0
