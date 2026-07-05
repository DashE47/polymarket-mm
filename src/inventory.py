"""
Inventory and P&L accounting for the market maker.

A market maker is constantly buying and selling, so we need to answer two
questions at any moment:
    1. What's my position?  (how many shares of the token do I hold, net)
    2. How am I doing?       (profit/loss)

We split P&L the standard way:
    * REALIZED   — locked in when we CLOSE part of a position (sell shares we
                   bought, or buy back shares we shorted). It's the difference
                   between the price we exit at and our average entry price.
    * UNREALIZED — paper P&L on the position we still hold, marked at the current
                   market price (here, the order-book midpoint). It moves up and
                   down with the market until we close.
    total = realized + unrealized.

We track position with an AVERAGE-COST basis, which is the simplest correct
scheme: every share in the current position is treated as if bought at the
running average price. When we reduce the position we realize P&L against that
average; when we add, we blend the new fill into the average.

Sign convention: position > 0 means LONG (we own shares), position < 0 means
SHORT (we owe shares). A BUY adds +size, a SELL adds -size.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Inventory:
    position: float = 0.0      # signed share count (+long / -short)
    avg_price: float = 0.0     # average entry price of the CURRENT position
    realized_pnl: float = 0.0  # P&L locked in by closing trades
    buys: int = 0              # fill counters, for stats
    sells: int = 0

    def on_fill(self, side: str, price: float, size: float) -> None:
        """Apply one fill. `side` is 'BUY' or 'SELL'; size is always positive."""
        signed = size if side.upper() == "BUY" else -size
        if side.upper() == "BUY":
            self.buys += 1
        else:
            self.sells += 1

        new_position = self.position + signed

        # Case A: opening from flat, or adding in the SAME direction we already
        # hold. Blend the fill into the average entry price.
        same_direction = self.position == 0 or (self.position > 0) == (signed > 0)
        if same_direction:
            prev_notional = self.avg_price * abs(self.position)
            add_notional = price * abs(signed)
            self.avg_price = (
                (prev_notional + add_notional) / abs(new_position)
                if new_position != 0
                else 0.0
            )
            self.position = new_position
            return

        # Case B: this fill reduces (and maybe flips) the position. The portion
        # that closes against the existing position realizes P&L.
        closing = min(abs(signed), abs(self.position))
        direction = 1 if self.position > 0 else -1  # were we long or short?
        # Selling above avg (when long) is profit; buying below avg (when short)
        # is profit. Both are captured by (price - avg) * closed * direction.
        self.realized_pnl += (price - self.avg_price) * closing * direction

        if abs(signed) > abs(self.position):
            # We closed everything AND flipped to the other side. The leftover
            # opens a fresh position at this fill's price.
            self.avg_price = price
        elif new_position == 0:
            self.avg_price = 0.0
        # else: still on the same side, smaller; avg_price is unchanged.

        self.position = new_position

    # --- valuation --------------------------------------------------------

    def unrealized_pnl(self, mark_price: float) -> float:
        """Paper P&L on the open position, marked at `mark_price`.

        Works for both sides: long profits when mark > avg; short profits when
        mark < avg, because position is negative and the signs cancel.
        """
        return (mark_price - self.avg_price) * self.position

    def total_pnl(self, mark_price: float) -> float:
        return self.realized_pnl + self.unrealized_pnl(mark_price)

    def exposure(self, mark_price: float) -> float:
        """Absolute notional exposure in pUSD (|shares| * price)."""
        return abs(self.position) * mark_price
