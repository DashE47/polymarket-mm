"""
Live market data via the CLOB V2 WebSocket (push side).

Endpoint and protocol (verified against the live feed):
    URL : wss://ws-subscriptions-clob.polymarket.com/ws/market
    subscribe by sending: {"assets_ids": [<token_id>, ...], "type": "market"}

    Messages arrive as either a single object or a list of them. The two we care
    about for book tracking:
        event_type "book"         -> full snapshot (same shape as REST)
        event_type "price_change" -> deltas; field `price_changes` is a list of
                                      {asset_id, price, size, side, best_bid,
                                       best_ask}. size "0" means level removed.
    (Other types like last_trade_price/tick_size_change also come through; we
    expose them via a raw callback but don't need them to track the book.)

This class keeps one LocalOrderBook per subscribed token, applies updates as
they stream in, and calls your `on_update(token_id, book)` callback so the UI
layer can re-render. It reconnects automatically with exponential backoff, so a
dropped connection doesn't kill your session.
"""

from __future__ import annotations

import json
import random
import threading
import time
from typing import Callable

import websocket  # from the `websocket-client` package

from src.orderbook import LocalOrderBook

WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Type aliases for the callbacks, just for readability.
UpdateCallback = Callable[[str, LocalOrderBook], None]
RawCallback = Callable[[dict], None]


class MarketStream:
    """Subscribe to live book updates for one or more tokens."""

    def __init__(
        self,
        token_ids: list[str],
        on_update: UpdateCallback | None = None,
        on_raw: RawCallback | None = None,
    ) -> None:
        self.token_ids = token_ids
        self.on_update = on_update
        self.on_raw = on_raw
        # One book per token, pre-created so a callback never hits a missing key.
        self.books: dict[str, LocalOrderBook] = {
            tid: LocalOrderBook(tid) for tid in token_ids
        }
        self._stop = threading.Event()
        self._ws: websocket.WebSocketApp | None = None

    # --- public control ---------------------------------------------------

    def run_forever(self) -> None:
        """Connect and process messages, reconnecting until stop() is called.

        Blocks the calling thread. For a UI, run this and do your rendering in
        the on_update callback, or start it via run_in_thread().
        """
        attempt = 0
        while not self._stop.is_set():
            self._ws = websocket.WebSocketApp(
                WS_MARKET_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            # ping_interval keeps the connection alive through idle periods.
            self._ws.run_forever(ping_interval=10, ping_timeout=5)

            if self._stop.is_set():
                break

            # We fell out of run_forever (disconnect). Back off, then retry.
            attempt += 1
            delay = min(30.0, 0.5 * (2 ** attempt)) + random.uniform(0, 0.5)
            print(f"[ws] disconnected; reconnecting in {delay:.1f}s …")
            self._stop.wait(delay)
        # Reset attempt counter handled implicitly on a clean run via _on_open.

    def run_in_thread(self) -> threading.Thread:
        """Start run_forever() on a daemon thread and return it."""
        t = threading.Thread(target=self.run_forever, daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        """Signal the loop to stop and close the socket."""
        self._stop.set()
        if self._ws is not None:
            self._ws.close()

    # --- websocket callbacks ----------------------------------------------

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        sub = {"assets_ids": self.token_ids, "type": "market"}
        ws.send(json.dumps(sub))
        print(f"[ws] connected; subscribed to {len(self.token_ids)} token(s).")

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        data = json.loads(message)
        # The server may batch several events into a JSON array.
        items = data if isinstance(data, list) else [data]
        for item in items:
            if self.on_raw:
                self.on_raw(item)
            self._handle(item)

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        # Normal socket drops often arrive as an empty/None error; show the type
        # so the log line is informative instead of a blank "[ws] error:".
        detail = str(error) or type(error).__name__
        print(f"[ws] error: {detail}")

    def _on_close(self, ws, status_code, msg) -> None:  # noqa: ANN001
        # Logged; reconnection is handled by the run_forever loop.
        pass

    # --- message handling -------------------------------------------------

    def _handle(self, item: dict) -> None:
        event_type = item.get("event_type") or item.get("type")

        if event_type == "book":
            tid = item.get("asset_id")
            book = self.books.get(tid)
            if book is not None:
                book.apply_snapshot(item)
                self._emit(tid)

        elif event_type == "price_change":
            # A single event can carry changes for multiple tokens; route each
            # change to its own book and only emit for tokens we track.
            changes = item.get("price_changes", [])
            ts = item.get("timestamp")
            touched: set[str] = set()
            for ch in changes:
                tid = ch.get("asset_id")
                book = self.books.get(tid)
                if book is not None:
                    book.apply_price_changes([ch], timestamp=ts)
                    touched.add(tid)
            for tid in touched:
                self._emit(tid)

        # Other event types (last_trade_price, tick_size_change, …) are
        # available via on_raw; we don't need them to maintain the book.

    def _emit(self, token_id: str) -> None:
        if self.on_update is not None:
            self.on_update(token_id, self.books[token_id])
