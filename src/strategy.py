"""
The quoting strategy: turn a fair-value estimate + current inventory into a
two-sided quote (a bid and an ask).

This module is deliberately PURE — no network, no order book, no logging. It's
just math: given some numbers, return the prices/sizes we'd like to show. That
makes it trivial to unit test and to reuse unchanged in the live runner (Phase
3) and the backtester (Phase 4).

The model, from the inside out:

  fair_value
      Our estimate of the "true" price. We start with the order-book midpoint
      (passed in by the caller). Everything is quoted around this.

  inventory skew  (shift)
      If we're long, we want to sell more eagerly and buy less eagerly, to pull
      our position back toward flat. We do this by shifting BOTH quotes down by
      an amount proportional to how big our position is relative to the max:
          reservation = fair_value - skew * inventory_ratio
      (inventory_ratio is +1 when maxed long, -1 when maxed short.) When long,
      reservation drops, so both bid and ask drop — we undercut to offload.

  spread + inventory widening
      Around the reservation price we place a bid and ask half a spread away.
      Optionally we WIDEN the spread as inventory grows, demanding more edge to
      take on even more risk:
          half_spread = base_half + widen * |inventory_ratio|

  tick snapping & bounds
      Polymarket prices live on a tick grid (e.g. 0.001) inside (0, 1). We snap
      to the grid and clamp away from the 0 and 1 boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StrategyConfig:
    """All the knobs. Defaults are sane starting points, not tuned values."""

    spread: float = 0.02          # target TOTAL spread (ask - bid) at zero inventory
    size: float = 50.0            # shares quoted per side
    min_half_spread: float = 0.001  # never quote tighter than this half-spread
    inventory_skew: float = 0.02  # max price shift of quotes at full inventory
    inventory_widen: float = 0.01  # extra half-spread at full inventory
    requote_threshold: float = 0.002  # min price move before we cancel/replace
    tick_size: float = 0.001      # price grid; overwritten from the live book


@dataclass
class Quote:
    bid_price: float | None
    bid_size: float
    ask_price: float | None
    ask_size: float

    def is_two_sided(self) -> bool:
        return self.bid_price is not None and self.ask_price is not None


def _snap(price: float, tick: float) -> float:
    """Round a price to the nearest tick and keep it strictly inside (0, 1)."""
    snapped = round(round(price / tick) * tick, 10)
    # Stay at least one tick away from the 0 and 1 boundaries.
    return min(max(snapped, tick), 1 - tick)


def compute_quote(
    cfg: StrategyConfig,
    fair_value: float,
    inventory_ratio: float,
    allow_bid: bool = True,
    allow_ask: bool = True,
) -> Quote:
    """Compute desired bid/ask around `fair_value`.

    Args:
        fair_value: current fair price (e.g. order-book midpoint).
        inventory_ratio: signed position size as a fraction of the max position,
            clamped to [-1, 1]. +1 = maxed long, -1 = maxed short.
        allow_bid / allow_ask: let the caller (risk layer) suppress a side, e.g.
            stop bidding once we're at the long position limit.
    """
    # Clamp the ratio so a position briefly over the limit can't explode the math.
    ratio = max(-1.0, min(1.0, inventory_ratio))

    # Skew: shift quotes against our inventory to mean-revert the position.
    reservation = fair_value - cfg.inventory_skew * ratio

    # Half-spread, optionally widened by how much inventory we're carrying.
    half = cfg.spread / 2 + cfg.inventory_widen * abs(ratio)
    half = max(half, cfg.min_half_spread)

    tick = cfg.tick_size
    bid_price = _snap(reservation - half, tick) if allow_bid else None
    ask_price = _snap(reservation + half, tick) if allow_ask else None

    # If snapping collapsed the two sides onto the same tick (very tight spread
    # near a boundary), nudge them apart by one tick so bid < ask always holds.
    if bid_price is not None and ask_price is not None and bid_price >= ask_price:
        bid_price = _snap(ask_price - tick, tick)

    return Quote(
        bid_price=bid_price,
        bid_size=cfg.size,
        ask_price=ask_price,
        ask_size=cfg.size,
    )


def should_requote(cfg: StrategyConfig, old: Quote | None, new: Quote) -> bool:
    """True if `new` differs from the resting `old` quote enough to re-quote.

    We avoid churning orders on every tiny tick: only cancel/replace when a side
    moved by at least `requote_threshold`, or a side appeared/disappeared.
    """
    if old is None:
        return True
    for old_px, new_px in ((old.bid_price, new.bid_price), (old.ask_price, new.ask_price)):
        if (old_px is None) != (new_px is None):
            return True  # a side turned on or off
        if old_px is not None and new_px is not None:
            if abs(new_px - old_px) >= cfg.requote_threshold:
                return True
    return False
