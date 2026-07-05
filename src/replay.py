"""
Replay historical data through the SimEngine.

The whole point of Phase 4: feed the EXACT SAME engine used live (Phase 3) with
historical book states instead of a live WebSocket, so a backtest is a faithful
re-run of the strategy. Two sources:

    replay_recording(...)     — a file recorded by record_market.py. Reconstructs
                                the real order book tick by tick (book snapshots +
                                price_change deltas). Highest fidelity.

    replay_price_series(...)  — a list of (timestamp, price) from history.py.
                                Synthesises a 1-level book per point (mid-crossing
                                fill model). Lower fidelity, but works without any
                                pre-recorded data.

Both walk the data in order and call engine.on_book(book) for each update, just
like the live runner does — only faster, and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.history import book_from_mid
from src.orderbook import LocalOrderBook
from src.sim_engine import SimEngine


def sniff_token_id(path: str | Path) -> str:
    """Read the first event carrying an asset_id to learn the recorded token."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line).get("event", {})
            if event.get("asset_id"):
                return event["asset_id"]
            for ch in event.get("price_changes", []):
                if ch.get("asset_id"):
                    return ch["asset_id"]
    raise ValueError(f"Could not find a token id inside {path}")


def replay_recording(path: str | Path, token_id: str, engine: SimEngine,
                     status_every: int = 500) -> int:
    """Replay a recorded WS feed. Returns the number of book updates processed.

    Reconstructs the book the same way the live client does: a `book` event
    resets the book; a `price_change` event applies deltas (for our token only).
    """
    book = LocalOrderBook(token_id)
    updates = 0

    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line).get("event", {})
            etype = event.get("event_type") or event.get("type")

            if etype == "book" and event.get("asset_id") == token_id:
                book.apply_snapshot(event)
            elif etype == "price_change":
                # A price_change can carry both tokens; keep only ours.
                ours = [c for c in event.get("price_changes", [])
                        if c.get("asset_id") == token_id]
                if not ours:
                    continue
                book.apply_price_changes(ours, timestamp=event.get("timestamp"))
            else:
                continue  # other event types don't affect the book

            engine.on_book(book)
            updates += 1
            if status_every and updates % status_every == 0:
                engine.log_status()
            if engine.halted:
                break

    engine.log_status()
    return updates


def replay_price_series(series: list[tuple[int, float]], token_id: str, tick: float,
                        engine: SimEngine, status_every: int = 50) -> int:
    """Replay a [(unix_seconds, price), ...] series via synthesised books."""
    updates = 0
    for ts, price in series:
        book = book_from_mid(token_id, price, tick, timestamp_ms=ts * 1000)
        engine.on_book(book)
        updates += 1
        if status_every and updates % status_every == 0:
            engine.log_status()
        if engine.halted:
            break

    engine.log_status()
    return updates
