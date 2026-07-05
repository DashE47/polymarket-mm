"""
A local, in-memory order book and the math that turns it into the numbers a
market maker actually cares about: best bid, best ask, midpoint, and spread.

Why a *local* book?
    The CLOB gives us the book two ways: a full snapshot (REST `get_order_book`
    or the WS `book` message) and a stream of incremental `price_change` deltas.
    To follow a market live and cheaply, we seed a local copy from a snapshot,
    then apply each delta as it arrives. That's exactly how a real trading system
    tracks the book — re-downloading the whole thing on every tick would be slow
    and rate-limit-hostile.

A few domain notes for someone new to order books:
    * Each side is a set of price levels. A "level" is a price and the total
      size resting there. On Polymarket prices are probabilities in (0, 1) and
      sizes are share counts.
    * The BEST BID is the highest price a buyer will pay. The BEST ASK is the
      lowest price a seller will accept. They're the two prices that face each
      other across the spread.
    * MIDPOINT = (best_bid + best_ask) / 2 — a fair-value proxy.
    * SPREAD  = best_ask - best_bid — how far apart buyers and sellers are; also
      roughly the edge a market maker tries to capture.

We store sizes keyed by a *normalised* price (rounded to 6 dp) so that float
quirks like 0.006000000001 don't create duplicate levels. Polymarket tick sizes
are >= 0.0001, so 6 dp is plenty of headroom.
"""

from __future__ import annotations

from dataclasses import dataclass


def _p(price: str | float) -> float:
    """Normalise a price to a stable float key (6 decimal places)."""
    return round(float(price), 6)


def _num(v) -> float | None:
    """float(v), but tolerant of None / "" / junk (returns None instead of raising)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class TopOfBook:
    """A snapshot of just the prices a quoter reasons about."""

    best_bid: float | None
    best_ask: float | None
    midpoint: float | None
    spread: float | None


class LocalOrderBook:
    """An order book for ONE token, updatable from snapshots and deltas."""

    def __init__(self, token_id: str) -> None:
        self.token_id = token_id
        # price (float) -> size (float). One dict per side.
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}
        self.tick_size: float | None = None
        self.last_trade_price: float | None = None
        self.timestamp: int | None = None

    # --- updating ---------------------------------------------------------

    def apply_snapshot(self, book: dict) -> None:
        """Replace the whole book from a `book` message / REST response.

        Accepts the dict shape returned by both `get_order_book` and the WS
        `book` event: {'bids': [{price,size}], 'asks': [...], 'tick_size': ...}.
        """
        self._bids = {_p(lvl["price"]): float(lvl["size"]) for lvl in book.get("bids", [])}
        self._asks = {_p(lvl["price"]): float(lvl["size"]) for lvl in book.get("asks", [])}
        # These fields can be missing OR an empty string "" on a brand-new market
        # that has no trades/tick yet — float("") would crash, so parse safely.
        tick = _num(book.get("tick_size"))
        if tick is not None:
            self.tick_size = tick
        ltp = _num(book.get("last_trade_price"))
        if ltp is not None:
            self.last_trade_price = ltp
        ts = _num(book.get("timestamp"))
        if ts is not None:
            self.timestamp = int(ts)

    def apply_price_changes(self, changes: list[dict], timestamp: int | None = None) -> None:
        """Apply incremental updates from a WS `price_change` event.

        Each change is {'price','size','side', ...}. A size of 0 means that
        price level was fully consumed/cancelled and should be removed. Note a
        `price_change` event can carry updates for BOTH tokens of a market, so
        the caller should pass only the changes whose asset_id matches us (the
        WS client does this filtering).
        """
        for ch in changes:
            price = _p(ch["price"])
            size = float(ch["size"])
            # 'BUY' updates the bid side; 'SELL' updates the ask side.
            side = ch.get("side", "").upper()
            book_side = self._bids if side == "BUY" else self._asks
            if size == 0:
                book_side.pop(price, None)  # level removed
            else:
                book_side[price] = size      # level set/replaced
        if timestamp is not None:
            self.timestamp = int(timestamp)

    # --- reading ----------------------------------------------------------

    @property
    def best_bid(self) -> float | None:
        return max(self._bids) if self._bids else None

    @property
    def best_ask(self) -> float | None:
        return min(self._asks) if self._asks else None

    @property
    def midpoint(self) -> float | None:
        b, a = self.best_bid, self.best_ask
        return (b + a) / 2 if (b is not None and a is not None) else None

    @property
    def spread(self) -> float | None:
        b, a = self.best_bid, self.best_ask
        return (a - b) if (b is not None and a is not None) else None

    def top(self) -> TopOfBook:
        return TopOfBook(self.best_bid, self.best_ask, self.midpoint, self.spread)

    def bid_levels(self, depth: int = 10) -> list[tuple[float, float]]:
        """Top `depth` bid levels as (price, size), best (highest) first."""
        return sorted(self._bids.items(), key=lambda kv: kv[0], reverse=True)[:depth]

    def ask_levels(self, depth: int = 10) -> list[tuple[float, float]]:
        """Top `depth` ask levels as (price, size), best (lowest) first."""
        return sorted(self._asks.items(), key=lambda kv: kv[0])[:depth]
