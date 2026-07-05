"""
Background session objects for the live pages.

Streamlit reruns the whole script on every interaction, so any long-lived work
(a WebSocket subscription, a recording, a running simulation) must live in a
plain object stored in st.session_state and driven by background threads. These
classes are that object. Their callbacks run on the WebSocket thread and only
touch plain Python state (never the Streamlit API), so they're safe to read from
the UI thread between reruns.

This module currently holds RecorderSession. LiveSession (order book + live sim)
is added alongside it for the streaming pages.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from src.orderbook import LocalOrderBook
from src.recorder import Recorder
from src.ws_client import MarketStream


class RecorderSession:
    """Record a token's live feed to disk for `duration` seconds, in the background."""

    def __init__(self, token_id: str, duration: float) -> None:
        self.token_id = token_id
        self.duration = duration
        # Open the recording file now so self.path is available immediately.
        self._rec = Recorder(token_id)
        self._rec.__enter__()
        self.path = self._rec.path
        self.count = 0
        self.done = False
        self._stop = threading.Event()
        self._stream = MarketStream([token_id], on_raw=self._on_raw)

    def _on_raw(self, event: dict) -> None:
        # Runs on the WS thread: write the event and update the counter.
        self._rec.write(event)
        self.count = self._rec.count

    def start(self) -> None:
        self._stream.run_in_thread()
        threading.Thread(target=self._auto_stop, daemon=True).start()

    def _auto_stop(self) -> None:
        # Wait out the duration (or an early stop), then shut down cleanly.
        self._stop.wait(self.duration)
        self.stop()

    def stop(self) -> None:
        if self.done:
            return
        self._stop.set()
        self._stream.stop()
        self._rec.__exit__(None, None, None)  # close the file
        self.done = True

    @property
    def running(self) -> bool:
        return not self.done


class LiveSession:
    """Stream a token's live book; optionally run the SimEngine on each update.

    Used by both the Live Order Book page (with_engine=False) and the Strategy
    Lab's streaming sim (with_engine=True). The WS callback runs on a background
    thread and copies a plain snapshot under a lock, so the UI can read a
    consistent view between reruns.
    """

    def __init__(self, token_id: str, depth: int = 12, *, cfg=None, to_file: bool = False) -> None:
        self.token_id = token_id
        self.depth = depth
        self._lock = threading.Lock()
        self._stream = MarketStream([token_id], on_update=self._on_update)
        self._start_mono = time.monotonic()
        self._stopped = False
        self.updates = 0

        # Book snapshot (read under lock via snapshot()).
        self.best_bid = self.best_ask = self.mid = self.spread = self.tick = None
        self.bids: list[tuple[float, float]] = []
        self.asks: list[tuple[float, float]] = []
        self.mid_times: deque[float] = deque(maxlen=900)
        self.mid_vals: deque[float] = deque(maxlen=900)

        # Optional simulation engine.
        self.engine = None
        self.logger = None
        self._eng_summary: dict | None = None
        self._eng_events: list[dict] = []
        if cfg is not None:
            from src.sim_engine import SimEngine
            from src.sim_logger import SimLogger
            # to_file=True lets the run also be analysed later from logs/.
            self.logger = SimLogger(token_id, {"cfg": vars(cfg), "via": "ui-live"},
                                    quiet=True, to_file=to_file)
            self.engine = SimEngine(token_id, cfg, self.logger)

    def _on_update(self, _tid: str, book: LocalOrderBook) -> None:
        # WS thread. Run the engine first (if any), then snapshot everything.
        if self.engine is not None:
            self.engine.on_book(book)
        with self._lock:
            self.best_bid, self.best_ask = book.best_bid, book.best_ask
            self.mid, self.spread, self.tick = book.midpoint, book.spread, book.tick_size
            self.bids = book.bid_levels(self.depth)
            self.asks = book.ask_levels(self.depth)
            self.updates += 1
            if self.mid is not None:
                self.mid_times.append(round(time.monotonic() - self._start_mono, 2))
                self.mid_vals.append(self.mid)
            if self.engine is not None:
                self._eng_summary = self.engine.summary()
                self._eng_events = list(self.logger.events)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(
                best_bid=self.best_bid, best_ask=self.best_ask, mid=self.mid,
                spread=self.spread, tick=self.tick, bids=list(self.bids),
                asks=list(self.asks), mid_times=list(self.mid_times),
                mid_vals=list(self.mid_vals), updates=self.updates,
            )

    def engine_snapshot(self) -> dict | None:
        if self.engine is None:
            return None
        with self._lock:
            return {"summary": self._eng_summary, "events": list(self._eng_events)}

    def start(self, duration: float | None = None) -> None:
        """Start streaming. If `duration` is given, auto-stop after that many
        seconds (used by the Strategy Lab's fixed-duration mode); otherwise it
        runs until stop() is called (continuous mode)."""
        self._stream.run_in_thread()
        if duration:
            self._auto_stop_event = threading.Event()
            threading.Thread(target=self._auto_stop, args=(duration,), daemon=True).start()

    def _auto_stop(self, duration: float) -> None:
        self._auto_stop_event.wait(duration)
        self.stop()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stream.stop()
        if self.logger is not None:
            self.logger.close()
        self._stopped = True

    @property
    def running(self) -> bool:
        return not self._stopped
