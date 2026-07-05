"""
Market data via the CLOB REST API (public, no auth).

This is the "pull" side of market data: ask the CLOB for the current state of a
token's book on demand. The "push" side — a live stream of updates — lives in
ws_client.py. Both feed the same LocalOrderBook so the rest of the code doesn't
care where a book came from.

All functions here take a `client` built by connection.build_public_client().
The SDK returns plain dicts (confirmed against the live API), e.g.:
    get_order_book(tid)   -> {'bids': [...], 'asks': [...], 'tick_size': '0.001', ...}
    get_midpoint(tid)     -> {'mid': '0.0085'}
    get_spread(tid)       -> {'spread': '0.001'}
We mostly compute midpoint/spread ourselves from the book so every number on
screen is internally consistent, but the SDK helpers are exposed too.
"""

from __future__ import annotations

from typing import Any

from src.orderbook import LocalOrderBook, TopOfBook


def fetch_order_book(client: Any, token_id: str) -> LocalOrderBook:
    """Fetch a full order-book snapshot and load it into a LocalOrderBook."""
    raw = client.get_order_book(token_id)
    book = LocalOrderBook(token_id)
    # The SDK may hand back a dict or an object; normalise to a dict.
    book.apply_snapshot(raw if isinstance(raw, dict) else _book_to_dict(raw))
    return book


def fetch_top_of_book(client: Any, token_id: str) -> TopOfBook:
    """Convenience: just the best bid/ask/mid/spread, computed from the book."""
    return fetch_order_book(client, token_id).top()


def get_midpoint(client: Any, token_id: str) -> float | None:
    """The CLOB's own midpoint (a cross-check against our computed one)."""
    resp = client.get_midpoint(token_id)
    val = resp.get("mid") if isinstance(resp, dict) else resp
    return float(val) if val not in (None, "") else None


def get_spread(client: Any, token_id: str) -> float | None:
    """The CLOB's own spread value."""
    resp = client.get_spread(token_id)
    val = resp.get("spread") if isinstance(resp, dict) else resp
    return float(val) if val not in (None, "") else None


def _book_to_dict(obj: Any) -> dict:
    """Fallback: coerce an OrderBookSummary-like object into our dict shape."""
    def levels(side):
        return [{"price": lvl.price, "size": lvl.size} for lvl in side]

    return {
        "bids": levels(getattr(obj, "bids", []) or []),
        "asks": levels(getattr(obj, "asks", []) or []),
        "tick_size": getattr(obj, "tick_size", None),
        "last_trade_price": getattr(obj, "last_trade_price", None),
        "timestamp": getattr(obj, "timestamp", None),
    }
