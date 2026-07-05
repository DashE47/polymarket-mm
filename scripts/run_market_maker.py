r"""
Run the market-making strategy in SIMULATION against the live order book.

It quotes a two-sided market around the book midpoint, skews quotes by inventory,
re-quotes as the book moves, enforces the risk limits, and simulates fills
locally. It NEVER sends a real order.

USAGE
    # simplest: pick a token from search_markets.py
    .\.venv\Scripts\python.exe scripts\run_market_maker.py <token_id>

    # tune parameters and run for 2 minutes
    .\.venv\Scripts\python.exe scripts\run_market_maker.py 0x<conditionId> --outcome Yes \
        --spread 0.01 --size 100 --skew 0.02 --widen 0.01 --requote 0.002 --duration 120

Stop early with Ctrl-C. Every quote/fill is printed and written to logs/mm_*.jsonl.
To halt instantly from another terminal: create a file named KILL in the project
root (New-Item KILL).
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SETTINGS, Mode  # noqa: E402
from src.connection import build_public_client  # noqa: E402
from src.gamma import resolve_token  # noqa: E402
from src.market_data import fetch_order_book  # noqa: E402
from src.orderbook import LocalOrderBook  # noqa: E402
from src.sim_engine import SimEngine  # noqa: E402
from src.sim_logger import SimLogger  # noqa: E402
from src.strategy import StrategyConfig  # noqa: E402
from src.ws_client import MarketStream  # noqa: E402


def _resolve_token(target: str, outcome: str) -> tuple[str, str]:
    try:
        token_id, market = resolve_token(target, outcome)
    except ValueError as e:
        raise SystemExit(str(e))
    title = f"{market.question}  [{outcome}]" if market else f"token {target[:18]}..."
    return token_id, title


def main() -> int:
    p = argparse.ArgumentParser(description="Simulated market maker.")
    p.add_argument("target", help="token id, or 0x… conditionId")
    p.add_argument("--outcome", default="Yes", help="outcome if given a conditionId")
    p.add_argument("--spread", type=float, default=0.02, help="target total spread")
    p.add_argument("--size", type=float, default=50.0, help="shares quoted per side")
    p.add_argument("--skew", type=float, default=0.02, help="max quote shift at full inventory")
    p.add_argument("--widen", type=float, default=0.01, help="extra half-spread at full inventory")
    p.add_argument("--requote", type=float, default=0.002, help="min move before re-quoting")
    p.add_argument("--duration", type=float, default=0.0, help="seconds to run (0 = until Ctrl-C)")
    p.add_argument("--status-interval", type=float, default=5.0, help="status line cadence (s)")
    args = p.parse_args()

    # --- safety gate: this phase only runs in simulation ------------------
    if SETTINGS.mode == Mode.READONLY:
        raise SystemExit("MODE=readonly: market making is disabled. Set MODE=simulation.")
    if SETTINGS.mode == Mode.LIVE:
        raise SystemExit(
            "MODE=live: real order placement is not implemented in this phase. "
            "Run with MODE=simulation to simulate fills against the live book."
        )

    token_id, title = _resolve_token(args.target, args.outcome)

    cfg = StrategyConfig(
        spread=args.spread, size=args.size, inventory_skew=args.skew,
        inventory_widen=args.widen, requote_threshold=args.requote,
    )
    params = {
        "title": title, "mode": SETTINGS.mode.value,
        "spread": cfg.spread, "size": cfg.size, "skew": cfg.inventory_skew,
        "widen": cfg.inventory_widen, "requote_threshold": cfg.requote_threshold,
        "max_position_usd": SETTINGS.max_position_usd,
        "max_daily_loss_usd": SETTINGS.max_daily_loss_usd,
    }

    print("=" * 70)
    print("SIMULATED MARKET MAKER  (no real orders are sent)")
    print(f"  market : {title}")
    print(f"  params : spread {cfg.spread} | size {cfg.size:g} | skew {cfg.inventory_skew} "
          f"| widen {cfg.inventory_widen} | requote {cfg.requote_threshold}")
    print(f"  limits : max position ${SETTINGS.max_position_usd:g} | "
          f"max daily loss ${SETTINGS.max_daily_loss_usd:g}")
    print("=" * 70)

    logger = SimLogger(token_id, params)
    engine = SimEngine(token_id, cfg, logger)

    # Seed from a REST snapshot so we can quote on the very first tick.
    client = build_public_client()
    seed_book = fetch_order_book(client, token_id)
    engine.on_book(seed_book)

    # Stream live updates into the engine.
    def on_update(_tid: str, book: LocalOrderBook) -> None:
        engine.on_book(book)

    stream = MarketStream([token_id], on_update=on_update)
    stream.books[token_id] = seed_book
    stream.run_in_thread()

    start = time.monotonic()
    try:
        while True:
            time.sleep(0.25)
            engine.maybe_status(args.status_interval)
            if engine.halted:
                print("\nEngine halted by a risk limit; stopping.")
                break
            if args.duration and (time.monotonic() - start) >= args.duration:
                print("\nDuration reached; stopping.")
                break
    except KeyboardInterrupt:
        print("\nInterrupted; stopping.")
    finally:
        stream.stop()
        logger.close()

    # --- summary ----------------------------------------------------------
    s = engine.summary()
    print("\n" + "-" * 70)
    print("RUN SUMMARY")
    for k in ("cycles", "fills", "buys", "sells", "position", "avg_price",
              "realized_pnl", "unrealized_pnl", "total_pnl", "halted", "halt_reason"):
        print(f"  {k:16} : {s[k]}")
    print(f"  log file         : {logger.path}")
    print("-" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
