"""
Historical price data from the CLOB, for backtesting without a pre-recorded feed.

`get_prices_history` returns a token's price over time as a list of
{'t': unix_seconds, 'p': price} points. That's a MIDPOINT-style series, not a
full order book — so a backtest built on it can only know "the price was X at
time T", not the depth on each side.

To run our existing engine (which thinks in terms of an order book) on this, we
synthesise a minimal book from each price point with the best bid and best ask
both sitting at the price. Consequences:

    * midpoint  == the historical price (correct).
    * spread    == 0 (we have no real spread information here).
    * fill model degrades to a "mid-crossing" rule: our resting bid fills when
      the price falls to it, our ask fills when the price rises to it.

This is a coarser simulation than replaying a recorded book, but it lets you
backtest over real historical movement immediately. For higher fidelity, record
a live feed (record_market.py) and replay that instead.
"""

from __future__ import annotations

from typing import Any

from py_clob_client_v2 import PricesHistoryParams

from src.orderbook import LocalOrderBook

# Allowed interval strings (mirror PriceHistoryInterval): "1h","6h","1d","1w","max".
VALID_INTERVALS = {"1h", "6h", "1d", "1w", "max"}


def fetch_price_history(
    client: Any, token_id: str, interval: str = "1d", fidelity: int = 5
) -> list[tuple[int, float]]:
    """Return [(unix_seconds, price), ...] for a token.

    `interval` is how far back to look; `fidelity` is the resolution in minutes
    (smaller = more, finer points).
    """
    params = PricesHistoryParams(market=token_id, interval=interval, fidelity=fidelity)
    resp = client.get_prices_history(params)
    points = resp.get("history", resp) if isinstance(resp, dict) else resp
    return [(int(pt["t"]), float(pt["p"])) for pt in points]


def book_from_mid(token_id: str, mid: float, tick: float, timestamp_ms: int | None = None) -> LocalOrderBook:
    """Build a 1-level synthetic book with best_bid == best_ask == mid.

    See the module docstring for what this implies about spread and fills.
    """
    book = LocalOrderBook(token_id)
    book.apply_snapshot({
        "bids": [{"price": mid, "size": 1e9}],   # effectively unlimited size
        "asks": [{"price": mid, "size": 1e9}],
        "tick_size": tick,
        "timestamp": timestamp_ms,
    })
    return book
