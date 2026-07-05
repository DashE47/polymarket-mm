r"""
Backtest the market-making strategy on historical data.

Two data sources:

  A) A RECORDING you captured with record_market.py (faithful book replay):
       .\.venv\Scripts\python.exe scripts\backtest.py --recording data\recordings\rec_....jsonl `
           --spread 0.01 --size 100

  B) HISTORICAL PRICES from the CLOB (works with no pre-recorded data; coarser,
     mid-crossing fill model):
       .\.venv\Scripts\python.exe scripts\backtest.py 0x<conditionId> --outcome Yes --history `
           --interval 1d --fidelity 5 --spread 0.01 --size 100

Strategy parameters are the same flags as run_market_maker.py, so you can move a
setting straight from live-sim to backtest. Risk limits come from .env
(MAX_POSITION_USD / MAX_DAILY_LOSS_USD). No orders are ever sent.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connection import build_public_client  # noqa: E402
from src.gamma import resolve_token  # noqa: E402
from src.history import VALID_INTERVALS, fetch_price_history  # noqa: E402
from src.replay import replay_price_series, replay_recording, sniff_token_id  # noqa: E402
from src.sim_engine import SimEngine  # noqa: E402
from src.sim_logger import SimLogger  # noqa: E402
from src.strategy import StrategyConfig  # noqa: E402


def _add_strategy_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--spread", type=float, default=0.02)
    p.add_argument("--size", type=float, default=50.0)
    p.add_argument("--skew", type=float, default=0.02)
    p.add_argument("--widen", type=float, default=0.01)
    p.add_argument("--requote", type=float, default=0.002)


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest the market maker.")
    p.add_argument("target", nargs="?", help="token id or 0x… conditionId (history mode)")
    p.add_argument("--recording", help="path to a recording from record_market.py")
    p.add_argument("--history", action="store_true", help="fetch historical prices for target")
    p.add_argument("--outcome", default="Yes")
    p.add_argument("--interval", default="1d", help=f"one of {sorted(VALID_INTERVALS)}")
    p.add_argument("--fidelity", type=int, default=5, help="resolution in minutes")
    p.add_argument("--status-every", type=int, default=0, help="status line every N updates (0=off)")
    _add_strategy_args(p)
    args = p.parse_args()

    cfg = StrategyConfig(
        spread=args.spread, size=args.size, inventory_skew=args.skew,
        inventory_widen=args.widen, requote_threshold=args.requote,
    )

    # --- choose data source ----------------------------------------------
    if args.recording:
        try:
            token_id = sniff_token_id(args.recording)
        except ValueError as e:
            raise SystemExit(str(e))
        source = f"recording {Path(args.recording).name}"
        runner = lambda eng: replay_recording(  # noqa: E731
            args.recording, token_id, eng,
            status_every=args.status_every or 500,
        )
    elif args.history and args.target:
        if args.interval not in VALID_INTERVALS:
            raise SystemExit(f"--interval must be one of {sorted(VALID_INTERVALS)}")
        client = build_public_client()
        try:
            token_id, _ = resolve_token(args.target, args.outcome)
        except ValueError as e:
            raise SystemExit(str(e))
        tick = float(client.get_tick_size(token_id))
        cfg.tick_size = tick
        series = fetch_price_history(client, token_id, args.interval, args.fidelity)
        if not series:
            raise SystemExit("No history returned for that token/interval.")
        source = f"history {args.interval}@{args.fidelity}m ({len(series)} points)"
        runner = lambda eng: replay_price_series(  # noqa: E731
            series, token_id, tick, eng, status_every=args.status_every or 50,
        )
    else:
        raise SystemExit("Provide --recording <path>, or <target> with --history.")

    params = {
        "source": source, "spread": cfg.spread, "size": cfg.size,
        "skew": cfg.inventory_skew, "widen": cfg.inventory_widen,
        "requote_threshold": cfg.requote_threshold,
    }
    print("=" * 70)
    print("BACKTEST  (no real orders)")
    print(f"  source : {source}")
    print(f"  token  : {token_id[:20]}...")
    print(f"  params : spread {cfg.spread} | size {cfg.size:g} | skew {cfg.inventory_skew} "
          f"| widen {cfg.inventory_widen} | requote {cfg.requote_threshold}")
    print("=" * 70)

    logger = SimLogger(token_id, params)
    engine = SimEngine(token_id, cfg, logger)
    updates = runner(engine)
    logger.close()

    s = engine.summary()
    print("\n" + "-" * 70)
    print("BACKTEST SUMMARY")
    print(f"  updates replayed : {updates}")
    for k in ("fills", "buys", "sells", "position", "avg_price",
              "realized_pnl", "unrealized_pnl", "total_pnl", "halted", "halt_reason"):
        print(f"  {k:16} : {s[k]}")
    print(f"  log file         : {logger.path}")
    print("-" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
