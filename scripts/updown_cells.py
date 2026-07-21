r"""updown_cells — query the price x time calibration data yourself.

Samples every 60-min recording's BOTH order books once per minute (ask side,
spread <= 5c, uncrossed) into a cached observation file; then any (price band,
minute range) cell answers instantly with hit% vs paid% for ALL data and for
the two chronological halves.

    mm cell --extract            rebuild the observation cache (~10 min, rare)
    mm cell 0.60-0.70 20-30      edge of asks 60-70c seen at minutes 20-30
    mm cell 0.97-1.00 40-59      the "lazy asks near settlement" corner

DISCIPLINE (printed on every result): querying many cells IS data-mining —
a good-looking cell found this way needs FRESH out-of-sample windows before
it means anything. Both halves same sign is the minimum bar, not proof.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT  # noqa: E402

OBS = PROJECT_ROOT / "data" / "updown_hd" / "_pt_obs.json"


def extract() -> None:
    from src.orderbook import LocalOrderBook
    from src.updown_replay import _apply, load_recording, peek_meta
    hd = PROJECT_ROOT / "data" / "updown_hd"
    resolved = json.loads((hd / "_resolved.json").read_text(encoding="utf-8"))
    files = [p for p in sorted(hd.glob("udx_*.jsonl*"))
             if (m := peek_meta(p)) and m.get("window_min") == 60]
    print(f"extracting {len(files)} recordings (1-min checkpoints)...")
    obs = []
    for i, f in enumerate(files, 1):
        meta, events, _ = load_recording(f)
        if not meta or not events:
            continue
        winner = resolved.get(meta.get("condition_id"))
        if not winner:
            continue
        up, dn = meta["up_token"], meta["down_token"]
        books = {up: LocalOrderBook(up), dn: LocalOrderBook(dn)}
        start, nxt = meta["start_ts"], 1
        for e in events:
            _apply(e["ev"], books)
            mins = (e["recv_ms"] / 1000.0 - start) / 60.0
            if nxt < 60 and mins >= nxt:
                for side, tid in (("Up", up), ("Down", dn)):
                    b = books[tid]
                    bid, ask = b.best_bid, b.best_ask
                    if bid is not None and ask is not None and bid < ask and ask - bid <= 0.05:
                        obs.append([nxt, round(ask, 3), 1 if side == winner else 0,
                                    meta["end_ts"]])
                nxt += 1
        if i % 100 == 0:
            print(f"  ...{i}/{len(files)}")
    OBS.write_text(json.dumps(obs), encoding="utf-8")
    print(f"wrote {len(obs)} observations -> {OBS.name}")


def query(band: str, minutes: str, one_per_window: bool = False, since: str = "") -> int:
    if not OBS.exists():
        print("no observation cache yet — run:  mm cell --extract")
        return 1
    try:
        lo, hi = (float(x) for x in band.split("-"))
        m0, m1 = (int(x) for x in minutes.split("-"))
    except ValueError:
        print("format:  mm cell 0.60-0.70 20-30")
        return 1
    import datetime as dt
    obs = json.loads(OBS.read_text(encoding="utf-8"))
    if since:
        # keep only windows (buckets) that ended on/after this date — the honest
        # out-of-sample test: windows the frozen cell could NOT have been fit to.
        try:
            cut = dt.datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            print("format:  --since 2026-07-14"); return 1
        before = len({wk for *_, wk in obs})
        obs = [o for o in obs if o[3] >= cut]
        after = len({wk for *_, wk in obs})
        print(f"(FRESH-ONLY: windows ending >= {since} — {after} of {before} total windows)")
    sel = [(m, a, w, wk) for m, a, w, wk in obs if lo <= a < hi and m0 <= m <= m1]
    if one_per_window:
        first: dict = {}
        for r in sorted(sel):                      # earliest minute wins
            first.setdefault(r[3], r)
        sel = list(first.values())
        print("(one bet per clock-window: first qualifying ask only — replicable live)")
    if not sel:
        print("no observations in that cell")
        return 0
    wks = sorted({wk for *_, wk in obs})
    mid = wks[len(wks) // 2]
    import datetime as dt
    print(f"asks {lo:.2f}-{hi:.2f} at minutes {m0}-{m1}   "
          f"(halves split at {dt.datetime.fromtimestamp(mid, dt.timezone.utc):%m-%d %H:%M} UTC)")
    print(f"{'':>10} {'obs':>6} {'windows':>8} {'hit%':>7} {'paid%':>7} {'edge_pp':>8} {'$100->':>9}")
    for label, rows in (("ALL", sel),
                        ("HALF A", [r for r in sel if r[3] < mid]),
                        ("HALF B", [r for r in sel if r[3] >= mid])):
        if not rows:
            print(f"{label:>10} {'-':>6}")
            continue
        n = len(rows)
        nw = len({wk for *_, wk in rows})
        hit = sum(w for _, _, w, _ in rows) / n
        paid = sum(a for _, a, _, _ in rows) / n
        # start $100, flat $1 per bet, net of the crypto taker fee
        # (cost/share = p + 0.07*p*(1-p); win pays 1/cost shares' dollars)
        bal = 100.0
        for _, a, w, _ in rows:
            eff = a + 0.07 * a * (1 - a)
            bal += (1.0 / eff - 1.0) if w else -1.0
        flag = "  (thin!)" if nw < 15 else ""
        print(f"{label:>10} {n:>6} {nw:>8} {hit * 100:>7.1f} {paid * 100:>7.1f} "
              f"{(hit - paid) * 100:>+8.1f} {bal:>9.2f}{flag}")
    print("\n$100-> = ending balance starting from $100 with a flat $1 on every")
    print("observation above, net of the 7% crypto taker fee.")
    print("\nreminder: you are mining. same sign in BOTH halves = minimum bar;")
    print("only FRESH windows recorded after today can confirm a cell.")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if args and args[0] == "--extract":
        extract()
        return 0
    opw = "--one-per-window" in args
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    args = [a for a in args if a != "--one-per-window"]
    if len(args) >= 2:
        return query(args[0], args[1], opw, since)
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
