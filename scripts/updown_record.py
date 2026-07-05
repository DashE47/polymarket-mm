r"""
HIGH-PRECISION recorder for short-term crypto Up/Down markets.

Goal: capture enough that an OFFLINE replay is a faithful re-run of what you would
have seen and filled LIVE — so a backtest on this data can be trusted before ever
risking real money. This is deliberately heavier than updown_collect.py (which
stores a periodic aggregate); use that one for the quick study, this one when you
need execution-grade fidelity.

What makes it precise
  * BOTH order books. We subscribe to the Up AND Down tokens over the CLOB
    WebSocket, so every fill can be priced against the exact book you'd hit
    (Down is a real separate book here, not inferred from Up).
  * FULL tick-by-tick stream. We record every raw WS event verbatim — the opening
    `book` snapshot, every `price_change` delta, every `last_trade_price` (the
    trade tape) and `tick_size_change` — so replay can reconstruct the precise
    book state and the real trade prints at any instant, not just at poll times.
  * PRECISE timestamps. Each event is wrapped with our receive time to the
    millisecond (UTC + a monotonic offset), alongside the exchange's own event
    timestamp/hash that ride inside the event. That lets replay model observation
    latency instead of pretending fills are instantaneous.
  * REAL resolution. After the bucket ends we read the actual settled outcome from
    Gamma (outcomePrices → 1/0), not a "last mid ≥ 0.5" guess. Falls back to the
    last mid only if Gamma hasn't posted the result yet (flagged as such).
  * FULL metadata, verbatim. The complete raw Gamma market dict is stored at start
    (tick size, negRisk, minimum order size, fees/rewards, ids …) so the exact
    trading rules of the instrument are on record.

Output: one self-contained JSON-Lines file per bucket in data/updown_hd/:
    line 1      {"rec":"meta",  ...market + tokens + raw gamma dict}
    lines 2..N  {"rec":"ev", recv_ts, recv_ms, recv_mono, ev:<raw WS event>}
    last line   {"rec":"resolution", winner, outcome_prices, source, ...}

SIMULATION ONLY — this records market data. It never sends an order.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_record.py --assets Bitcoin,Ethereum,Solana,XRP --windows 5,15,60 --duration 0
    (duration 0 = run until Ctrl-C. Records 5/15/60-min buckets by default; each live
     bucket is one WS connection, so all-windows × 4 assets is ~12 sockets. Prints a
     running bucket counter and the on-disk size periodically — tick data is BULKY.)

NOTE ON FEES: Polymarket's CLOB currently charges no maker/taker trading fee, but
confirm this for your account/market before trusting P&L — the raw metadata we
store lets a replay apply whatever fee model is correct.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT, SETTINGS  # noqa: E402
from src import gamma  # noqa: E402
from src.orderbook import LocalOrderBook  # noqa: E402
from src.ws_client import WS_MARKET_URL, MarketStream  # noqa: E402

RECORDER_VERSION = 1
OUT_DIR = PROJECT_ROOT / "data" / "updown_hd"
END_GRACE = 4.0        # keep recording this many seconds past the end (catch the close)
RESOLVE_TRIES = 18     # after end, poll Gamma this many times for the settled result
RESOLVE_WAIT = 10.0    # seconds between resolution polls (≈3 min total)
FLUSH_EVERY = 64       # flush to disk every N events (crash-safe within a fraction of a sec,
                       # while letting gzip compress across the batch for a good ratio)

try:  # explicit Israel time for progress lines; fall back to local tz
    from zoneinfo import ZoneInfo
    _IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # noqa: BLE001
    _IL_TZ = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _il(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.astimezone(_IL_TZ).strftime("%H:%M") if _IL_TZ else dt.astimezone().strftime("%H:%M")


def _end_ts(iso: str):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _raw_market(condition_id: str, closed: bool = False) -> dict | None:
    """The full raw Gamma market dict. `closed=True` for settled-market lookups —
    Gamma's /markets hides closed markets by default, so resolution needs it."""
    params = {"condition_ids": condition_id, "limit": 1}
    if closed:
        params["closed"] = "true"
    data = gamma.get_json(f"{SETTINGS.gamma_host}/markets", params=params)
    rows = data if isinstance(data, list) else data.get("data", [])
    return rows[0] if rows else None


def _outcome_prices(raw: dict) -> dict[str, float]:
    outs = gamma._parse_json_list(raw.get("outcomes"))
    prices = gamma._parse_json_list(raw.get("outcomePrices"))
    out: dict[str, float] = {}
    for o, p in zip(outs, prices):
        try:
            out[o] = float(p)
        except (TypeError, ValueError):
            pass
    return out


def _decisive(opx: dict[str, float]) -> bool:
    """True once the market has settled to ~1/0 (a real resolution)."""
    return bool(opx) and any(v >= 0.99 for v in opx.values())


class Stats:
    """Thread-safe running tally of completed buckets (finalize runs off-thread)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.completed = 0
        self.events = 0
        self.trades = 0
        self.by_window: dict[int, int] = {}
        self.by_asset: dict[str, int] = {}

    def record(self, asset: str, window_min: int, events: int, trades: int) -> tuple[int, dict[int, int]]:
        with self._lock:
            self.completed += 1
            self.events += events
            self.trades += trades
            self.by_window[window_min] = self.by_window.get(window_min, 0) + 1
            self.by_asset[asset] = self.by_asset.get(asset, 0) + 1
            return self.completed, dict(sorted(self.by_window.items()))

    def snapshot(self) -> dict:
        with self._lock:
            return {"completed": self.completed, "events": self.events, "trades": self.trades,
                    "by_window": dict(sorted(self.by_window.items())), "by_asset": dict(self.by_asset)}


class BucketRecorder:
    """Records both books + trades for ONE bucket, then its settled outcome."""

    def __init__(self, market, asset: str, window_min: int, end_ts: float,
                 raw_meta: dict | None, stats: "Stats", compress: bool = True) -> None:
        self.market = market
        self.asset = asset
        self.stats = stats
        self.window_min = window_min
        self.end_ts = end_ts
        self.cid = market.condition_id
        self.up_tok = market.tokens["Up"]
        self.down_tok = market.tokens["Down"]
        self.start_ts = end_ts - window_min * 60
        self.start_mono = time.monotonic()
        self.events = 0
        self.trades = 0
        self.winner: str | None = None
        self.last_mid: dict[str, float | None] = {self.up_tok: None, self.down_tok: None}
        self._lock = threading.Lock()

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "jsonl.gz" if compress else "jsonl"
        self.path = OUT_DIR / f"udx_{asset}_{stamp}_{self.cid[:10]}.{ext}"
        # gzip.open in text mode = streaming compression: every line is compressed
        # on its way to disk, so the file is never stored uncompressed.
        self._fh = gzip.open(self.path, "wt", encoding="utf-8") if compress else self.path.open("w", encoding="utf-8")
        self._since_flush = 0
        self._write({
            "rec": "meta", "recorder_version": RECORDER_VERSION, "ws_url": WS_MARKET_URL,
            "asset": asset, "condition_id": self.cid, "question": market.question,
            "up_token": self.up_tok, "down_token": self.down_tok,
            "window_min": window_min, "end_iso": market.end_date,
            "end_ts": end_ts, "start_ts": self.start_ts, "captured_at": _now_iso(),
            "gamma_market": raw_meta,  # verbatim: tick size, negRisk, min size, fees, …
        })
        self._fh.flush()  # get the meta line on disk right away
        # Subscribe to BOTH tokens on one socket. on_raw stores every event
        # verbatim; on_update maintains a mid per token for progress + fallback.
        self._stream = MarketStream([self.up_tok, self.down_tok],
                                    on_update=self._on_book, on_raw=self._on_raw)

    # --- writing ----------------------------------------------------------

    def _write(self, obj: dict) -> None:
        with self._lock:
            self._fh.write(json.dumps(obj) + "\n")
            self._since_flush += 1
            if self._since_flush >= FLUSH_EVERY:
                self._fh.flush()
                self._since_flush = 0

    def _on_raw(self, ev: dict) -> None:
        # WS thread. Wrap the raw event with millisecond receive timestamps.
        et = ev.get("event_type") or ev.get("type")
        self._write({
            "rec": "ev", "recv_ts": _now_iso(), "recv_ms": int(time.time() * 1000),
            "recv_mono": round(time.monotonic() - self.start_mono, 3), "ev": ev,
        })
        self.events += 1
        if et == "last_trade_price":
            self.trades += 1

    def _on_book(self, tid: str, book: LocalOrderBook) -> None:
        mid = book.midpoint
        if mid is not None:  # keep the last VALID mid (books go one-sided near the close)
            self.last_mid[tid] = mid

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._stream.run_in_thread()
        print(f"[rec] {self.asset:>8} {self.window_min}m {_il(self.start_ts)}-{_il(self.end_ts)} IL "
              f"-> {self.path.name}")

    def finalize(self, quick: bool = False) -> None:
        """Stop streaming, read the settled outcome, write the resolution line."""
        self._stream.stop()
        winner, opx, resolved, src = self._resolve(quick)
        self.winner = winner
        self._write({
            "rec": "resolution", "resolved": resolved, "winner": winner,
            "outcome_prices": opx, "source": src,
            "final_up_mid": self.last_mid.get(self.up_tok),
            "final_down_mid": self.last_mid.get(self.down_tok),
            "events": self.events, "trades": self.trades, "resolved_at": _now_iso(),
        })
        self._fh.close()
        total, byw = self.stats.record(self.asset, self.window_min, self.events, self.trades)
        print(f"[done] {self.asset:>8} {self.window_min}m -> {winner or '??'} "
              f"({src}) | {self.events} ev, {self.trades} tr | TOTAL this run: {total} buckets {byw}")

    def _resolve(self, quick: bool):
        tries = 1 if quick else RESOLVE_TRIES
        for _ in range(tries):
            try:
                raw = _raw_market(self.cid, closed=True)  # settled-market lookup
            except Exception:  # noqa: BLE001 - never let a network hiccup crash finalize
                raw = None
            if raw:
                opx = _outcome_prices(raw)
                if bool(raw.get("closed")) and _decisive(opx):
                    return max(opx, key=opx.get), opx, True, "gamma"
            if not quick:
                time.sleep(RESOLVE_WAIT)
        # Gamma hasn't posted the result — fall back to the last observed Up mid.
        up = self.last_mid.get(self.up_tok)
        if up is None:
            return None, {}, False, "unresolved"
        return ("Up" if up >= 0.5 else "Down"), {}, False, "last_mid_fallback"


def _asset_of(question: str) -> str:
    q = question.lower()
    for sep in (" up or down", " price up or down"):
        if sep in q:
            return question[: q.index(sep)].strip()
    return question.split(" - ")[0].strip()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # avoid cp1255 crashes
    p = argparse.ArgumentParser(description="High-precision Up/Down recorder (both books, tick-level).")
    p.add_argument("--assets", default="Bitcoin,Ethereum,Solana,XRP", help="comma list")
    # Default excludes 5-min: proven efficient (no edge either way on 2,360 buckets)
    # and it produced ~70% of the disk usage. Pass --windows 5,15,60 to include it.
    p.add_argument("--windows", default="15,60", help="bucket lengths (min) to record, e.g. '15,60' or '5,15,60'")
    p.add_argument("--duration", type=float, default=0.0, help="seconds to run (0 = until Ctrl-C)")
    p.add_argument("--discover-poll", type=float, default=5.0, help="seconds between discovery scans")
    p.add_argument("--status-every", type=float, default=300.0, help="seconds between running-total status lines")
    p.add_argument("--no-compress", action="store_true", help="write plain .jsonl instead of streaming .jsonl.gz")
    args = p.parse_args()
    compress = not args.no_compress

    assets = {a.strip().lower() for a in args.assets.split(",") if a.strip()}
    allowed = {int(x) for x in args.windows.split(",") if x.strip()}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"High-precision recorder -> {OUT_DIR}")
    print(f"assets={sorted(assets)} windows={sorted(allowed)}m  (both books, tick-level, "
          f"{'gzip-compressed' if compress else 'UNCOMPRESSED'}; Ctrl-C to stop)\n")

    active: dict[str, BucketRecorder] = {}
    done: set[str] = set()
    stats = Stats()
    start_run = time.monotonic()
    last_status = start_run

    def finalize_async(br: BucketRecorder, quick: bool = False) -> None:
        threading.Thread(target=br.finalize, args=(quick,), daemon=True).start()

    def print_status(mono: float) -> None:
        s = stats.snapshot()
        files = list(OUT_DIR.glob("udx_*.jsonl*"))
        mb = sum(f.stat().st_size for f in files) / 1e6
        gb = f"{mb / 1000:.2f} GB" if mb >= 1000 else f"{mb:.0f} MB"
        print(f"[status] {(mono - start_run) / 60:.0f}m up | active {len(active)} | "
              f"done this run {s['completed']} {s['by_window']} | "
              f"{len(files)} files, {gb} on disk | {s['events']:,} events, {s['trades']:,} trades")

    try:
        while True:
            now = time.time()
            try:
                live = gamma.crypto_updown(120)
            except Exception as exc:  # noqa: BLE001
                print(f"  [warn] discovery failed: {exc}")
                live = []
            for m in live:
                cid = m.condition_id
                if cid in active or cid in done:
                    continue
                if "Up" not in m.tokens or "Down" not in m.tokens:
                    continue
                asset = _asset_of(m.question)
                if asset.lower() not in assets:
                    continue
                end = _end_ts(m.end_date)
                win = gamma.window_minutes(m.question)
                if not end or not win or win not in allowed:
                    continue
                start = end - win * 60
                if now < start or now >= end:
                    continue  # only catch buckets that are live right now
                try:
                    raw = _raw_market(cid)  # full metadata snapshot at join
                except Exception:  # noqa: BLE001
                    raw = None
                try:
                    br = BucketRecorder(m, asset, win, end, raw, stats, compress)
                    br.start()
                    active[cid] = br
                except Exception as exc:  # noqa: BLE001 - one bad bucket shouldn't stop the run
                    print(f"  [warn] could not start {asset} {cid[:8]}: {exc}")
                    done.add(cid)

            for cid in list(active):
                br = active[cid]
                if now >= br.end_ts + END_GRACE:
                    finalize_async(br)     # resolve + close off the main thread
                    done.add(cid)
                    del active[cid]

            mono = time.monotonic()
            if mono - last_status >= args.status_every:
                print_status(mono)
                last_status = mono
            if args.duration and (mono - start_run) >= args.duration:
                break
            time.sleep(args.discover_poll)
    except KeyboardInterrupt:
        print("\n(stopping — finalizing active buckets)")
    finally:
        for br in list(active.values()):
            br.finalize(quick=True)  # quick resolve on shutdown

    s = stats.snapshot()
    files = list(OUT_DIR.glob("udx_*.jsonl*"))
    mb = sum(f.stat().st_size for f in files) / 1e6
    print(f"\nSaved {s['completed']} buckets this run {s['by_window']} (by asset {s['by_asset']}).")
    print(f"{len(files)} total files in {OUT_DIR}  ({mb:.0f} MB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
