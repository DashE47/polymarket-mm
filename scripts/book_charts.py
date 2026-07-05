r"""
Generate all figures + a stats.json for the statistics mini-book, from REAL data:
the replay cache (exact-fill entries), the settled-outcome sidecar, and one raw
60-min recording (for the price-path and order-book figures).

Output: reports/book_figs/*.png + reports/book_figs/stats.json
Run:    .\.venv\Scripts\python.exe scripts\book_charts.py
"""

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import PROJECT_ROOT  # noqa: E402
from src.orderbook import LocalOrderBook  # noqa: E402
from src.updown_replay import _apply, load_recording, peek_meta  # noqa: E402

HD = PROJECT_ROOT / "data" / "updown_hd"
CACHE = HD / "_replay_cache"
PHASH = "64348b0def"  # default exec params: $1, spread<=0.05, latency 0, no min-fill
OUT = PROJECT_ROOT / "reports" / "book_figs"
OUT.mkdir(parents=True, exist_ok=True)

GREEN, RED, BLUE, GRAY, AMBER = "#1fa05a", "#d6453f", "#378add", "#8a8a8a", "#d9a514"
plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.size": 10.5,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "figure.facecolor": "white"})

STATS: dict = {}


def load_cache():
    winners = json.loads((HD / "_resolved.json").read_text(encoding="utf-8"))
    by_cid = {}
    for f in CACHE.glob(f"*.{PHASH}.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        prev = by_cid.get(d["cid"])
        if prev is None or d.get("n_events", 0) > prev.get("n_events", 0):
            by_cid[d["cid"]] = d
    return list(by_cid.values()), winners


def bets_for(entries, winners, window, mode, key):
    """[(end_ts, paid, won, pnl_per_$1)] for one rule, settled buckets only."""
    out = []
    for e in entries:
        if e["window_min"] != window:
            continue
        w = winners.get(e["cid"])
        r = e["modes"].get(mode, {}).get(key)
        if not w or not r:
            continue
        won = r["side"] == w
        pnl = (r["shares"] - r["spent"]) if won else -r["spent"]
        out.append((e["end_ts"] or 0.0, r["avg"], won, pnl / 1.0))
    out.sort(key=lambda x: x[0])
    return out


def savefig(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def fig_price_path_and_book(entries, winners):
    """F1: one real 60-min bucket's price path. F2: its order book mid-flight."""
    # pick a settled 60-min recording with a dramatic, momentum-triggering path
    pick = None
    for p in sorted(HD.glob("udx_*.jsonl*")):
        m = peek_meta(p)
        if not m or m.get("window_min") != 60 or m.get("condition_id") not in winners:
            continue
        pick = (p, m)
        meta, events, _ = load_recording(p)
        up = meta["up_token"]
        books = {up: LocalOrderBook(up), meta["down_token"]: LocalOrderBook(meta["down_token"])}
        path, snap = [], None
        for e in events:
            _apply(e["ev"], books)
            mid = books[up].midpoint
            t_min = (e["recv_ms"] / 1000.0 - meta["start_ts"]) / 60.0
            if mid is not None and 0 <= t_min <= 60:
                path.append((t_min, mid))
            if snap is None and t_min >= 30 and books[up].best_bid and books[up].best_ask:
                snap = (books[up].bid_levels(8), books[up].ask_levels(8), books[up].midpoint, t_min)
        if (len(path) > 300 and snap and path[0][0] < 6
                and (max(x[1] for x in path) - min(x[1] for x in path)) > 0.3):
            break
        pick = None
    if pick is None:
        raise SystemExit("no suitable 60m recording found")
    p, m = pick
    winner = winners[m["condition_id"]]
    xs, ys = zip(*path)
    STATS["path"] = {"asset": m["asset"], "winner": winner, "question": m.get("question", "")}

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.plot(xs, ys, color=BLUE, lw=1.2)
    ax.axhline(0.5, color=GRAY, ls="--", lw=0.8)
    ax.axhline(1.0 if winner == "Up" else 0.0, color=GREEN, ls=":", lw=1.2)
    ax.annotate(f"resolves: {winner} wins", xy=(60, 1.0 if winner == "Up" else 0.0),
                xytext=(40, 0.88 if winner == "Up" else 0.12), color=GREEN, fontsize=10,
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=1))
    ax.set_xlabel("minutes into the market")
    ax.set_ylabel('price of "Up" (= its probability)')
    ax.set_ylim(-0.03, 1.03)
    ax.set_title(f'{m["asset"]} 60-minute Up/Down — one real market, tick by tick', fontsize=11)
    savefig(fig, "f1_price_path.png")

    bids, asks, mid, tmin = snap
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    bp = [b[0] for b in bids]; bs = [b[1] for b in bids]
    ap = [a[0] for a in asks]; asz = [a[1] for a in asks]
    ax.barh(bp, [-s for s in bs], height=0.007, color=GREEN, alpha=0.85, label="bids (buyers waiting)")
    ax.barh(ap, asz, height=0.007, color=RED, alpha=0.85, label="asks (sellers waiting)")
    ax.axhline(mid, color=BLUE, ls="--", lw=1)
    ax.annotate(f"mid = {mid:.3f}", xy=(0, mid), xytext=(max(asz) * 0.45, mid + 0.012),
                color=BLUE, fontsize=10)
    ax.set_xlabel("shares waiting at each price   (left = bids, right = asks)")
    ax.set_ylabel("price")
    ax.legend(loc="lower right", frameon=False)
    ax.set_title(f'The live order book of that market, {tmin:.0f} minutes in', fontsize=11)
    STATS["book"] = {"best_bid": bp[0], "best_ask": ap[0], "spread": round(ap[0] - bp[0], 3),
                     "bid_size": round(bs[0], 1), "ask_size": round(asz[0], 1)}
    savefig(fig, "f2_orderbook.png")


def fig_payout():
    """F3: the payout asymmetry of a cheap share (worked EV example)."""
    price, hit = 0.259, 0.283  # 5-min fade 0.30/1min cell from the old study (teaching example)
    win_pay, lose_pay = (1 - price) / price, -1.0
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    bars = ax.bar(["you win\n(share pays $1)", "you lose\n(share pays $0)"],
                  [win_pay, lose_pay], color=[GREEN, RED], width=0.5)
    for b, v in zip(bars, [win_pay, lose_pay]):
        ax.text(b.get_x() + b.get_width() / 2, v + (0.12 if v > 0 else -0.22),
                f"{v:+.2f} per $1 staked", ha="center", fontsize=10.5, fontweight="bold")
    ev = hit * win_pay + (1 - hit) * lose_pay
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylim(-1.6, 3.4)
    ax.set_ylabel("profit per $1 staked")
    ax.set_title(f"Buying at {price:.2f}: one win pays for ~2.9 losses\n"
                 f"(win {hit:.0%} of the time -> EV = {ev:+.3f} per $1)", fontsize=11)
    STATS["payout"] = {"price": price, "hit": hit, "win_pay": round(win_pay, 2), "ev": round(ev, 3)}
    savefig(fig, "f3_payout.png")


def fig_calibration(entries, winners):
    """F4: hit%% vs paid%% for momentum thresholds — 5-min (calibrated) vs 60-min (edge)."""
    ths = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
    panels = []
    for window, key_w in ((5, 4), (60, 48)):
        hits, paids, ns = [], [], []
        for t in ths:
            b = bets_for(entries, winners, window, "momentum", f"{t:.2f}|{key_w}")
            if len(b) < 10:
                hits.append(np.nan); paids.append(np.nan); ns.append(0)
                continue
            hits.append(100 * sum(1 for x in b if x[2]) / len(b))
            paids.append(100 * np.mean([x[1] for x in b]))
            ns.append(len(b))
        panels.append((window, key_w, hits, paids, ns))
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.6), sharey=True)
    x = np.arange(len(ths))
    for ax, (window, key_w, hits, paids, ns) in zip(axes, panels):
        ax.bar(x - 0.19, paids, 0.38, color=GRAY, alpha=0.8, label="price paid (%)")
        ax.bar(x + 0.19, hits, 0.38, color=GREEN, alpha=0.9, label="actually won (%)")
        ax.set_xticks(x); ax.set_xticklabels([f"{t:.2f}" for t in ths], fontsize=8.5)
        ax.set_xlabel(f"buy the strong side at price >= ...")
        ax.set_title(f"{window}-minute markets", fontsize=11)
        ax.set_ylim(50, 100)
    axes[0].set_ylabel("percent")
    axes[0].legend(frameon=False, loc="upper left", fontsize=9)
    STATS["calibration"] = {f"{w}m": {"hit": [None if np.isnan(h) else round(h, 1) for h in hits],
                                      "paid": [None if np.isnan(p) else round(p, 1) for p in paids],
                                      "n": ns}
                            for (w, kw, hits, paids, ns) in panels}
    savefig(fig, "f4_calibration.png")


def fig_collapse(entries, winners):
    """F5: the running estimate of the 5-min '0.75 in first minute' edge vs sample size."""
    b = bets_for(entries, winners, 5, "momentum", "0.75|1")
    hits = np.cumsum([1 if x[2] else 0 for x in b])
    paids = np.cumsum([x[1] for x in b])
    n = np.arange(1, len(b) + 1)
    edge = hits / n * 100 - paids / n * 100
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.plot(n, edge, color=BLUE, lw=1.4)
    ax.axhline(0, color="black", lw=0.8)
    k = min(90, len(b) - 1)
    ax.annotate(f"after ~{k} bets: {edge[k - 1]:+.1f}pp\n(looked like a great edge!)",
                xy=(k, edge[k - 1]), xytext=(k + 60, max(edge) * 0.75), fontsize=9.5,
                arrowprops=dict(arrowstyle="->", lw=1))
    ax.annotate(f"after all {len(b)} bets: {edge[-1]:+.1f}pp\n(it was noise)",
                xy=(len(b), edge[-1]), xytext=(len(b) * 0.62, min(edge) * 0.2 - 4), fontsize=9.5,
                arrowprops=dict(arrowstyle="->", lw=1))
    ax.set_xlabel("number of bets included (chronological)")
    ax.set_ylabel("estimated edge (pp)")
    ax.set_title('The same rule, measured as data grows — 5-min "buy >= 0.75 in the first minute"',
                 fontsize=11)
    STATS["collapse"] = {"n": len(b), "early_edge": round(float(edge[k - 1]), 1),
                         "final_edge": round(float(edge[-1]), 1)}
    savefig(fig, "f5_collapse.png")


def block_bootstrap(bets, iters=4000, seed=7):
    groups = defaultdict(list)
    for end_ts, _paid, _won, pnl in bets:
        groups[end_ts].append(pnl)
    keys = list(groups)
    rng = random.Random(seed)
    means = []
    for _ in range(iters):
        tot = cnt = 0.0
        for _ in keys:
            for v in groups[keys[rng.randrange(len(keys))]]:
                tot += v; cnt += 1
        means.append(tot / cnt)
    return np.array(means), len(keys)


def fig_bootstrap(entries, winners):
    """F6: bootstrap distribution for the 60-min lead rule."""
    b = bets_for(entries, winners, 60, "momentum", "0.65|24")
    obs = np.mean([x[3] for x in b])
    means, kw = block_bootstrap(b)
    p0 = float((means <= 0).mean())
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.hist(means * 100, bins=48, color=BLUE, alpha=0.75)
    ax.axvline(0, color=RED, lw=1.6)
    ax.axvline(obs * 100, color=GREEN, lw=1.6)
    ax.text(obs * 100 + 0.4, ax.get_ylim()[1] * 0.9, f"measured: {obs * 100:+.1f} cents/bet",
            color=GREEN, fontsize=10)
    ax.text(0.4, ax.get_ylim()[1] * 0.72, f"zero (no edge)\nP(<= 0) = {p0:.3f}", color=RED, fontsize=10)
    ax.set_xlabel("average profit per $1 bet (cents) in each resampled world")
    ax.set_ylabel("how many of 4,000 resamples")
    ax.set_title('4,000 alternate worlds of the 60-min rule "buy >= 0.65 in the first 24 min"',
                 fontsize=11)
    STATS["bootstrap"] = {"n_bets": len(b), "n_windows": kw, "obs_c": round(float(obs) * 100, 1),
                          "p_le_zero": round(p0, 3),
                          "lo90": round(float(np.percentile(means, 5)) * 100, 1),
                          "hi90": round(float(np.percentile(means, 95)) * 100, 1)}
    savefig(fig, "f6_bootstrap.png")


def fig_split(entries, winners):
    """F7: first half vs second half of the period, stable rule vs regime-flip rule."""
    rules = [("5-min: buy >= 0.55 (1st min)", 5, "0.55|1"),
             ("5-min: buy >= 0.75 (1st min)", 5, "0.75|1"),
             ("60-min: buy >= 0.65 (24m)", 60, "0.65|24"),
             ("60-min: buy >= 0.65 (48m)", 60, "0.65|48")]
    labels, a_vals, b_vals = [], [], []
    for label, w, key in rules:
        b = bets_for(entries, winners, w, "momentum", key)
        ts = sorted({x[0] for x in b})
        mid = ts[len(ts) // 2]
        a = [x[3] for x in b if x[0] < mid]
        c = [x[3] for x in b if x[0] >= mid]
        labels.append(label)
        a_vals.append(100 * np.mean(a)); b_vals.append(100 * np.mean(c))
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    ax.bar(x - 0.19, a_vals, 0.38, color=GRAY, label="first half of the data")
    ax.bar(x + 0.19, b_vals, 0.38, color=BLUE, label="second half")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("profit per $1 bet (cents)")
    ax.legend(frameon=False, fontsize=9)
    ax.set_title("The out-of-sample test: does a rule work in BOTH halves of the period?", fontsize=11)
    STATS["split"] = {lab: {"A": round(a, 1), "B": round(bv, 1)}
                      for lab, a, bv in zip(labels, a_vals, b_vals)}
    savefig(fig, "f7_split.png")


def fig_heatmaps(entries, winners):
    """F8: 60-min edge grids — momentum vs fade."""
    m_ths = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
    f_ths = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    wins = [12, 24, 36, 48]
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.0))
    for ax, (mode, ths, ttl) in zip(axes, [("momentum", m_ths, "MOMENTUM: buy the strong side"),
                                           ("fade", f_ths, "FADE: buy the cheap side")]):
        grid = np.full((len(ths), len(wins)), np.nan)
        for i, t in enumerate(ths):
            for j, w in enumerate(wins):
                b = bets_for(entries, winners, 60, mode, f"{t:.2f}|{w}")
                if len(b) >= 10:
                    grid[i, j] = 100 * np.mean([x[3] for x in b])
        im = ax.imshow(grid, cmap="RdYlGn", vmin=-60, vmax=60, aspect="auto")
        for i in range(len(ths)):
            for j in range(len(wins)):
                if not np.isnan(grid[i, j]):
                    ax.text(j, i, f"{grid[i, j]:+.0f}", ha="center", va="center", fontsize=8.5)
        ax.set_xticks(range(len(wins))); ax.set_xticklabels([f"<={w}m" for w in wins], fontsize=8.5)
        ax.set_yticks(range(len(ths))); ax.set_yticklabels([f"{t:.2f}" for t in ths], fontsize=8.5)
        ax.set_xlabel("entered within"); ax.grid(False)
        ax.set_title(ttl, fontsize=10.5)
    axes[0].set_ylabel("trigger price")
    fig.suptitle("60-minute markets: profit per $1 bet (cents), exact fills, real outcomes", fontsize=11, y=1.0)
    savefig(fig, "f8_heatmaps.png")


def fig_stops():
    """F9: what stop-losses did to the 60-min momentum rule (verified CLI runs, 300ms latency)."""
    rules = ["0.65 / 24m", "0.65 / 36m", "0.65 / 48m", "0.70 / 36m"]
    base = [14.8, 11.9, 10.8, 10.3]
    s45 = [2.2, 3.8, 3.9, 3.2]
    s35 = [7.6, 8.0, 7.3, 7.9]
    x = np.arange(len(rules))
    fig, ax = plt.subplots(figsize=(7.6, 3.5))
    ax.bar(x - 0.27, base, 0.27, color=GREEN, label="hold to resolution")
    ax.bar(x, s35, 0.27, color=AMBER, label="stop-loss at 0.35")
    ax.bar(x + 0.27, s45, 0.27, color=RED, label="stop-loss at 0.45")
    ax.set_xticks(x); ax.set_xticklabels(rules)
    ax.set_ylabel("profit per $1 bet (cents)")
    ax.legend(frameon=False, fontsize=9)
    ax.set_title("Stop-losses destroy the edge (60-min momentum, 300ms latency)", fontsize=11)
    savefig(fig, "f9_stops.png")


def fig_equity(entries, winners):
    """F10: equity curve of the 60-min lead rule."""
    b = bets_for(entries, winners, 60, "momentum", "0.65|24")
    cum = np.cumsum([x[3] for x in b])
    peak = np.maximum.accumulate(cum)
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.plot(np.arange(1, len(b) + 1), cum, color=GREEN, lw=1.6)
    ax.fill_between(np.arange(1, len(b) + 1), cum, peak, color=RED, alpha=0.18, label="drawdown")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("bet number (chronological)")
    ax.set_ylabel("cumulative profit ($, at $1 stakes)")
    ax.legend(frameon=False, fontsize=9)
    ax.set_title('Equity curve: 60-min "buy >= 0.65 in first 24 min", held to resolution', fontsize=11)
    STATS["equity"] = {"n": len(b), "final": round(float(cum[-1]), 2),
                       "hit": round(100 * sum(1 for x in b if x[2]) / len(b), 1),
                       "paid": round(100 * float(np.mean([x[1] for x in b])), 1),
                       "maxdd": round(float((peak - cum).max()), 2)}
    savefig(fig, "f10_equity.png")


def main():
    entries, winners = load_cache()
    STATS["dataset"] = {
        "buckets": len(entries),
        "settled": sum(1 for e in entries if e["cid"] in winners),
        "by_window": {str(w): sum(1 for e in entries if e["window_min"] == w) for w in (5, 15, 60)},
    }
    fig_price_path_and_book(entries, winners)
    fig_payout()
    fig_calibration(entries, winners)
    fig_collapse(entries, winners)
    fig_bootstrap(entries, winners)
    fig_split(entries, winners)
    fig_heatmaps(entries, winners)
    fig_stops()
    fig_equity(entries, winners)
    (OUT / "stats.json").write_text(json.dumps(STATS, indent=1), encoding="utf-8")
    print("\nSTATS:", json.dumps(STATS, indent=1))


if __name__ == "__main__":
    main()
