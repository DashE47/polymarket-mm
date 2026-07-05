"""
Shared backtest / sweep orchestration — called by BOTH the CLI scripts and the
Streamlit UI, so the two can never drift apart.

Each function wires the existing pieces together:
    StrategyConfig + SimEngine + (quiet) SimLogger + a replay source + compute_metrics
and hands back the metrics (and raw events) without printing anything. The
callers (scripts/*.py, app/views/*.py) own presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.analytics import RunMetrics, compute_metrics
from src.connection import build_public_client
from src.history import fetch_price_history
from src.replay import replay_price_series, replay_recording, sniff_token_id
from src.sim_engine import SimEngine
from src.sim_logger import SimLogger
from src.strategy import StrategyConfig


@dataclass
class BacktestResult:
    metrics: RunMetrics
    events: list[dict]
    token_id: str
    source: str


def _run(token_id: str, cfg: StrategyConfig, replay_fn, source: str) -> BacktestResult:
    """Run one backtest: replay_fn drives the engine, then we compute metrics."""
    # Quiet, no file — the caller decides whether to persist anything.
    logger = SimLogger(token_id, {"source": source, "cfg": vars(cfg)}, quiet=True, to_file=False)
    engine = SimEngine(token_id, cfg, logger)
    replay_fn(engine)
    return BacktestResult(compute_metrics(logger.events), logger.events, token_id, source)


def backtest_recording(path: str, cfg: StrategyConfig) -> BacktestResult:
    """Replay a recorded WS feed (faithful order-book fill model)."""
    token_id = sniff_token_id(path)
    source = f"recording:{path}"
    return _run(token_id, cfg, lambda e: replay_recording(path, token_id, e, status_every=0), source)


def backtest_history(token_id: str, interval: str, fidelity: int, cfg: StrategyConfig,
                     client=None) -> BacktestResult:
    """Replay fetched CLOB price history (coarser mid-crossing fill model)."""
    client = client or build_public_client()
    tick = float(client.get_tick_size(token_id))
    cfg.tick_size = tick
    series = fetch_price_history(client, token_id, interval, fidelity)
    if not series:
        raise ValueError("No price history returned for that token/interval.")
    source = f"history:{interval}@{fidelity}m"
    return _run(token_id, cfg, lambda e: replay_price_series(series, token_id, tick, e, status_every=0), source)


def run_sweep(
    *,
    spreads: list[float],
    sizes: list[float],
    skews: list[float],
    widen: float = 0.005,
    requote: float = 0.002,
    recording: str | None = None,
    token_id: str | None = None,
    interval: str = "1d",
    fidelity: int = 5,
) -> pd.DataFrame:
    """Run the strategy across a grid of (spread, size, skew) on ONE data source.

    Provide either `recording` (a recording path) or `token_id` (+ interval /
    fidelity for history). The data is loaded once and reused for every combo.
    Returns a DataFrame ranked by total P&L (best first).
    """
    # Resolve the data source once.
    if recording:
        tok = sniff_token_id(recording)
        tick = 0.001  # engine picks up the real tick from the recorded book events
        make_replay = lambda e: replay_recording(recording, tok, e, status_every=0)  # noqa: E731
    elif token_id:
        client = build_public_client()
        tok = token_id
        tick = float(client.get_tick_size(tok))
        series = fetch_price_history(client, tok, interval, fidelity)
        if not series:
            raise ValueError("No price history returned for that token/interval.")
        make_replay = lambda e: replay_price_series(series, tok, tick, e, status_every=0)  # noqa: E731
    else:
        raise ValueError("Provide either `recording` or `token_id`.")

    rows = []
    for spread in spreads:
        for size in sizes:
            for skew in skews:
                cfg = StrategyConfig(
                    spread=spread, size=size, inventory_skew=skew,
                    inventory_widen=widen, requote_threshold=requote, tick_size=tick,
                )
                result = _run(tok, cfg, make_replay, source="sweep")
                rows.append({"spread": spread, "size": size, "skew": skew,
                             **result.metrics.summary_row()})

    return pd.DataFrame(rows).sort_values("total_pnl", ascending=False).reset_index(drop=True)
