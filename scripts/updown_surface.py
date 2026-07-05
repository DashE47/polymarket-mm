r"""
Build the WIN-PROBABILITY / CALIBRATION SURFACE for short-term Up/Down markets.

For every (time-into-the-bucket, current price) state a side can be in, it asks:
how often did that side ACTUALLY win, versus what its price implied? That single
map answers three things at once:
  * the "fade the longshot" story (low-price region),
  * its opposite, backing the favourite (high-price region), and
  * the EXIT question — at any moment your position sits at some (price, time)
    state, and this map says whether holding it is favourable or not.

Method: from the recorded chance-paths (data/updown/updown_*.jsonl), each sample
contributes two observations — the Up side at its price and the Down side at
1-price — labelled by whether that side eventually won. We bin by
(fraction of the bucket elapsed × price) and report, per cell:
    mispricing = empirical win-rate − average price  (in percentage points)
≈ 0 everywhere  → the market is calibrated (no edge to enter OR exit on).
clearly ≠ 0     → that state is mis-priced: a real place to fade, back, or exit.

CAVEAT: samples within a bucket (and across the 4 correlated assets) are highly
autocorrelated, so per-cell noise is much larger than the raw count implies. Trust
big, consistent coloured regions, not lone cells.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_surface.py                 # text surface, 5-min
    .\.venv\Scripts\python.exe scripts\updown_surface.py --window-len 15
    .\.venv\Scripts\python.exe scripts\updown_surface.py --json          # emit JSON (for the UI)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT  # noqa: E402

PRICE_BINS = 10   # 0.0–1.0 in 0.1 steps
TIME_BINS = 10    # 0–100% of the bucket's life in 10% steps


def load_all(window_len: int) -> list[dict]:
    target = window_len * 60
    buckets = []
    for f in sorted((PROJECT_ROOT / "data" / "updown").glob("updown_*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    b = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if abs(b.get("dur_s", 0) - target) <= 60 and b.get("samples"):
                    buckets.append(b)
    return buckets


def build_surface(buckets: list[dict]) -> dict:
    # per cell: [n, sum_won, sum_price]
    cells = [[[0, 0.0, 0.0] for _ in range(TIME_BINS)] for _ in range(PRICE_BINS)]
    obs = 0
    for b in buckets:
        dur = b.get("dur_s") or 300
        up_won = 1.0 if b["winner"] == "Up" else 0.0
        for s in b["samples"]:
            t, mid = s[0], s[1]
            frac = min(max(t / dur, 0.0), 0.999)
            tb = min(int(frac * TIME_BINS), TIME_BINS - 1)
            for price, won in ((mid, up_won), (1.0 - mid, 1.0 - up_won)):
                pb = min(max(int(price * PRICE_BINS), 0), PRICE_BINS - 1)
                c = cells[pb][tb]
                c[0] += 1
                c[1] += won
                c[2] += price
                obs += 1
    grid = []
    wsum = wcount = 0.0
    for pb in range(PRICE_BINS):
        row = []
        for tb in range(TIME_BINS):
            n, sw, sp = cells[pb][tb]
            if n:
                emp = sw / n
                avg = sp / n
                mis = (emp - avg) * 100
                wsum += abs(mis) * n
                wcount += n
                row.append({"n": n, "mis": round(mis, 2), "emp": round(emp, 4), "price": round(avg, 4)})
            else:
                row.append({"n": 0, "mis": None, "emp": None, "price": None})
        grid.append(row)
    return {
        "window_len": None, "buckets": len(buckets), "observations": obs,
        "price_bins": PRICE_BINS, "time_bins": TIME_BINS,
        "rms_mispricing_pp": round(wsum / wcount, 2) if wcount else None,
        "grid": grid,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Win-probability / calibration surface.")
    ap.add_argument("--window-len", type=int, default=5)
    ap.add_argument("--min-cell", type=int, default=30, help="hide cells with fewer obs than this in the text view")
    ap.add_argument("--json", action="store_true", help="emit JSON only (for the UI/widget)")
    args = ap.parse_args()

    buckets = load_all(args.window_len)
    if not buckets:
        raise SystemExit(f"No {args.window_len}-min buckets in data/updown — collect first.")
    surf = build_surface(buckets)
    surf["window_len"] = args.window_len

    if args.json:
        print(json.dumps(surf))
        return 0

    print(f"WIN-PROBABILITY SURFACE — {args.window_len}-min buckets")
    print(f"{surf['buckets']} buckets · {surf['observations']:,} observations · "
          f"avg |mispricing| {surf['rms_mispricing_pp']}pp (≈0 = calibrated)")
    print("cell = empirical win-rate − price (pp): '+' wins MORE than priced, '-' less\n")
    cols = "  ".join(f"{int(t/TIME_BINS*100):>3}%" for t in range(TIME_BINS))
    print(f"price\\time  {cols}    (% of bucket elapsed →)")
    for pb in range(PRICE_BINS - 1, -1, -1):  # high price at top
        lo, hi = pb / PRICE_BINS, (pb + 1) / PRICE_BINS
        cells = []
        for tb in range(TIME_BINS):
            c = surf["grid"][pb][tb]
            if not c["n"] or c["n"] < args.min_cell:
                cells.append("   .")
            else:
                cells.append(f"{c['mis']:>+4.0f}")
        print(f"{lo:.1f}-{hi:.1f}   " + " ".join(cells))
    print("\n(‘.’ = too few observations. Read a price row left→right to see how a")
    print(" position at that price fares as the bucket runs out — your exit map.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
