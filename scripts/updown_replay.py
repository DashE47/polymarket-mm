r"""
Replay the high-precision Up/Down recordings (data/updown_hd) with EXACT fills, and
print the same threshold × entry-window grid as updown_analyze.py — but every entry
is now filled by walking the real ask ladder for your stake (true price + slippage),
against the real Down book, settled on the real resolved outcome.

Compare its grid to updown_analyze.py's to see exactly what honest execution costs.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_replay.py                       # 5-min, $1 stake
    .\.venv\Scripts\python.exe scripts\updown_replay.py --stake 5 --max-spread 0.05
    .\.venv\Scripts\python.exe scripts\updown_replay.py --detail 0.30,1       # per-bucket + equity for one rule
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT  # noqa: E402
from src.updown_replay import (  # noqa: E402
    FADE_THRESHOLDS, MOMENTUM_THRESHOLDS, FillCfg, load_recording, peek_meta, replay_bucket,
)

MIN_SAMPLE = 10


def block_bootstrap(bets: list[tuple[float, float]], n_iter: int = 5000, seed: int = 1):
    """Block-bootstrap the P&L/bet of one rule, resampling whole clock-windows.

    `bets` is [(window_key, pnl_per_stake), ...]. The 4 assets sharing one 5-min
    clock window are correlated (same underlying market move), so we resample
    WINDOWS with replacement, not individual bets — exactly the method that
    correctly flagged the fade's earlier +10pp as noise. Returns
    (obs_pnl_per_bet, lo5, hi95, p_le_zero, n_windows).
    """
    groups: dict[float, list[float]] = {}
    for wkey, pnl in bets:
        groups.setdefault(wkey, []).append(pnl)
    keys = list(groups.keys())
    k = len(keys)
    if not bets or k == 0:
        return 0.0, 0.0, 0.0, 1.0, 0
    obs = sum(p for _, p in bets) / len(bets)
    rng = random.Random(seed)
    vals = []
    le_zero = 0
    for _ in range(n_iter):
        num = cnt = 0
        for _ in range(k):
            for p in groups[keys[rng.randrange(k)]]:
                num += p
                cnt += 1
        v = num / cnt if cnt else 0.0
        vals.append(v)
        if v <= 0:
            le_zero += 1
    vals.sort()
    lo = vals[int(0.05 * n_iter)]
    hi = vals[int(0.95 * n_iter)]
    return obs, lo, hi, le_zero / n_iter, k


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Exact-fill replay of the HD Up/Down recordings.")
    ap.add_argument("--dir", default=str(PROJECT_ROOT / "data" / "updown_hd"))
    ap.add_argument("--window-len", type=int, default=5, help="market length to replay (min)")
    ap.add_argument("--stake", type=float, default=1.0, help="dollars deployed per bet")
    ap.add_argument("--max-spread", type=float, default=0.05, help="only fill if taken side's spread ≤ this")
    ap.add_argument("--latency-ms", type=float, default=0.0, help="react this many ms after the trigger")
    ap.add_argument("--min-fill-frac", type=float, default=0.0, help="require ≥ this fraction of stake to fill")
    ap.add_argument("--mode", choices=["fade", "momentum"], default="fade",
                    help="fade = buy the cheap side ≤ thr; momentum = buy the strong side ≥ thr")
    ap.add_argument("--stop-mid", type=float, default=None,
                    help="exit overlay: sell (into the real bid ladder) if the held side's mid ≤ this")
    ap.add_argument("--take-mid", type=float, default=None,
                    help="exit overlay: sell if the held side's mid ≥ this (take profit)")
    ap.add_argument("--detail", default="", help="'thr,win' → per-bucket fills + equity for that rule")
    ap.add_argument("--null", action="store_true",
                    help="block-bootstrap each rule's P&L/bet (resamples whole clock-windows) to "
                         "test whether it beats luck: 90%% band + P(pnl≤0)")
    ap.add_argument("--split", action="store_true",
                    help="out-of-sample: show each rule's pnl/bet on the 1st half vs 2nd half of "
                         "the recording period (chronological) — a real edge holds in BOTH")
    args = ap.parse_args()

    thresholds = MOMENTUM_THRESHOLDS if args.mode == "momentum" else FADE_THRESHOLDS
    windows_min = [max(1, round(args.window_len * f)) for f in (0.2, 0.4, 0.6, 0.8)]
    rules = [(thr, w) for thr in thresholds for w in windows_min]
    cfg = FillCfg(stake=args.stake, max_spread=args.max_spread,
                  latency_ms=args.latency_ms, min_fill_frac=args.min_fill_frac,
                  stop_mid=args.stop_mid, take_mid=args.take_mid)

    detail_rule = None
    if args.detail:
        p = args.detail.split(",")
        detail_rule = (float(p[0]), int(p[1]))

    files = sorted(Path(args.dir).glob("udx_*.jsonl*"))  # matches .jsonl and .jsonl.gz
    if not files:
        raise SystemExit(f"No recordings in {args.dir} — run updown_record.py first.")

    # Authoritative settled outcomes live in the sidecar built by updown_resolve.py
    # (keyed by conditionId) — real resolutions the recorder couldn't get in time.
    resolved_idx: dict[str, str] = {}
    idx_path = Path(args.dir) / "_resolved.json"
    if idx_path.exists():
        try:
            resolved_idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    agg = {r: {"n": 0, "wins": 0, "pnl": 0.0, "paid": 0.0, "frac": 0.0, "slip": 0.0,
               "entered": 0, "unsettled": 0, "exits": 0} for r in rules}
    bet_records: dict[tuple[float, int], list[tuple[str, float]]] = {r: [] for r in rules}
    src_count = {"gamma": 0, "last_mid_fallback": 0, "unresolved": 0}
    detail_rows = []
    used = 0

    for f in files:
        m0 = peek_meta(f)  # cheap window-length filter before the full decompress
        if not m0 or m0.get("window_min") != args.window_len:
            continue
        meta, events, resolution = load_recording(f)
        if not meta or not events:
            continue
        used += 1
        # sidecar wins: real settled outcome overrides the recorder's in-file guess
        sw = resolved_idx.get(meta.get("condition_id"))
        if sw:
            resolution = {"winner": sw, "source": "gamma"}
        src = (resolution or {}).get("source", "unresolved")
        src_count[src] = src_count.get(src, 0) + 1
        results = replay_bucket(meta, events, resolution, rules, cfg, mode=args.mode)
        for r in rules:
            res = results[r]
            if not res.get("entered"):
                continue
            a = agg[r]
            a["entered"] += 1
            if res.get("won") is None:
                a["unsettled"] += 1
                continue
            a["n"] += 1
            a["wins"] += 1 if res["won"] else 0
            a["pnl"] += res["pnl"]
            a["paid"] += res["avg"]
            a["frac"] += res["fill_frac"]
            a["slip"] += res["slippage"] or 0.0
            a["exits"] += 1 if res.get("exit") else 0
            # window_key = the shared clock window (end_ts) — assets resolving at the
            # same instant are correlated, so the bootstrap resamples by this, not per-bet.
            # Kept as a float (not str) so --split can sort bets chronologically too.
            bet_records[r].append((meta.get("end_ts") or 0.0, res["pnl"] / args.stake))
        if detail_rule is not None:
            res = results.get(detail_rule)
            if res and res.get("entered") and res.get("won") is not None:
                detail_rows.append((meta["end_ts"], meta["asset"], res))

    trig = "buy STRONG side ≥ thr (ride the move)" if args.mode == "momentum" else "buy CHEAP side ≤ thr (fade the dip)"
    print(f"Exact-fill replay [{args.mode.upper()}: {trig}] — {used} {args.window_len}-min recordings from {args.dir}")
    print(f"resolution source: {src_count}   (gamma = truly settled)")
    print(f"stake ${args.stake:g} · max_spread {args.max_spread} · latency {args.latency_ms:g}ms "
          f"· min_fill_frac {args.min_fill_frac:g}"
          + (f" · stop_mid {args.stop_mid}" if args.stop_mid is not None else "")
          + (f" · take_mid {args.take_mid}" if args.take_mid is not None else ""))

    if args.null:
        print(f"\nNULL TEST — block bootstrap (resample whole {args.window_len}-min clock-windows), 5000 iters")
        print("=" * 86)
        print(f"{'thr':>5} {'win':>4} {'bets':>5} {'windows':>8} {'pnl/bet':>8} "
              f"{'90% band':>18} {'P(pnl≤0)':>10}")
        print("-" * 86)
        null_rows = []
        for r in rules:
            bets = bet_records[r]
            if len(bets) < MIN_SAMPLE:
                continue
            obs, lo, hi, p0, kw = block_bootstrap(bets)
            null_rows.append((r[0], r[1], len(bets), kw, obs, lo, hi, p0))
        for thr, win, n, kw, obs, lo, hi, p0 in sorted(null_rows, key=lambda x: -x[4]):
            flag = "  ✓" if (lo > 0 and p0 < 0.05) else ""
            band = f"[{lo:+.3f},{hi:+.3f}]"
            print(f"{thr:>5.2f} {win:>4} {n:>5} {kw:>8} {obs:>+8.3f} {band:>18} {p0:>10.3f}{flag}")
        print("=" * 86)
        print("✓ = 90% band entirely above 0 AND P(pnl≤0) < 5%  → unlikely to be luck.")
        print("'windows' is the real sample size (4 assets/window are correlated, not independent).")
        return 0

    if args.split:
        # Chronological median split by clock-window (end_ts), so both halves are
        # real, distinct time periods — a genuine edge should hold in BOTH.
        all_windows = sorted({wk for r in rules for wk, _ in bet_records[r]})
        if len(all_windows) < 2:
            raise SystemExit("Not enough distinct clock-windows to split.")
        mid = all_windows[len(all_windows) // 2]
        print(f"\nOUT-OF-SAMPLE SPLIT — chronological median at window {mid:.0f}, "
              f"{len(all_windows)} distinct windows total")
        print("=" * 86)
        print(f"{'thr':>5} {'win':>4} | {'A bets':>7} {'A pnl/bet':>9} | {'B bets':>7} {'B pnl/bet':>9} | {'both?':>6}")
        print("-" * 86)
        split_rows = []
        for r in rules:
            bets = bet_records[r]
            a_bets = [p for wk, p in bets if wk < mid]
            b_bets = [p for wk, p in bets if wk >= mid]
            if len(a_bets) < MIN_SAMPLE or len(b_bets) < MIN_SAMPLE:
                continue
            pa, pb = sum(a_bets) / len(a_bets), sum(b_bets) / len(b_bets)
            split_rows.append((r[0], r[1], len(a_bets), pa, len(b_bets), pb))
        for thr, win, na, pa, nb, pb in sorted(split_rows, key=lambda x: -(x[3] + x[5])):
            both = "  ✓" if (pa > 0 and pb > 0) else ""
            print(f"{thr:>5.2f} {win:>4} | {na:>7} {pa:>+9.3f} | {nb:>7} {pb:>+9.3f} | {both:>6}")
        print("=" * 86)
        print("Read the two pnl/bet columns: a rule you'd trust is positive in BOTH halves (✓).")
        print("If it flips sign or collapses across the split, it's a fluke / one-regime effect.")
        return 0

    print("=" * 92)
    print(f"{'thr':>5} {'win':>4} {'bets':>5} {'fill%':>6} {'hit%':>6} {'paid%':>6} "
          f"{'slip¢':>6} {'exit%':>6} {'edge_pp':>8} {'P&L/bet':>8}")
    print("-" * 92)
    rows = []
    for r in rules:
        a = agg[r]
        n = a["n"]
        if n == 0:
            continue
        hit = a["wins"] / n * 100
        paid = a["paid"] / n * 100
        fillp = a["frac"] / n * 100
        slipc = a["slip"] / n * 100
        rows.append((r[0], r[1], n, fillp, hit, paid, slipc, a["exits"] / n * 100,
                     hit - paid, a["pnl"] / n))
    for thr, win, n, fillp, hit, paid, slipc, exitp, edge, pnlpb in sorted(rows, key=lambda x: -x[9]):
        flag = "  ← small" if n < MIN_SAMPLE else ("  ★" if pnlpb > 0.02 else "")
        print(f"{thr:>5.2f} {win:>4} {n:>5} {fillp:>5.0f}% {hit:>6.1f} {paid:>6.1f} "
              f"{slipc:>+6.1f} {exitp:>5.0f}% {edge:>+8.1f} {pnlpb:>+8.3f}{flag}")
    print("=" * 86)
    print("fill% = avg fraction of the stake actually filled · slip¢ = avg cost above the")
    print("touch from walking the ladder · edge/P&L now reflect EXACT execution + real")
    print("resolution. Compare to updown_analyze.py to see what honest fills cost.")

    if detail_rule is not None:
        print(f"\n--- per-bucket detail for dip ≤ {detail_rule[0]}, ≤ {detail_rule[1]}m "
              f"({len(detail_rows)} bets) ---")
        detail_rows.sort(key=lambda x: x[0])
        cum = 0.0
        print(f"{'asset':>9} {'side':>4} {'in@min':>7} {'avg':>6} {'fill%':>6} {'slip¢':>6} {'W/L':>4} {'pnl':>7} {'cum':>8}")
        for _end, asset, res in detail_rows:
            cum += res["pnl"]
            print(f"{asset:>9} {res['side']:>4} {res['elapsed']/60:>7.1f} {res['avg']:>6.3f} "
                  f"{res['fill_frac']*100:>5.0f}% {(res['slippage'] or 0)*100:>+6.1f} "
                  f"{'W' if res['won'] else 'L':>4} {res['pnl']:>+7.3f} {cum:>+8.2f}")
        if detail_rows:
            n = len(detail_rows)
            print(f"final cum P&L {cum:+.2f} over {n} bets ({cum/n:+.3f}/bet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
