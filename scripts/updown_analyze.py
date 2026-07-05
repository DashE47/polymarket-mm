r"""
Analyse collected Up/Down data (from updown_collect.py) to find which entry rule
— if any — has an edge. For a grid of (threshold × entry-window) it computes, over
all recorded buckets:
    triggered = a side dipped <= threshold within the first N minutes
    hit rate  = how often that side actually won
    edge      = hit rate − average price paid   (this is the whole game)
    P&L/bet   = expected $ per $1 bet at the prices you'd have gotten
Plus descriptives: base win rate, and how low / how early the chance usually dips.

A positive edge with a healthy sample is interesting; tiny-sample winners are
almost certainly luck. Confirm any candidate on FRESH data before believing it.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_analyze.py [path\to\updown_*.jsonl]
    (no path = newest file in data/updown)
"""

import argparse
import json
import random
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import PROJECT_ROOT  # noqa: E402

THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
MIN_SAMPLE = 10  # below this, treat results as noise


def load(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _bet_for_bucket(b, threshold, window_min, max_spread, fill_lag, min_size=0.0):
    """The (side, entry_price) this rule would take on ONE bucket, or None.

    Trigger uses the MID chance (what you observe). Entry COST is the real price
    you'd pay to BUY that side — the ASK (Up→Up's ask, Down→1−Up's bid).

    TRADEABILITY FILTER: an entry only counts if, at the FILL moment, the Up book
    was two-sided with a quoted spread ≤ `max_spread` (rejects one-sided / very
    wide books). (Old mid-only data has no book; falls back to mid.)

    FILLABILITY FILTER (`min_size`): require at least `min_size` shares resting on
    the side you'd actually take — Up-fade buys Up's ASK (needs ask size), Down-fade
    buys Down ≈ sells into Up's BID (needs bid size). This rejects tight-but-EMPTY
    quotes (a 1-share order making the price look real). Needs size in the data
    (new collector records [t,mid,bid,ask,bid_sz,ask_sz]); older rows without size
    can't be confirmed fillable, so they're rejected when min_size > 0.

    FILL LAG: the dip TRIGGERS at the tick where the chance first hits the
    threshold, but you can't react instantly. With `fill_lag` > 0 we fill at the
    first sample ≥ `fill_lag` seconds AFTER the trigger — at whatever price the
    book shows then. If a "cheap" dip is just a stale/blink quote, a lag of one
    poll (~12-24s) makes the price snap back and the apparent edge collapses. The
    side is locked at the trigger; if the price recovered by fill time you simply
    pay more (correctly penalising chasing a blip). No later sample → no fill.
    """
    cutoff = window_min * 60
    samples = b["samples"]
    early = [s for s in samples if s[0] <= cutoff]
    if not early:
        return None  # no early coverage → can't evaluate this rule on this bucket
    for s in early:
        mid = s[1]
        low = min(mid, 1 - mid)
        if low > threshold:
            continue
        side = "Up" if mid <= 0.5 else "Down"
        fill = s
        if fill_lag > 0:  # trade at the price one+ poll later, not the blink
            later = [x for x in samples if x[0] >= s[0] + fill_lag]
            if not later:
                continue  # bucket ended before we could react → no fill
            fill = later[0]
        if len(fill) > 3:  # have bid/ask → enforce tradeability at FILL time
            bid, ask = fill[2], fill[3]
            if bid is None or ask is None or (ask - bid) > max_spread:
                continue  # one-sided / too-wide book → not a real entry
            cost = ask if side == "Up" else (1 - bid)
            if min_size > 0:  # require enough resting size to actually fill
                if len(fill) <= 5:
                    continue  # no size recorded → can't confirm fillable → reject
                bid_sz, ask_sz = fill[4], fill[5]
                avail = ask_sz if side == "Up" else bid_sz  # the side we take
                if avail is None or avail < min_size:
                    continue  # tight but too thin → not really fillable
        else:
            if min_size > 0:
                continue  # mid-only data, no book/size → can't confirm fillable
            cost = min(fill[1], 1 - fill[1])  # old data: no book to check
        return side, min(max(cost, 0.001), 0.999)
    return None


def evaluate(buckets, threshold, window_min, max_spread, fill_lag=0.0,
             side_filter=None, min_size=0.0):
    """Return (n_triggered, wins, sum_pnl, sum_cost) for one rule."""
    n = wins = 0
    pnl = cost_sum = 0.0
    for b in buckets:
        bet = _bet_for_bucket(b, threshold, window_min, max_spread, fill_lag, min_size)
        if not bet:
            continue
        side, price = bet
        if side_filter and side != side_filter:
            continue  # only counting one side's fades (Up-fades vs Down-fades)
        n += 1
        cost_sum += price
        if side == b["winner"]:
            wins += 1
            pnl += (1 - price) / price
        else:
            pnl -= 1
    return n, wins, pnl, cost_sum


def collect_bets(buckets, threshold, window_min, max_spread, fill_lag, min_size=0.0):
    """Per-bet records for the null test: list of (window_key, won, price).

    `window_key` groups the (up to 4) assets that share one clock window, so the
    bootstrap can resample whole windows and respect that those assets move
    together (they are NOT 4 independent bets).
    """
    out = []
    for b in buckets:
        bet = _bet_for_bucket(b, threshold, window_min, max_spread, fill_lag, min_size)
        if not bet:
            continue
        side, price = bet
        won = side == b["winner"]
        out.append((b.get("end", b.get("cond", "")), won, price))
    return out


def block_bootstrap(bets, n_iter=5000, seed=1):
    """Block bootstrap of a rule's edge, resampling whole time-windows.

    edge = hit% − avg price paid. We group bets by their 5-min window and resample
    those GROUPS with replacement (not individual bets), because the 4 assets in a
    window are correlated — treating them as independent would fake-narrow the
    result. Returns (obs_edge, lo5, hi95, p_le_zero, n_windows): the observed edge,
    a 90% confidence band, the fraction of resamples where the edge was ≤ 0 (our
    "could this just be zero?" gauge), and how many independent windows there were.
    """
    groups: dict[str, list] = {}
    for wkey, won, price in bets:
        groups.setdefault(wkey, []).append((won, price))
    keys = list(groups.keys())
    k = len(keys)
    if not bets or k == 0:
        return 0.0, 0.0, 0.0, 1.0, 0
    obs = sum((1.0 if w else 0.0) - p for _, w, p in bets) / len(bets)
    rng = random.Random(seed)
    edges = []
    le_zero = 0
    for _ in range(n_iter):
        num = 0.0
        cnt = 0
        for _ in range(k):  # resample k windows with replacement
            for won, price in groups[keys[rng.randrange(k)]]:
                num += (1.0 if won else 0.0) - price
                cnt += 1
        e = num / cnt if cnt else 0.0
        edges.append(e)
        if e <= 0:
            le_zero += 1
    edges.sort()
    lo = edges[int(0.05 * n_iter)]
    hi = edges[int(0.95 * n_iter)]
    return obs, lo, hi, le_zero / n_iter, k


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # avoid cp1255 crashes
    ap = argparse.ArgumentParser(description="Analyse Up/Down data.")
    ap.add_argument("path", nargs="?", help="data file (default: newest in data/updown)")
    ap.add_argument("--max-spread", type=float, default=0.05,
                    help="only count an entry if the quoted spread ≤ this (tradeability filter)")
    ap.add_argument("--fill-lag", type=float, default=0.0,
                    help="seconds to wait after the dip before filling (tests stale/blink prices)")
    ap.add_argument("--split", action="store_true",
                    help="train/test: show each rule's edge on the 1st half vs 2nd half of data "
                         "(an edge that's real should appear in BOTH; overfitting won't)")
    ap.add_argument("--by-side", action="store_true",
                    help="split each rule's edge into Up-fades vs Down-fades (an edge in only ONE "
                         "side is probably this period's directional drift, not a real signal)")
    ap.add_argument("--null", action="store_true",
                    help="block-bootstrap each rule's edge (resamples whole 5-min windows) to test "
                         "whether it beats luck: shows a 90%% confidence band + P(edge≤0)")
    ap.add_argument("--by-asset", action="store_true",
                    help="break the first-minute edge down per coin (Bitcoin/Ethereum/Solana/XRP) — "
                         "an edge in ALL coins is replication; an edge in only one is likely noise")
    ap.add_argument("--window-len", type=int, default=5,
                    help="which market length to analyse, in minutes (5, 15 or 60)")
    ap.add_argument("--min-size", type=float, default=0.0,
                    help="fillability: require ≥ this many shares resting on the side you'd take "
                         "(needs size in the data — new collector only; 0 = off)")
    args = ap.parse_args()
    if args.path:
        path = Path(args.path)
    else:
        files = sorted((PROJECT_ROOT / "data" / "updown").glob("updown_*.jsonl"))
        if not files:
            raise SystemExit("No data files in data/updown — run updown_collect.py first.")
        path = files[-1]
    max_spread = args.max_spread
    fill_lag = args.fill_lag
    min_size = args.min_size
    window_len = args.window_len
    # Entry windows scale with the bucket: "first 20/40/60/80% of the bucket", so
    # the rules stay comparable across 5/15/60-min markets (5→[1,2,3,4] min).
    windows_min = [max(1, int(round(window_len * f))) for f in (0.2, 0.4, 0.6, 0.8)]

    allb = load(path)
    if not allb:
        raise SystemExit(f"{path} is empty.")
    # Only analyse buckets of the chosen cadence — timing (and the entry window) is
    # only comparable within one length. (Older data without dur_s is skipped.)
    target_s = window_len * 60
    buckets = [b for b in allb if abs(b.get("dur_s", 0) - target_s) <= 60]
    if not buckets:
        raise SystemExit(f"{path}: {len(allb)} buckets, but none are {window_len}-min "
                         f"(need dur_s ~{target_s}). Try a different --window-len.")

    # --- descriptives -----------------------------------------------------
    by_asset: dict[str, int] = {}
    up_wins = 0
    lows, low_mins = [], []
    for b in buckets:
        by_asset[b["asset"]] = by_asset.get(b["asset"], 0) + 1
        if b["winner"] == "Up":
            up_wins += 1
        if b["samples"]:
            low = min(min(s[1], 1 - s[1]) for s in b["samples"])
            lows.append(low)
            t_at_low = min(b["samples"], key=lambda s: min(s[1], 1 - s[1]))[0]
            low_mins.append(t_at_low / 60)

    print(f"Data: {path.name}")
    print(f"{window_len}-min buckets: {len(buckets)} of {len(allb)} recorded  ({by_asset})")
    if min_size > 0:
        print(f"fillability filter: only entries with ≥ {min_size:g} shares on the taken side")
    print(f"base 'Up' win rate: {up_wins / len(buckets):.1%}  (≈50% expected for a fair coin)")
    if lows:
        lows.sort()
        print(f"lowest chance reached per bucket — median {median(lows):.2f}, "
              f"10th pct {lows[len(lows) // 10]:.2f}, min {lows[0]:.2f}")
        print(f"timing of that low — median {median(low_mins):.1f} min into the bucket")

    # --- out-of-sample split (the real overfitting test) ------------------
    # buckets are in chronological (file append) order, so the first half and
    # second half are two different time periods. A genuine edge shows up in
    # BOTH; an overfit / regime-specific fluke shows up in one and dies in the
    # other. We print every rule's edge_pp + bets for each half, side by side.
    if args.split:
        mid_i = len(buckets) // 2
        half1, half2 = buckets[:mid_i], buckets[mid_i:]
        print(f"\nOUT-OF-SAMPLE SPLIT — 1st half ({len(half1)} buckets) vs 2nd half ({len(half2)})")
        print(f"tradeability spread ≤ {max_spread:.2f}"
              + (f", fill lag {fill_lag:.0f}s" if fill_lag > 0 else ""))
        print("=" * 78)
        print(f"{'thr':>5} {'win(min)':>9} | {'A bets':>7} {'A edge':>7} | {'B bets':>7} {'B edge':>7} | {'both?':>6}")
        print("-" * 78)
        for thr in THRESHOLDS:
            for w in windows_min:
                n1, wins1, _, e1 = evaluate(half1, thr, w, max_spread, fill_lag, min_size=min_size)
                n2, wins2, _, e2 = evaluate(half2, thr, w, max_spread, fill_lag, min_size=min_size)
                if n1 < MIN_SAMPLE or n2 < MIN_SAMPLE:
                    continue  # need a real sample in BOTH halves to compare
                edge1 = (wins1 / n1 - e1 / n1) * 100
                edge2 = (wins2 / n2 - e2 / n2) * 100
                both = "  ✓" if (edge1 > 2 and edge2 > 2) else ""
                print(f"{thr:>5.2f} {w:>9} | {n1:>7} {edge1:>+7.1f} | {n2:>7} {edge2:>+7.1f} | {both:>6}")
        print("=" * 78)
        print("Read the two edge columns: a rule you'd trust is positive in BOTH halves")
        print("(✓). If big edges flip sign or collapse across the split, it was a fluke /")
        print("a one-regime effect — not something to bet real money on.")
        return 0

    # --- by-side breakdown (drift vs real-reversion test) -----------------
    # The fade bets whichever side is the underdog. If the market drifted one way
    # this period (base Up rate ≠ 50%), the strategy ends up mostly long the other
    # side and can show a fake "edge" that's really just that drift. Splitting the
    # SAME bets into Up-fades vs Down-fades tells them apart: a real reversion edge
    # shows up on BOTH sides; a drift artifact lives in only one.
    if args.by_side:
        print(f"\nBY-SIDE — Up-fades vs Down-fades (base 'Up' win rate {up_wins / len(buckets):.1%})")
        print(f"tradeability spread ≤ {max_spread:.2f}"
              + (f", fill lag {fill_lag:.0f}s" if fill_lag > 0 else ""))
        print("=" * 78)
        print(f"{'thr':>5} {'win(min)':>9} | {'Up bets':>7} {'Up edge':>8} | {'Dn bets':>7} {'Dn edge':>8} | {'both?':>6}")
        print("-" * 78)
        for thr in THRESHOLDS:
            for w in windows_min:
                nu, wu, _, eu = evaluate(buckets, thr, w, max_spread, fill_lag, "Up", min_size)
                nd, wd, _, ed = evaluate(buckets, thr, w, max_spread, fill_lag, "Down", min_size)
                if nu < MIN_SAMPLE or nd < MIN_SAMPLE:
                    continue  # need a real sample on BOTH sides to compare
                edge_u = (wu / nu - eu / nu) * 100
                edge_d = (wd / nd - ed / nd) * 100
                both = "  ✓" if (edge_u > 2 and edge_d > 2) else ""
                print(f"{thr:>5.2f} {w:>9} | {nu:>7} {edge_u:>+8.1f} | {nd:>7} {edge_d:>+8.1f} | {both:>6}")
        print("=" * 78)
        print("If the edge sits on BOTH sides (✓), it looks like a genuine reversion")
        print("effect. If it's strong on only ONE side, it's most likely just this")
        print("period's price drift — and it will flip if the market trends the other way.")
        return 0

    # --- null / block-bootstrap test (does the edge beat luck?) -----------
    # For every rule we resample whole 5-min windows with replacement and recompute
    # the edge thousands of times. The spread of those resamples is the honest
    # uncertainty (it accounts for the 4-assets-move-together correlation, which a
    # naive per-bet test would ignore). P(edge≤0) ≈ "chance the true edge is really
    # zero/negative". Small P + a 90% band clear of 0 = the edge is unlikely to be
    # luck. (Caveat: this does NOT correct for having scanned many cells, nor for
    # this being one market regime — out-of-sample on more days is the final word.)
    if args.null:
        print(f"\nNULL TEST — block bootstrap (resample whole {window_len}-min windows), 5000 iters")
        print(f"tradeability spread ≤ {max_spread:.2f}"
              + (f", fill lag {fill_lag:.0f}s" if fill_lag > 0 else "")
              + (f", min size {min_size:g}" if min_size > 0 else ""))
        print("=" * 78)
        print(f"{'thr':>5} {'win(min)':>9} {'bets':>5} {'windows':>8} {'edge_pp':>8} "
              f"{'90% band':>16} {'P(edge≤0)':>10}")
        print("-" * 78)
        for w in windows_min:  # group output by entry window; the earliest is the signal
            for thr in THRESHOLDS:
                bets = collect_bets(buckets, thr, w, max_spread, fill_lag, min_size)
                if len(bets) < MIN_SAMPLE:
                    continue
                obs, lo, hi, p0, kw = block_bootstrap(bets)
                flag = "  ✓" if (lo > 0 and p0 < 0.05) else ""
                band = f"[{lo * 100:+.1f},{hi * 100:+.1f}]"
                print(f"{thr:>5.2f} {w:>9} {len(bets):>5} {kw:>8} {obs * 100:>+8.1f} "
                      f"{band:>16} {p0:>10.3f}{flag}")
            print("-" * 78)
        print("✓ = 90% band entirely above 0 AND P(edge≤0) < 5%  → unlikely to be luck.")
        print("Note 'windows' << 'bets': the 4 assets in a window aren't independent, so")
        print("the real sample is the window count. This test handles sampling + that")
        print("correlation, but NOT multiple-cell search or single-regime risk — only")
        print("fresh out-of-sample data (more days, incl. an up-trending one) settles those.")
        return 0

    # --- by-asset breakdown (replication across coins) --------------------
    # Pooling 4 coins hides whether the edge is broad or driven by one coin. Per
    # coin there's ~1 bucket per 5-min window, so each coin's bets are ~independent
    # — 4 coins all positive = genuine 4-way replication; an edge in only one coin
    # is most likely noise. We focus on the first-minute window (the live signal).
    if args.by_asset:
        assets = sorted({b["asset"] for b in buckets})
        w = windows_min[0]  # the earliest entry window is where the signal lives
        print(f"\nBY-ASSET — earliest-window (win={w}min) edge per coin")
        print(f"tradeability spread ≤ {max_spread:.2f}"
              + (f", fill lag {fill_lag:.0f}s" if fill_lag > 0 else "")
              + (f", min size {min_size:g}" if min_size > 0 else ""))
        print("=" * 78)
        print("base 'Up' win rate by coin (checks if drift differed across coins):")
        for a in assets:
            ab = [b for b in buckets if b["asset"] == a]
            uw = sum(1 for b in ab if b["winner"] == "Up")
            print(f"   {a:>9}: {uw / len(ab):4.1%}   ({len(ab)} buckets)")
        print("\nedge_pp by threshold   [bets]")
        print("-" * 78)
        print(f"{'thr':>5} |" + "".join(f"{a:>17}" for a in assets))
        print("-" * 78)
        for thr in THRESHOLDS:
            cells = []
            for a in assets:
                ab = [b for b in buckets if b["asset"] == a]
                n, wins, _, esum = evaluate(ab, thr, w, max_spread, fill_lag, min_size=min_size)
                if n == 0:
                    cells.append(f"{'--':>17}")
                else:
                    edge = (wins / n - esum / n) * 100
                    cells.append(f"{f'{edge:+.1f} [{n}]':>17}")
            print(f"{thr:>5.2f} |" + "".join(cells))
        print("=" * 78)
        print("Per coin the windows are ~independent (1 bucket each), so all 4 coins")
        print("positive = 4-way replication (convincing). Edge in only 1 coin = likely")
        print("noise / that coin's drift. Watch the bet counts — per coin they're small.")
        return 0

    # --- strategy grid ----------------------------------------------------
    print(f"\ntradeability filter: only entries with quoted spread ≤ {max_spread:.2f} count")
    if fill_lag > 0:
        print(f"fill lag: trade at the price ≥ {fill_lag:.0f}s after the dip (not the blink)")
    if min_size > 0:
        print(f"fillability: only entries with ≥ {min_size:g} shares on the taken side count")
    print("=" * 78)
    print(f"{'thr':>5} {'win(min)':>9} {'bets':>5} {'hit%':>6} {'paid%':>6} {'edge_pp':>8} {'P&L/bet':>8}")
    print("-" * 78)
    rows = []
    for thr in THRESHOLDS:
        for w in windows_min:
            n, wins, pnl, esum = evaluate(buckets, thr, w, max_spread, fill_lag, min_size=min_size)
            if n == 0:
                continue
            hit = wins / n
            paid = esum / n
            edge = (hit - paid) * 100
            row = (thr, w, n, hit * 100, paid * 100, edge, pnl / n)
            rows.append(row)
    for thr, w, n, hit, paid, edge, pnlpb in sorted(rows, key=lambda r: -r[5]):
        flag = "  ← sample too small" if n < MIN_SAMPLE else ("  ★" if edge > 2 else "")
        print(f"{thr:>5.2f} {w:>9} {n:>5} {hit:>6.1f} {paid:>6.1f} {edge:>+8.1f} {pnlpb:>+8.3f}{flag}")

    print("=" * 78)
    good = [r for r in rows if r[2] >= MIN_SAMPLE]
    if good:
        best = max(good, key=lambda r: r[5])
        print(f"Best (n≥{MIN_SAMPLE}): threshold {best[0]:.2f}, first {best[1]} min → "
              f"edge {best[5]:+.1f}pp, P&L {best[6]:+.3f}/bet over {best[2]} bets.")
        print("Edge ≈ 0 means the market is calibrated (no free money). A clearly")
        print("positive edge is only believable if it HOLDS on fresh data — collect more,")
        print("then re-run; don't trust a single sample (that's overfitting).")
    else:
        print(f"No rule reached {MIN_SAMPLE}+ bets yet — collect more data and re-run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
