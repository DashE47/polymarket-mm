r"""
Live study of the "fade the longshot" idea on short-term crypto Up/Down markets.

Your rule: on each rolling 5-min bucket, if a side's chance dips to <= THRESHOLD
within the first ENTRY_WINDOW minutes, place a (simulated) $STAKE on that low side
at that price; settle win/loss at resolution. Repeat for N buckets and report the
hit rate vs. the price you paid — i.e. is the market UNDER-pricing these flip-backs?

Why live (not historical): the 5-min markets are too thin for the price-history
API to return their intra-life path, so we can't replay the past. We watch them
live instead. SIMULATION ONLY — places no real orders.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_study.py --asset Bitcoin --threshold 0.25 --bets 10
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import gamma  # noqa: E402
from src.connection import build_public_client  # noqa: E402
from src.market_data import get_midpoint  # noqa: E402

BUCKET_SECONDS = 300  # 5-minute markets


def _end_dt(iso: str):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _next_bucket(asset: str, done: set, entry_window_min: float):
    """The soonest genuine 5-min bucket for `asset` that we can still catch early.

    Markets come in 5-min AND 15-min (etc.) durations, so we filter by the REAL
    start→end span (~5 min) and skip any we've already missed the entry window on —
    otherwise we'd 'enter' a long bucket that's actually near resolution.
    """
    now = time.time()
    for m in gamma.crypto_updown(80):
        if not m.question.lower().startswith(asset.lower()):
            continue
        if m.condition_id in done or "Up" not in m.tokens or "Down" not in m.tokens:
            continue
        end = _end_dt(m.end_date)
        if not end or gamma.window_minutes(m.question) != 5:
            continue  # 5-minute buckets only (window parsed from the title)
        start = end.timestamp() - 5 * 60
        if now >= end.timestamp() or now > start + entry_window_min * 60:
            continue  # already over, or past the entry window (joined too late)
        return m, start, end.timestamp()
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Live Up/Down longshot study.")
    p.add_argument("--asset", default="Bitcoin")
    p.add_argument("--threshold", type=float, default=0.25, help="enter when a side dips to <= this")
    p.add_argument("--entry-window", type=float, default=2.0, help="minutes from bucket start to allow entry")
    p.add_argument("--bets", type=int, default=10, help="how many triggered bets to collect")
    p.add_argument("--stake", type=float, default=1.0)
    p.add_argument("--poll", type=float, default=8.0, help="seconds between chance checks")
    p.add_argument("--max-buckets", type=int, default=40, help="give up after this many buckets watched")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # avoid cp1255 crashes

    client = build_public_client()
    done: set[str] = set()
    bets: list[dict] = []
    watched = 0

    print(f"Studying {args.asset} 5-min Up/Down — enter a side at <= {args.threshold} "
          f"within first {args.entry_window:g} min, ${args.stake:g} each, target {args.bets} bets.\n"
          f"SIMULATION ONLY. Ctrl-C to stop early and see the summary.\n")

    try:
        while len(bets) < args.bets and watched < args.max_buckets:
            found = _next_bucket(args.asset, done, args.entry_window)
            if found is None:
                print("  …no catchable 5-min bucket right now; waiting 15s")
                time.sleep(15)
                continue
            m, start, end_ts = found

            done.add(m.condition_id)
            watched += 1
            end = _end_dt(m.end_date)
            up_tok = m.tokens["Up"]
            entry = None  # (side, price)
            last_up = m.outcome_prices.get("Up")
            label = m.question.split(" - ")[-1]
            print(f"[bucket {watched}] {label}  (resolves {end.astimezone().strftime('%H:%M:%S')})")

            # Watch until the bucket resolves.
            while time.time() < end.timestamp():
                up = get_midpoint(client, up_tok)
                if up is not None:
                    last_up = up
                    elapsed_min = (time.time() - start) / 60.0
                    if entry is None and elapsed_min <= args.entry_window:
                        low = min(up, 1 - up)
                        if low <= args.threshold:
                            side = "Up" if up <= 1 - up else "Down"
                            entry = (side, low)
                            print(f"    ▸ ENTER {side} @ {low:.3f}  ({elapsed_min:.1f} min in)")
                time.sleep(args.poll)

            # Resolve from the last observed chance (converges to ~1/0 at the end).
            if last_up is None:
                print("    (no price seen — skipping)\n")
                continue
            winner = "Up" if last_up >= 0.5 else "Down"

            if entry is None:
                print(f"    no trigger (winner: {winner})\n")
                continue
            side, price = entry
            won = side == winner
            pnl = args.stake * ((1 - price) / price) if won else -args.stake
            bets.append({"side": side, "price": price, "won": won, "pnl": pnl})
            n = len(bets); wins = sum(b["won"] for b in bets); total = sum(b["pnl"] for b in bets)
            avg_entry = sum(b["price"] for b in bets) / n
            print(f"    {'WON ✅' if won else 'lost ❌'} {side} @ {price:.3f} (winner {winner})  "
                  f"| running: {wins}/{n} wins ({wins/n:.0%}), P&L ${total:+.2f}, avg entry {avg_entry:.3f}\n")
    except KeyboardInterrupt:
        print("\n(stopped early)")

    # --- summary ----------------------------------------------------------
    print("=" * 64)
    if not bets:
        print(f"No triggered bets in {watched} buckets watched. The chance may not "
              f"have dipped to {args.threshold} early enough — try a higher threshold.")
        return 0
    n = len(bets); wins = sum(b["won"] for b in bets); total = sum(b["pnl"] for b in bets)
    avg_entry = sum(b["price"] for b in bets) / n
    print(f"STUDY RESULT — {args.asset} Up/Down, entry <= {args.threshold}")
    print(f"  buckets watched : {watched}")
    print(f"  bets placed     : {n}  (${args.stake:g} each = ${n * args.stake:g} staked)")
    print(f"  wins            : {wins}  →  hit rate {wins / n:.1%}")
    print(f"  avg entry price : {avg_entry:.3f}  (break-even hit rate = {avg_entry:.1%})")
    print(f"  total P&L       : ${total:+.2f}")
    verdict = ("EDGE? hit rate beat the price" if wins / n > avg_entry + 0.02
               else "no edge — hit rate ≈/below the price (as theory predicts)")
    print(f"  verdict         : {verdict}")
    print("  NOTE: a real edge needs ~50-100+ bets to trust; this is a small sample.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
