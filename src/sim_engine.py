"""
The simulation engine: the brain that runs the market-making loop.

It ties together the pieces built so far:
    LocalOrderBook  -> what the market looks like right now (fed live by the WS)
    StrategyConfig  -> our quoting parameters
    compute_quote   -> where we WANT to quote
    Inventory       -> our position and P&L
    safety + limits -> kill switch, max position, daily-loss cap
    SimLogger       -> record everything

On every order-book update we run one cycle:
    1. Did the market move through our resting quotes? -> simulate fills.
    2. Are any risk limits breached? -> halt and stop quoting.
    3. Recompute desired quotes (fair value + inventory skew + side limits).
    4. If they moved enough, cancel & replace (re-quote).

THE FILL MODEL (read this — it defines what the numbers mean):
    Our quotes are passive maker orders resting in the book. We model a resting
    BID as filled when the market's best ASK trades down to or below our bid
    price (i.e. someone became willing to sell at our price). Symmetrically, our
    ASK fills when the best BID reaches our ask price.

    Simplifying assumptions (intentionally optimistic / simple for v1):
      * We assume we're first in the queue and get our FULL quoted size on a
        cross. Real life: queue position and available size limit fills.
      * Fills happen at our quoted price (no price improvement, no slippage).
      * No latency: we react on the same book update that crosses us.
    These are reasonable for learning and for comparing parameter settings, but
    they will overstate fill rates versus production. Phase 4 keeps this model
    so backtests and live-sim are apples-to-apples.

SAFETY: this engine NEVER sends an order anywhere. It only updates in-memory
state and logs. Real order placement is a later phase, gated behind live mode.
"""

from __future__ import annotations

from config.settings import SETTINGS
from src.inventory import Inventory
from src.orderbook import LocalOrderBook
from src.safety import kill_switch_engaged, daily_loss_within_limit
from src.sim_logger import SimLogger
from src.strategy import Quote, StrategyConfig, compute_quote, should_requote


class SimEngine:
    def __init__(self, token_id: str, cfg: StrategyConfig, logger: SimLogger) -> None:
        self.token_id = token_id
        self.cfg = cfg
        self.log = logger
        self.inv = Inventory()
        self.resting: Quote | None = None
        self.halted = False
        self.halt_reason = ""
        self.last_mid: float | None = None
        self._last_status_mono = 0.0
        self._warned_spread = False
        self.cycles = 0

    # --- main entry point (called on every book update) -------------------

    def on_book(self, book: LocalOrderBook) -> None:
        if self.halted:
            return

        # Pick up the real tick size from the live book so our snapping matches.
        if book.tick_size:
            self.cfg.tick_size = book.tick_size
            # A half-spread below one tick can't be expressed on the price grid
            # and collapses into ASYMMETRIC quotes (ask at the mid, bid a tick
            # below), which fill one-sided and let inventory run away. Floor the
            # half-spread at one tick so the two sides are always symmetric.
            tick = self.cfg.tick_size
            if self.cfg.min_half_spread < tick:
                self.cfg.min_half_spread = tick
            if self.cfg.spread / 2 < tick and not self._warned_spread:
                self._warned_spread = True
                print(f"  [warn] requested spread {self.cfg.spread} is below 2 ticks "
                      f"({2 * tick:g}); quoting at the 1-tick-per-side minimum. "
                      f"Widen --spread to control your edge.")

        mid = book.midpoint
        if mid is None:
            # One-sided book: no fair value, so don't quote this tick.
            return
        self.last_mid = mid
        # Stamp logged events with market time (the book's own timestamp).
        self.log.mkt_ts = book.timestamp
        self.cycles += 1

        # 1) simulate fills against the *previous* resting quotes & new book.
        self._simulate_fills(book, mid)

        # 2) risk checks — may halt and stop quoting.
        if not self._check_risk(mid):
            return

        # 3) compute desired quotes with inventory skew + position-limit gating.
        desired = self._desired_quote(book, mid)

        # 4) re-quote if the desired quotes moved enough (or a side was filled).
        if should_requote(self.cfg, self.resting, desired):
            self.resting = desired
            self.log.quote(
                desired.bid_price, desired.ask_price, self.cfg.size,
                mid, self.inv.position, self.inv.total_pnl(mid),
            )

    # --- step 1: fills ----------------------------------------------------

    def _simulate_fills(self, book: LocalOrderBook, mid: float) -> None:
        if self.resting is None:
            return
        q = self.resting
        best_bid, best_ask = book.best_bid, book.best_ask

        # Our resting BID fills when the market offers to sell at/below it.
        if q.bid_price is not None and best_ask is not None and best_ask <= q.bid_price:
            self._record_fill("BUY", q.bid_price, q.bid_size, mid)
            q.bid_price = None  # consumed; will be re-armed on next re-quote

        # Our resting ASK fills when the market bids at/above it.
        if q.ask_price is not None and best_bid is not None and best_bid >= q.ask_price:
            self._record_fill("SELL", q.ask_price, q.ask_size, mid)
            q.ask_price = None

    def _record_fill(self, side: str, price: float, size: float, mid: float) -> None:
        self.inv.on_fill(side, price, size)
        self.log.fill(
            side, price, size, mid,
            self.inv.position, self.inv.avg_price, self.inv.realized_pnl,
        )

    # --- step 2: risk -----------------------------------------------------

    def _check_risk(self, mid: float) -> bool:
        """Return True if it's safe to keep quoting; halt and return False if not."""
        if kill_switch_engaged():
            self._halt("kill switch file present")
            return False

        # Daily-loss cap on total (realized + unrealized) P&L.
        total = self.inv.total_pnl(mid)
        if not daily_loss_within_limit(total):
            self._halt(f"daily loss cap hit (total P&L {total:+.4f} pUSD)")
            return False
        return True

    def _halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
        self.resting = None  # cancel all resting quotes
        self.log.halt(reason)

    # --- step 3: desired quote -------------------------------------------

    def _desired_quote(self, book: LocalOrderBook, mid: float) -> Quote:
        # Convert the pUSD position cap into a share cap at the current price.
        cap_shares = SETTINGS.max_position_usd / mid if mid > 0 else float("inf")

        # Normalised inventory in [-1, 1] drives the skew.
        ratio = self.inv.position / cap_shares if cap_shares not in (0, float("inf")) else 0.0

        # Position-limit gating: stop quoting the side that pushes us further
        # past the cap, but always allow the side that reduces our position.
        allow_bid = self.inv.position < cap_shares      # don't buy more if maxed long
        allow_ask = self.inv.position > -cap_shares     # don't sell more if maxed short

        q = compute_quote(self.cfg, mid, ratio, allow_bid=allow_bid, allow_ask=allow_ask)

        # Keep quotes PASSIVE: never price through the current book (that would
        # be a taker order, not market making). Clamp to just inside the touch.
        tick = self.cfg.tick_size
        if q.bid_price is not None and book.best_ask is not None and q.bid_price >= book.best_ask:
            q.bid_price = round(book.best_ask - tick, 10)
        if q.ask_price is not None and book.best_bid is not None and q.ask_price <= book.best_bid:
            q.ask_price = round(book.best_bid + tick, 10)
        return q

    # --- status / summary -------------------------------------------------

    def log_status(self) -> None:
        """Emit a status line right now (used by both live runs and backtests)."""
        if self.last_mid is None:
            return
        self.log.status(
            self.last_mid, self.inv.position, self.inv.exposure(self.last_mid),
            self.inv.realized_pnl, self.inv.unrealized_pnl(self.last_mid),
        )

    def maybe_status(self, every_seconds: float = 5.0) -> None:
        """Print a status line at most every `every_seconds` (live run loop)."""
        import time

        now = time.monotonic()
        if self.last_mid is None or now - self._last_status_mono < every_seconds:
            return
        self._last_status_mono = now
        self.log_status()

    def summary(self) -> dict:
        mid = self.last_mid or 0.0
        return {
            "cycles": self.cycles,
            "fills": self.inv.buys + self.inv.sells,
            "buys": self.inv.buys,
            "sells": self.inv.sells,
            "position": round(self.inv.position, 4),
            "avg_price": round(self.inv.avg_price, 6),
            "realized_pnl": round(self.inv.realized_pnl, 6),
            "unrealized_pnl": round(self.inv.unrealized_pnl(mid), 6),
            "total_pnl": round(self.inv.total_pnl(mid), 6),
            "halted": self.halted,
            "halt_reason": self.halt_reason,
        }
