r"""
Live, in-place view of one token's order book.

USAGE
    # by token id (from search_markets.py)
    .\.venv\Scripts\python.exe scripts\live_view.py 39971087496427056640429359043364261029374524049464674733142166279730655826181

    # or by market + outcome (resolves the token id for you)
    .\.venv\Scripts\python.exe scripts\live_view.py 0xbaf7…8da4 --outcome No --depth 8

Seeds the book from a REST snapshot for instant display, then streams live
updates over the WebSocket and re-renders in place. Ctrl-C to quit.

Public, read-only: no key, no orders.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connection import build_public_client  # noqa: E402
from src.gamma import resolve_token  # noqa: E402
from src.market_data import fetch_order_book  # noqa: E402
from src.orderbook import LocalOrderBook  # noqa: E402
from src.ws_client import MarketStream  # noqa: E402


def _setup_console() -> None:
    """Prepare the terminal: UTF-8 output + ANSI escape handling.

    Two Windows-specific gotchas this guards against:
      * Output encoding: when stdout isn't an interactive console (e.g. piped to
        a file), Python uses the locale codepage, which on many Windows installs
        can't encode the box-drawing/dash glyphs we draw. Forcing UTF-8 makes the
        view work identically whether shown live or redirected.
      * ANSI: older consoles don't process the colour/clear escape codes unless
        we enable virtual-terminal mode.
    """
    # Force UTF-8 so glyphs like ─ — … never raise UnicodeEncodeError.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # ENABLE_PROCESSED_OUTPUT(1) | ENABLE_VIRTUAL_TERMINAL_PROCESSING(4) = 7
        # on the standard output handle (-11).
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def _resolve_token(target: str, outcome: str) -> tuple[str, str | None]:
    """Return (token_id, title). Accepts a token id or a 0x conditionId."""
    try:
        token_id, market = resolve_token(target, outcome)
    except ValueError as e:
        raise SystemExit(str(e))
    return token_id, (f"{market.question}  [{outcome}]" if market else None)


def _fmt_price(price: float | None, dp: int) -> str:
    return "—" if price is None else f"{price:.{dp}f}"


def _render(book: LocalOrderBook, title: str | None, depth: int) -> None:
    """Clear the screen and draw the current book."""
    # Decide price decimals from tick size (e.g. 0.001 -> 3 dp).
    dp = 3
    if book.tick_size:
        dp = max(0, len(f"{book.tick_size:.10f}".rstrip("0").split(".")[-1]))
        dp = min(dp, 4)

    top = book.top()
    lines: list[str] = []
    lines.append("\033[H\033[J")  # cursor home + clear screen
    lines.append(title or f"token {book.token_id[:18]}…")
    ts = (
        datetime.fromtimestamp(book.timestamp / 1000, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        if book.timestamp else "—"
    )
    lines.append(f"tick {_fmt_price(book.tick_size, dp)}   "
                 f"last trade {_fmt_price(book.last_trade_price, dp)}   "
                 f"updated {ts}Z")
    lines.append("")
    lines.append(f"  {'SIDE':<4} {'PRICE':>8} {'SIZE':>16}")

    # Asks: show from higher price down to the best (lowest) ask just above the
    # spread divider — the conventional depth-of-market layout.
    for price, size in reversed(book.ask_levels(depth)):
        lines.append(f"  \033[31m{'ASK':<4} {price:>8.{dp}f} {size:>16,.2f}\033[0m")

    spread = _fmt_price(top.spread, dp)
    mid = _fmt_price(top.midpoint, dp)
    lines.append(f"  {'─' * 30}  spread {spread} | mid {mid}")

    # Bids: best (highest) first, just below the divider.
    for price, size in book.bid_levels(depth):
        lines.append(f"  \033[32m{'BID':<4} {price:>8.{dp}f} {size:>16,.2f}\033[0m")

    lines.append("")
    lines.append(f"  best bid {_fmt_price(top.best_bid, dp)} | "
                 f"best ask {_fmt_price(top.best_ask, dp)} | "
                 f"mid {mid} | spread {spread}")
    lines.append("\n  (Ctrl-C to quit)")
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live order-book view.")
    parser.add_argument("target", help="a token id, or a 0x… conditionId")
    parser.add_argument("--outcome", default="Yes",
                        help="which outcome when given a conditionId (default Yes)")
    parser.add_argument("--depth", type=int, default=10, help="levels per side")
    args = parser.parse_args()

    token_id, title = _resolve_token(args.target, args.outcome)
    _setup_console()

    # 1) Instant first paint from a REST snapshot.
    client = build_public_client()
    book = fetch_order_book(client, token_id)
    _render(book, title, args.depth)

    # 2) Stream live updates. We throttle re-renders so a burst of deltas can't
    #    spam the terminal; ~15 fps is plenty smooth and easy on the eyes.
    last_render = 0.0
    min_interval = 1 / 15

    def on_update(tid: str, live_book: LocalOrderBook) -> None:
        nonlocal last_render
        now = time.monotonic()
        if now - last_render >= min_interval:
            last_render = now
            _render(live_book, title, args.depth)

    stream = MarketStream([token_id], on_update=on_update)
    # Reuse the snapshot we already fetched so there's no blank moment.
    stream.books[token_id] = book

    try:
        stream.run_forever()
    except KeyboardInterrupt:
        stream.stop()
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
