r"""
Record a token's live order-book feed to a file for later backtesting.

USAGE
    .\.venv\Scripts\python.exe scripts\record_market.py <token_id> --duration 300
    .\.venv\Scripts\python.exe scripts\record_market.py 0x<conditionId> --outcome Yes --duration 600

Writes data/recordings/rec_<token>_<time>.jsonl. Replay it with:
    .\.venv\Scripts\python.exe scripts\backtest.py --recording data\recordings\rec_....jsonl

Public, read-only: no key, no orders.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gamma import resolve_token  # noqa: E402
from src.recorder import Recorder  # noqa: E402
from src.ws_client import MarketStream  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Record live market data.")
    p.add_argument("target", help="token id, or 0x… conditionId")
    p.add_argument("--outcome", default="Yes", help="outcome if given a conditionId")
    p.add_argument("--duration", type=float, default=300.0, help="seconds to record")
    args = p.parse_args()

    try:
        token_id, _ = resolve_token(args.target, args.outcome)
    except ValueError as e:
        raise SystemExit(str(e))

    print(f"Recording token {token_id[:18]}... for {args.duration:g}s (Ctrl-C to stop early)")

    with Recorder(token_id) as rec:
        stream = MarketStream([token_id], on_raw=rec.write)
        stream.run_in_thread()
        start = time.monotonic()
        try:
            while time.monotonic() - start < args.duration:
                time.sleep(0.5)
                # Light progress so you know it's alive.
                print(f"\r  captured {rec.count} events", end="", flush=True)
        except KeyboardInterrupt:
            print("\n  stopped early.")
        finally:
            stream.stop()
        print(f"\nSaved {rec.count} events -> {rec.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
