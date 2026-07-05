r"""
FULL report over the high-precision recordings — reads the replay cache (built by
updown_prewarm.py / the web Replay button) and the settled-outcome sidecar, and
prints the complete analysis with zero re-parsing of the 16GB of ticks:

  * dataset summary
  * per market length (5/15/60 min), per strategy (momentum + fade):
      - the exact-fill edge grid (threshold × entry window)
      - block-bootstrap null test on the momentum grid (does it beat luck?)
      - out-of-sample chronological split (does it hold across the period?)

Everything is execution-exact (real ask-ladder fills) and settled on the real
Gamma outcomes. SIMULATION ONLY.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_hd_report.py            # latency-0 cache
    .\.venv\Scripts\python.exe scripts\updown_hd_report.py --latency-ms 300
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling CLI for block_bootstrap

from api.hd import _cache_path, _finished, _phash, _recordings, _sidecar  # noqa: E402
from src.updown_replay import FADE_THRESHOLDS, MOMENTUM_THRESHOLDS, entry_windows  # noqa: E402
from updown_replay import block_bootstrap  # noqa: E402

MIN_SAMPLE = 10


def _load_entries(window_len: int, phash: str) -> list[dict]:
    """Cached per-bucket results for finished `window_len` recordings, deduped by cid."""
    by_cid: dict[str, dict] = {}
    for p, m in _recordings():
        if m["window_min"] != window_len or not _finished(m):
            continue
        cp = _cache_path(p, phash)
        if not cp.exists():
            continue
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        prev = by_cid.get(data["cid"])
        if prev is None or data.get("n_events", 0) > prev.get("n_events", 0):
            by_cid[data["cid"]] = data
    return list(by_cid.values())


def _aggregate(entries, winners, mode, stake):
    """Return (agg per rule-key, bets per rule-key) joining entries with settled winners."""
    agg: dict[str, dict] = {}
    bets: dict[str, list] = {}
    for e in entries:
        win_side = winners.get(e["cid"])
        for key, r in e["modes"].get(mode, {}).items():
            a = agg.setdefault(key, {"entered": 0, "n": 0, "wins": 0, "pnl": 0.0,
                                     "paid": 0.0, "fill": 0.0, "slip": 0.0})
            if not r:
                continue
            a["entered"] += 1
            if not win_side:
                continue
            won = r["side"] == win_side
            pnl = (r["shares"] - r["spent"]) if won else -r["spent"]
            a["n"] += 1
            a["wins"] += 1 if won else 0
            a["pnl"] += pnl
            a["paid"] += r["avg"]
            a["fill"] += r["fill_frac"]
            a["slip"] += r["slippage"] or 0.0
            bets.setdefault(key, []).append((e["end_ts"] or 0.0, pnl / stake))
    return agg, bets


def _print_grid(agg, thresholds, windows, mode, stake):
    rows = []
    for thr in thresholds:
        for w in windows:
            a = agg.get(f"{thr:.2f}|{w}")
            if not a or a["n"] == 0:
                continue
            n = a["n"]
            hit, paid = a["wins"] / n * 100, a["paid"] / n * 100
            rows.append((thr, w, n, hit, paid, hit - paid, a["pnl"] / n / stake,
                         a["fill"] / n * 100, a["slip"] / n * 100))
    print(f"  {'thr':>5} {'win':>4} {'bets':>5} {'hit%':>6} {'paid%':>6} {'edge_pp':>8} {'¢/bet':>7} {'fill%':>6} {'slip¢':>6}")
    for thr, w, n, hit, paid, edge, pnl, fill, slip in sorted(rows, key=lambda x: -x[5]):
        flag = "  ← small" if n < MIN_SAMPLE else ("  ★" if edge > 2 else "")
        print(f"  {thr:>5.2f} {w:>4} {n:>5} {hit:>6.1f} {paid:>6.1f} {edge:>+8.1f} "
              f"{pnl * 100:>+7.1f} {fill:>5.0f}% {slip * 100:>+6.1f}{flag}")


def _print_null(bets):
    print(f"  {'thr':>5} {'win':>4} {'bets':>5} {'windows':>8} {'¢/bet':>7} {'90% band (¢)':>18} {'P(≤0)':>7}")
    out = []
    for key, b in bets.items():
        if len(b) < MIN_SAMPLE:
            continue
        obs, lo, hi, p0, kw = block_bootstrap(b, n_iter=3000)
        out.append((key, len(b), kw, obs, lo, hi, p0))
    for key, n, kw, obs, lo, hi, p0 in sorted(out, key=lambda x: -x[3])[:10]:
        thr, w = key.split("|")
        flag = "  ✓" if (lo > 0 and p0 < 0.05) else ""
        print(f"  {float(thr):>5.2f} {w:>4} {n:>5} {kw:>8} {obs * 100:>+7.1f} "
              f"[{lo * 100:>+5.1f},{hi * 100:>+5.1f}] {p0:>7.3f}{flag}")


def _print_split(bets):
    all_w = sorted({wk for b in bets.values() for wk, _ in b})
    if len(all_w) < 2:
        print("  (not enough windows to split)")
        return
    mid = all_w[len(all_w) // 2]
    print(f"  split at window {mid:.0f} ({len(all_w)} distinct windows)")
    print(f"  {'thr':>5} {'win':>4} | {'A n':>5} {'A ¢/bet':>8} | {'B n':>5} {'B ¢/bet':>8} | both?")
    out = []
    for key, b in bets.items():
        a = [p for wk, p in b if wk < mid]
        c = [p for wk, p in b if wk >= mid]
        if len(a) < MIN_SAMPLE or len(c) < MIN_SAMPLE:
            continue
        pa, pc = sum(a) / len(a), sum(c) / len(c)
        out.append((key, len(a), pa, len(c), pc))
    for key, na, pa, nc, pc in sorted(out, key=lambda x: -(x[2] + x[4]))[:10]:
        thr, w = key.split("|")
        both = "  ✓" if (pa > 0 and pc > 0) else ""
        print(f"  {float(thr):>5.2f} {w:>4} | {na:>5} {pa * 100:>+8.1f} | {nc:>5} {pc * 100:>+8.1f} |{both}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Full report over the HD recordings (from cache).")
    ap.add_argument("--stake", type=float, default=1.0)
    ap.add_argument("--max-spread", type=float, default=0.05)
    ap.add_argument("--latency-ms", type=float, default=0.0)
    ap.add_argument("--min-fill-frac", type=float, default=0.0)
    ap.add_argument("--windows", default="5,15,60", help="market lengths to report")
    args = ap.parse_args()

    phash = _phash(args.stake, args.max_spread, args.latency_ms, args.min_fill_frac)
    winners = _sidecar()
    recs = _recordings()

    # --- dataset summary ---
    byw: dict[int, int] = {}
    bya: dict[str, int] = {}
    ends = []
    resolved = 0
    for _p, m in recs:
        byw[m["window_min"]] = byw.get(m["window_min"], 0) + 1
        bya[m["asset"]] = bya.get(m["asset"], 0) + 1
        if m["end_ts"]:
            ends.append(m["end_ts"])
        if m["cid"] in winners:
            resolved += 1
    ends.sort()
    print("=" * 92)
    print("HIGH-PRECISION Up/Down — FULL REPORT (execution-exact fills, real settlement)")
    print("=" * 92)
    print(f"recordings: {len(recs)}  ·  by window {dict(sorted(byw.items()))}  ·  assets {bya}")
    print(f"settled: {resolved}  ·  unresolved: {len(recs) - resolved}")
    if ends:
        span = (ends[-1] - ends[0]) / 3600
        print(f"span: {datetime.fromtimestamp(ends[0], timezone.utc):%Y-%m-%d %H:%M} → "
              f"{datetime.fromtimestamp(ends[-1], timezone.utc):%Y-%m-%d %H:%M} UTC ({span:.1f} h)")
    print(f"exec params: stake ${args.stake:g} · max_spread {args.max_spread} · "
          f"latency {args.latency_ms:g}ms · min_fill {args.min_fill_frac:g}")

    up_base = sum(1 for c, w in winners.items() if w == "Up")
    if winners:
        print(f"base resolution: Up {up_base / len(winners):.1%} / Down {1 - up_base / len(winners):.1%} "
              f"(across {len(winners)} settled markets)")

    for wl in [int(x) for x in args.windows.split(",") if x.strip()]:
        entries = _load_entries(wl, phash)
        settled = sum(1 for e in entries if e["cid"] in winners)
        print("\n" + "=" * 92)
        print(f"{wl}-MIN MARKETS — {len(entries)} recordings ({settled} settled)")
        print("=" * 92)
        if not entries:
            print("  (no cached recordings for this length)")
            continue
        for mode, ths in (("momentum", MOMENTUM_THRESHOLDS), ("fade", FADE_THRESHOLDS)):
            agg, bets = _aggregate(entries, winners, mode, args.stake)
            label = "MOMENTUM (buy strong side ≥ thr)" if mode == "momentum" else "FADE (buy cheap side ≤ thr)"
            print(f"\n[{wl}m] {label} — edge grid")
            _print_grid(agg, ths, entry_windows(wl), mode, args.stake)
            if mode == "momentum":
                print(f"\n[{wl}m] momentum — NULL TEST (block bootstrap, top by ¢/bet)")
                _print_null(bets)
                print(f"\n[{wl}m] momentum — OUT-OF-SAMPLE SPLIT (top by ¢/bet)")
                _print_split(bets)
    print("\n" + "=" * 92)
    print("¢/bet = profit per $1 staked, in cents · ★ = edge > 2pp · ✓ = passes that test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
