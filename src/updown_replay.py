r"""
Tick-level REPLAY engine for the high-precision Up/Down recordings (data/updown_hd,
written by scripts/updown_record.py).

This is what makes a backtest equal to live execution: it re-plays the exact stream
of book snapshots and price-change deltas the market actually sent — reconstructing
BOTH the Up and Down order books tick by tick — and then simulates an entry by
WALKING THE REAL ASK LADDER for the dollar size you wanted. So the fill price,
the slippage, and whether your size was even fillable are all taken from the true
book you would have hit, not from an optimistic touch price. Settlement uses the
REAL resolved outcome recorded from Gamma.

The unit of P&L is per $1 staked, matching updown_analyze.py, so results are
directly comparable — the only differences are that fills are now exact (ladder-
walked, with slippage), the Down book is real (not inferred), and win/loss is the
true settlement. SIMULATION ONLY.
"""

from __future__ import annotations

import gzip
import json
import zlib
from dataclasses import dataclass
from pathlib import Path

from src.orderbook import LocalOrderBook


# Canonical rule grids (shared by the CLI and the web API).
FADE_THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]            # buy the cheap side ≤ thr
MOMENTUM_THRESHOLDS = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]  # buy the strong side ≥ thr


def entry_windows(window_len: int) -> list[int]:
    """Entry windows scaled to the bucket: first 20/40/60/80% of its life."""
    return [max(1, round(window_len * f)) for f in (0.2, 0.4, 0.6, 0.8)]


@dataclass
class FillCfg:
    """How an entry (and optional exit) is executed against the recorded book."""
    stake: float = 1.0          # dollars to deploy per bet
    max_spread: float = 1.0     # only fill if the taken side's spread ≤ this (1.0 = off)
    latency_ms: float = 0.0     # react this many ms after the trigger (fill on the later book)
    min_fill_frac: float = 0.0  # require ≥ this fraction of the stake to actually fill, else skip
    # Exit overlay (None = hold to resolution). After entry, if the HELD side's own
    # mid crosses these, we SELL into its real bid ladder (partial fills allowed —
    # whatever the book can't absorb rides to resolution).
    stop_mid: float | None = None   # sell if the held side's mid ≤ this (stop-loss)
    take_mid: float | None = None   # sell if the held side's mid ≥ this (take-profit)


def peek_meta(path: str | Path) -> dict | None:
    """Read just the meta line (fast — decompresses only the first block)."""
    p = Path(path)
    opener = gzip.open if p.name.endswith(".gz") else open
    try:
        with opener(p, "rt", encoding="utf-8") as fh:
            o = json.loads(fh.readline())
        return o if o.get("rec") == "meta" else None
    except (OSError, EOFError, json.JSONDecodeError):
        return None


def load_recording(path: str | Path) -> tuple[dict | None, list[dict], dict | None]:
    """Return (meta, events, resolution) from one recording file (.jsonl or .jsonl.gz).

    Tolerant of a truncated final block — a recording that was hard-killed mid-write
    (so its gzip trailer / last line is incomplete) still yields everything up to the
    last good line instead of raising.
    """
    p = Path(path)
    opener = gzip.open if p.name.endswith(".gz") else open
    meta = resolution = None
    events: list[dict] = []
    fh = opener(p, "rt", encoding="utf-8")
    try:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            rec = o.get("rec")
            if rec == "ev":
                events.append(o)
            elif rec == "meta":
                meta = o
            elif rec == "resolution":
                resolution = o
    except (EOFError, OSError, zlib.error, json.JSONDecodeError):
        pass  # incomplete/garbled tail — keep every good line we read up to it
    finally:
        fh.close()
    return meta, events, resolution


def walk_asks(levels: list[tuple[float, float]], stake: float) -> tuple[float, float, float | None]:
    """Spend up to `stake` dollars walking the ask ladder (best price first).

    Returns (shares, spent, avg_price). Takes whole levels until the budget can't
    cover the next one, then a fractional slice of that level — so it deploys as
    much of `stake` as the book allows and reports the true average price paid.
    """
    shares = spent = 0.0
    for price, size in levels:
        if price <= 0 or size <= 0:
            continue
        cost = price * size
        if spent + cost <= stake:
            shares += size
            spent += cost
        else:
            rem = stake - spent
            if rem > 0:
                shares += rem / price
                spent = stake
            break
    avg = spent / shares if shares > 0 else None
    return shares, spent, avg


def walk_bids(levels: list[tuple[float, float]], shares: float) -> tuple[float, float, float | None]:
    """Sell up to `shares` into the bid ladder (best price first).

    Returns (shares_sold, proceeds, avg_price). Sells whole levels until the
    remaining shares don't cover the next one, then a partial slice — whatever the
    book can't absorb stays with the seller (a realistic partial exit).
    """
    sold = proceeds = 0.0
    remaining = shares
    for price, size in levels:
        if price <= 0 or size <= 0 or remaining <= 0:
            continue
        take = min(size, remaining)
        sold += take
        proceeds += take * price
        remaining -= take
    avg = proceeds / sold if sold > 0 else None
    return sold, proceeds, avg


def _apply(ev: dict, books: dict[str, LocalOrderBook]) -> None:
    """Apply one raw WS event to the per-token books (mirrors the live client)."""
    et = ev.get("event_type") or ev.get("type")
    if et == "book":
        b = books.get(ev.get("asset_id"))
        if b is not None:
            b.apply_snapshot(ev)
    elif et == "price_change":
        ts = ev.get("timestamp")
        for ch in ev.get("price_changes", []):
            b = books.get(ch.get("asset_id"))
            if b is not None:
                b.apply_price_changes([ch], timestamp=ts)
    # last_trade_price / tick_size_change: not needed to maintain the book


def replay_bucket(meta: dict, events: list[dict], resolution: dict | None,
                  rules: list[tuple[float, int]], cfg: FillCfg,
                  mode: str = "fade") -> dict[tuple[float, int], dict]:
    """Replay one bucket and return, per (threshold, window_min) rule, the fill result.

    The 'chance' of a side is its own book's mid.
      mode="fade"     : trigger the first time the CHEAP side's mid ≤ threshold
                        (buy the loser, betting it reverts).
      mode="momentum" : trigger the first time the STRONG side's mid ≥ threshold
                        (buy the winner as it climbs, betting the move continues).
    In both cases entry needs spread ≤ cfg.max_spread; the fill walks that side's real
    ask ladder for cfg.stake (cfg.latency_ms later, if set). Held to the real resolution.

    Result per rule: {entered, [side, shares, spent, avg, fill_frac, touch, slippage,
    won, pnl, elapsed]}.
    """
    up, down = meta["up_token"], meta["down_token"]
    start_ts = meta["start_ts"]
    books = {up: LocalOrderBook(up), down: LocalOrderBook(down)}
    winner = (resolution or {}).get("winner")
    momentum = mode == "momentum"

    state: dict[tuple[float, int], dict] = {r: {"phase": "armed", "result": None} for r in rules}

    def pick():
        um, dm = books[up].midpoint, books[down].midpoint
        if um is None or dm is None:
            return None
        if momentum:  # the STRONG side (higher mid)
            return ("Up", up, um) if um >= dm else ("Down", down, dm)
        return ("Up", up, um) if um <= dm else ("Down", down, dm)  # the CHEAP side

    for e in events:
        _apply(e["ev"], books)
        t = e["recv_ms"] / 1000.0
        elapsed = t - start_ts
        c = pick()
        for r in rules:
            st = state[r]
            if st["phase"] == "done":
                continue
            thr, win = r
            if st["phase"] == "armed":
                if elapsed > win * 60:
                    st["phase"] = "done"
                    st["result"] = {"entered": False}
                    continue
                if c is not None:
                    side, tid, mid = c
                    book = books[tid]
                    triggered = mid >= thr if momentum else mid <= thr
                    # Crossed/locked books (bid ≥ ask) also make spread NEGATIVE, which
                    # would pass the max_spread cap — skip them, same as the live trader.
                    crossed = (book.best_bid is None or book.best_ask is None
                               or book.best_bid >= book.best_ask)
                    if triggered and not crossed and book.spread is not None and book.spread <= cfg.max_spread:
                        st.update(phase="pending", side=side, tid=tid,
                                  fill_time=t + cfg.latency_ms / 1000.0, trig_elapsed=elapsed)
            if st["phase"] == "pending" and t >= st["fill_time"]:
                book = books[st["tid"]]
                shares, spent, avg = walk_asks(book.ask_levels(50), cfg.stake)
                frac = spent / cfg.stake if cfg.stake > 0 else 0.0
                if frac < cfg.min_fill_frac or avg is None:
                    st["phase"] = "armed"  # couldn't fill enough — keep waiting for depth
                    continue
                won = (st["side"] == winner) if winner else None
                touch = book.best_ask
                result = {
                    "entered": True, "side": st["side"], "shares": shares, "spent": spent,
                    "avg": avg, "fill_frac": frac, "touch": touch,
                    "slippage": (avg - touch) if touch is not None else None,
                    "won": won, "elapsed": st["trig_elapsed"],
                    "pnl": (shares - spent) if won else (-spent if won is not None else None),
                    "exit": None,
                }
                if cfg.stop_mid is not None or cfg.take_mid is not None:
                    st["phase"] = "holding"   # keep watching the held side for an exit
                    st["result"] = result
                else:
                    st["phase"] = "done"
                    st["result"] = result

            if st["phase"] == "holding":
                # Exit check on the HELD side's own book. Sell into its bid ladder;
                # anything the book can't absorb rides to resolution.
                book = books[st["tid"]]
                mid = book.midpoint
                if mid is None:
                    continue
                hit_stop = cfg.stop_mid is not None and mid <= cfg.stop_mid
                hit_take = cfg.take_mid is not None and mid >= cfg.take_mid
                if not (hit_stop or hit_take):
                    continue
                res = st["result"]
                sold, proceeds, sell_avg = walk_bids(book.bid_levels(50), res["shares"])
                left = res["shares"] - sold
                settle = None if res["won"] is None else (left if res["won"] else 0.0)
                res.update(
                    exit="stop" if hit_stop else "take",
                    exit_elapsed=elapsed, exit_mid=mid, exit_avg=sell_avg,
                    shares_sold=sold, proceeds=proceeds,
                    pnl=(proceeds + settle - res["spent"]) if settle is not None else None,
                )
                st["phase"] = "done"

    return {r: (state[r]["result"] or {"entered": False}) for r in rules}
