r"""
Collect RAW data on short-term crypto Up/Down markets, to analyse offline later.

For every live bucket (across the chosen assets) it samples the 'Up' book every
few seconds over the bucket's life, and on resolution writes one JSON line:
    {asset, cond, label, end, dur_s, winner, final_up,
     samples: [[t_sec, mid, bid, ask, bid_size, ask_size, bid_depth2c, ask_depth2c], ...]}
where *_size is shares at the best price and *_depth2c is cumulative shares within
2c of the touch. Run it for hours in the background; then run updown_analyze.py.

This separates DATA from STRATEGY: record once, then test any number of entry
rules (threshold × timing × asset) against the same data. SIMULATION ONLY.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_collect.py --assets Bitcoin --duration 0
    (duration 0 = run until Ctrl-C; add more assets for more data, e.g. Bitcoin,Ethereum,Solana,XRP)
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT  # noqa: E402
from src import gamma  # noqa: E402
from src.connection import build_public_client  # noqa: E402
from src.market_data import fetch_order_book  # noqa: E402

BUCKET_SECONDS = 300
OUT_DIR = PROJECT_ROOT / "data" / "updown"


def _end_ts(iso: str):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


try:  # explicit Israel time; falls back to the machine's local tz if tzdata missing
    from zoneinfo import ZoneInfo
    _IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # noqa: BLE001 - Windows without the IANA tz database
    _IL_TZ = None


def _il(ts: float) -> str:
    """Format a unix timestamp as HH:MM in Israel time (or local tz as a fallback)."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.astimezone(_IL_TZ).strftime("%H:%M") if _IL_TZ else dt.astimezone().strftime("%H:%M")


def _depth_within(levels, best_price, band):
    """Cumulative shares resting within `band` of `best_price`.

    `levels` is [(price, size), ...] (best first, from bid_levels/ask_levels). This
    answers "how much could I fill near the touch?" — bigger than top-of-book size,
    so later analysis can gauge fillable SIZE and price slippage, not just whether a
    single share exists at the best price.
    """
    if not levels or best_price is None:
        return None
    return round(sum(sz for px, sz in levels if abs(px - best_price) <= band + 1e-9), 2)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # avoid cp1255 crashes
    p = argparse.ArgumentParser(description="Collect crypto Up/Down data.")
    p.add_argument("--assets", default="Bitcoin", help="comma list, e.g. Bitcoin,Ethereum,Solana,XRP")
    p.add_argument("--poll", type=float, default=12.0, help="seconds between chance samples")
    p.add_argument("--duration", type=float, default=0.0, help="seconds to run (0 = until Ctrl-C)")
    p.add_argument("--windows", default="5,15,60",
                   help="bucket lengths (minutes) to record, e.g. '5' for 5-min only")
    args = p.parse_args()

    assets = [a.strip().lower() for a in args.assets.split(",") if a.strip()]
    allowed_windows = {int(x) for x in args.windows.split(",") if x.strip()}
    client = build_public_client()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"updown_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    fh = out_path.open("w", encoding="utf-8")
    print(f"Collecting {assets} Up/Down → {out_path}\n(poll {args.poll:g}s; Ctrl-C to stop)\n")

    active: dict[str, dict] = {}   # cond_id -> {market, start, end, samples}
    done: set[str] = set()
    completed = 0
    start_run = time.monotonic()

    def finish(cid: str) -> None:
        nonlocal completed
        b = active.pop(cid)
        samples = b["samples"]
        if not samples:
            done.add(cid); return
        final_up = samples[-1][1]
        rec = {
            "asset": b["asset"], "cond": cid, "label": b["label"],
            "end": b["end_iso"], "dur_s": b["dur"], "samples": samples,
            "winner": "Up" if final_up >= 0.5 else "Down", "final_up": round(final_up, 4),
        }
        fh.write(json.dumps(rec) + "\n"); fh.flush()
        done.add(cid); completed += 1
        when = f"{_il(b['start'])}-{_il(b['end'])} IL"  # window shown in Israel time
        print(f"  ✓ {b['asset']:>8} {when}  ({len(samples)} samples) → {rec['winner']}  "
              f"[{completed} buckets saved]")

    try:
        while True:
            now = time.time()
            # discover new live buckets for our assets (resilient to API hiccups)
            try:
                live = gamma.crypto_updown(80)
            except Exception as exc:  # noqa: BLE001
                print(f"  [warn] discovery failed, retrying next cycle: {exc}")
                live = []
            for m in live:
                a = m.question.split(" up or down", 1)[0].split(" Up or Down", 1)[0].strip()
                if a.lower() not in assets:
                    continue
                cid = m.condition_id
                if cid in active or cid in done or "Up" not in m.tokens:
                    continue
                end = _end_ts(m.end_date)
                # Window length comes from the TITLE (Gamma's startDate is the
                # creation time, ~a day early). start = end − window.
                win = gamma.window_minutes(m.question)
                if not end or not win or win not in allowed_windows:
                    continue  # daily / unparseable / not a requested window length
                start = end - win * 60
                if now < start or now >= end:
                    continue  # not yet started, or already over
                active[cid] = {"asset": a, "market": m, "up_tok": m.tokens["Up"],
                               "start": start, "end": end, "dur": round(end - start),
                               "end_iso": m.end_date, "label": m.question.split(" - ")[-1],
                               "samples": []}

            # sample active buckets; finish any that have ended
            for cid in list(active.keys()):
                b = active[cid]
                if now >= b["end"]:
                    finish(cid); continue
                # Record the Up token's mid + best bid/ask, the SIZE at each, and the
                # cumulative depth within 2c of the touch — so analysis can charge the
                # real executable price (the ASK), check the order is actually fillable
                # (not a tight-but-empty quote), and later model bigger fills/slippage.
                # Sample = [t, mid, bid, ask, bid_size, ask_size, bid_depth2c, ask_depth2c].
                try:
                    book = fetch_order_book(client, b["up_tok"])
                    mid = book.midpoint
                except Exception as exc:  # noqa: BLE001 - never let one fetch kill the run
                    print(f"  [warn] sample failed for {b['asset']} {b['label']}: {exc}")
                    continue
                if mid is not None:
                    bb, ba = book.best_bid, book.best_ask
                    bid = round(bb, 4) if bb is not None else None
                    ask = round(ba, 4) if ba is not None else None
                    bid_lv = book.bid_levels(50)  # enough levels to cover 2c at any tick
                    ask_lv = book.ask_levels(50)
                    bid_sz = round(bid_lv[0][1], 2) if bid_lv else None  # at best price
                    ask_sz = round(ask_lv[0][1], 2) if ask_lv else None
                    bid_dep = _depth_within(bid_lv, bb, 0.02)  # within 2c of the touch
                    ask_dep = _depth_within(ask_lv, ba, 0.02)
                    b["samples"].append([round(now - b["start"], 1), round(mid, 4),
                                         bid, ask, bid_sz, ask_sz, bid_dep, ask_dep])

            if args.duration and (time.monotonic() - start_run) >= args.duration:
                break
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\n(stopping)")
    finally:
        for cid in list(active.keys()):
            finish(cid)
        fh.close()

    print(f"\nSaved {completed} buckets → {out_path}")
    print(f"Analyse with:  .\\.venv\\Scripts\\python.exe scripts\\updown_analyze.py {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
