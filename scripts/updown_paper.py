r"""
PAPER TRADER — trades the validated momentum rule live, with a DEMO wallet.

This is the bot, minus real money: it watches live 15/60-min crypto Up/Down
markets over the CLOB WebSocket, and when the strong side's mid crosses the
rule's threshold it "buys" by walking the REAL live ask ladder (same fill model
the replay validated). Positions are held to resolution (matching the validated
rule), settled on the REAL Gamma outcome, and every cent flows through a demo
wallet persisted on disk. Run it for days; if its P&L tracks what the replay
predicted, the pipeline is proven end-to-end.

RULES (from the 16GB study — see Mission Control):
    60-min markets: buy the strong side when its mid ≥ 0.65, within the first 48 min
    15-min markets: buy the strong side when its mid ≥ 0.85, within the first 12 min
    (15-min is OFF by default: across 7 days of sim+live it nets ~breakeven after
    spread; the validated edge is the 60-min rule. Re-enable with --windows 15,60.)

SIZING: --stake is the budget per CLOCK-WINDOW, split evenly across the assets.
The 4 cryptos move as one block, so 4 full stakes in the same window is one bet
levered 4x — the July 6-7 live run learned this the hard way.

STATE (data/paper/):
    wallet.json    {balance, start_balance, ...}    — the demo wallet
    trades.jsonl   append-only: {"type":"entry"...} then {"type":"settle"...}
    (restart-safe: already-traded buckets are skipped on reload)

SIMULATION ONLY — no orders are sent, no keys are used.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_paper.py --stake 10          # 60-min rule
    .\.venv\Scripts\python.exe scripts\updown_paper.py --windows 15,60     # both rules
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT  # noqa: E402
from src import gamma  # noqa: E402
from src.orderbook import LocalOrderBook  # noqa: E402
from src.updown_replay import walk_asks  # noqa: E402
from src.ws_client import MarketStream  # noqa: E402

PAPER_DIR = PROJECT_ROOT / "data" / "paper"
# window_min -> (threshold, latest entry, seconds from bucket start)
RULES: dict[int, tuple[float, float]] = {60: (0.65, 48 * 60), 15: (0.85, 12 * 60)}
MAX_SPREAD = 0.05
MIN_FILL_FRAC = 0.5          # skip if the live book can't fill ≥ half the stake
RESOLVE_RETRY_S = 60.0       # how often to re-poll Gamma for unsettled positions
RESOLVE_GIVEUP_S = 4 * 3600  # stop retrying after this long (flagged, not lost)

try:
    from zoneinfo import ZoneInfo
    _IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # noqa: BLE001
    _IL_TZ = None


def _il(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.astimezone(_IL_TZ).strftime("%H:%M") if _IL_TZ else dt.astimezone().strftime("%H:%M")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _end_ts(iso: str):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


class Wallet:
    """The demo wallet + append-only trade log. All writes flushed immediately."""

    def __init__(self, start_balance: float) -> None:
        PAPER_DIR.mkdir(parents=True, exist_ok=True)
        self.wallet_path = PAPER_DIR / "wallet.json"
        self.trades_path = PAPER_DIR / "trades.jsonl"
        self._lock = threading.Lock()
        if self.wallet_path.exists():
            self.state = json.loads(self.wallet_path.read_text(encoding="utf-8"))
        else:
            self.state = {"balance": start_balance, "start_balance": start_balance,
                          "created": _now_iso()}
            self._flush()
        # Reload history so restarts never double-trade a bucket.
        self.traded_cids: set[str] = set()
        self.open: dict[str, dict] = {}   # cid -> entry record
        if self.trades_path.exists():
            with self.trades_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec["type"] == "entry":
                        self.traded_cids.add(rec["cid"])
                        self.open[rec["cid"]] = rec
                    elif rec["type"] in ("settle", "abandon"):
                        self.open.pop(rec["cid"], None)

    def _flush(self) -> None:
        self.state["updated"] = _now_iso()
        self.wallet_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def _log(self, rec: dict) -> None:
        with self.trades_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    def enter(self, rec: dict) -> None:
        with self._lock:
            self.state["balance"] -= rec["spent"]
            self.traded_cids.add(rec["cid"])
            self.open[rec["cid"]] = rec
            self._log(rec)
            self._flush()

    def settle(self, cid: str, winner: str) -> dict | None:
        with self._lock:
            entry = self.open.pop(cid, None)
            if entry is None:
                return None
            won = entry["side"] == winner
            credit = entry["shares"] if won else 0.0
            self.state["balance"] += credit
            rec = {"type": "settle", "cid": cid, "ts": _now_iso(), "winner": winner,
                   "won": won, "credit": round(credit, 4),
                   "pnl": round(credit - entry["spent"], 4),
                   "balance_after": round(self.state["balance"], 4)}
            self._log(rec)
            self._flush()
            return rec

    def abandon(self, cid: str) -> None:
        """Resolution never arrived — release the position as a flagged loss of
        nothing further (stake already deducted; humans investigate)."""
        with self._lock:
            entry = self.open.pop(cid, None)
            if entry is not None:
                self._log({"type": "abandon", "cid": cid, "ts": _now_iso()})
                self._flush()


class BucketTrader:
    """Watches ONE live bucket and takes at most one rule-triggered paper trade."""

    def __init__(self, market, asset: str, window_min: int, end_ts: float,
                 wallet: Wallet, stake: float) -> None:
        self.market = market
        self.asset = asset
        self.window_min = window_min
        self.end_ts = end_ts
        self.start_ts = end_ts - window_min * 60
        self.cid = market.condition_id
        self.wallet = wallet
        self.stake = stake
        self.tokens = {"Up": market.tokens["Up"], "Down": market.tokens["Down"]}
        self.sides = {v: k for k, v in self.tokens.items()}
        self.entered = False
        self._lock = threading.Lock()
        self._stream = MarketStream(list(self.tokens.values()), on_update=self._on_book)

    def start(self) -> None:
        self._stream.run_in_thread()
        thr, entry_max = RULES[self.window_min]
        print(f"[watch] {self.asset:>8} {self.window_min}m {_il(self.start_ts)}-{_il(self.end_ts)} IL "
              f"(buy ≥{thr:.2f} within first {entry_max / 60:.0f}m)")

    def stop(self) -> None:
        self._stream.stop()

    def _on_book(self, tid: str, book: LocalOrderBook) -> None:
        # WS thread. Evaluate the rule against the updated side's own book.
        if self.entered:
            return
        now = time.time()
        thr, entry_max = RULES[self.window_min]
        if now >= self.end_ts or (now - self.start_ts) > entry_max:
            return
        mid, spread = book.midpoint, book.spread
        if mid is None or spread is None or mid < thr or spread > MAX_SPREAD:
            return
        # Skip crossed/locked books (bid ≥ ask): the quotes are momentarily unreliable
        # and can fill below the threshold the rule thinks it's buying at.
        bb, ba = book.best_bid, book.best_ask
        if bb is None or ba is None or bb >= ba:
            return
        # Also require the OTHER side to confirm this is the strong side (mid ≥ 0.5).
        if mid < 0.5:
            return
        with self._lock:
            if self.entered:
                return
            shares, spent, avg = walk_asks(book.ask_levels(50), self.stake)
            if avg is None or spent < self.stake * MIN_FILL_FRAC:
                return  # book too thin right now — keep watching
            self.entered = True
        side = self.sides[tid]
        rec = {"type": "entry", "cid": self.cid, "ts": _now_iso(), "ts_unix": now,
               "asset": self.asset, "window_min": self.window_min, "side": side,
               "question": self.market.question, "end_ts": self.end_ts,
               "thr": thr, "trigger_mid": round(mid, 4), "spread": round(spread, 4),
               "shares": round(shares, 4), "spent": round(spent, 4), "avg": round(avg, 5),
               "elapsed_min": round((now - self.start_ts) / 60, 2),
               "book_top": {"bids": book.bid_levels(3), "asks": book.ask_levels(3)}}
        self.wallet.enter(rec)
        print(f"[TRADE] {self.asset:>8} {self.window_min}m BUY {side} {shares:.2f} sh @ {avg:.3f} "
              f"(${spent:.2f}) {rec['elapsed_min']:.0f}m in | balance ${self.wallet.state['balance']:.2f}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Paper-trade the momentum rule with a demo wallet.")
    ap.add_argument("--windows", default="60", help="market lengths to trade (rules built in)")
    ap.add_argument("--stake", type=float, default=10.0,
                    help="demo dollars per CLOCK-WINDOW, split evenly across the assets — "
                         "the 4 cryptos move together, so the window is the real unit of risk")
    ap.add_argument("--start-balance", type=float, default=1000.0, help="wallet opening balance (first run)")
    ap.add_argument("--assets", default="Bitcoin,Ethereum,Solana,XRP")
    ap.add_argument("--status-every", type=float, default=300.0)
    args = ap.parse_args()

    windows = {int(x) for x in args.windows.split(",") if x.strip()} & set(RULES)
    assets = {a.strip().lower() for a in args.assets.split(",") if a.strip()}
    # The stake is a PER-CLOCK-WINDOW budget: BTC/ETH/SOL/XRP buckets ending at the
    # same instant are one correlated bet, so each asset gets an equal slice. This
    # keeps the dollars-at-risk per market move constant instead of 4x'ing it.
    per_asset = args.stake / max(1, len(assets))
    wallet = Wallet(args.start_balance)
    print(f"PAPER TRADER — windows {sorted(windows)}m · stake ${args.stake:g}/clock-window "
          f"(${per_asset:.2f} × {len(assets)} assets) · "
          f"balance ${wallet.state['balance']:.2f} (start ${wallet.state['start_balance']:g})")
    print(f"rules: " + " · ".join(f"{w}m: buy ≥{RULES[w][0]} in first {RULES[w][1] / 60:.0f}m"
                                  for w in sorted(windows)) + "  | SIMULATION ONLY\n")

    active: dict[str, BucketTrader] = {}
    pending: dict[str, float] = {cid: time.time() for cid in wallet.open}  # cid -> first_seen
    if pending:
        print(f"(reloaded {len(pending)} open position(s) awaiting resolution)")
    last_status = time.monotonic()
    last_resolve = 0.0

    try:
        while True:
            now = time.time()
            # --- discover new live buckets ---
            try:
                live = gamma.crypto_updown(120)
            except Exception as exc:  # noqa: BLE001
                print(f"  [warn] discovery failed: {exc}")
                live = []
            for m in live:
                cid = m.condition_id
                if cid in active or cid in wallet.traded_cids:
                    continue
                if "Up" not in m.tokens or "Down" not in m.tokens:
                    continue
                asset = m.question.split(" up or down", 1)[0].split(" Up or Down", 1)[0].strip()
                if asset.lower() not in assets:
                    continue
                end = _end_ts(m.end_date)
                win = gamma.window_minutes(m.question)
                if not end or win not in windows:
                    continue
                start = end - win * 60
                if now < start or now >= end or (now - start) > RULES[win][1]:
                    continue  # not live, or past the rule's entry window — no point watching
                try:
                    bt = BucketTrader(m, asset, win, end, wallet, per_asset)
                    bt.start()
                    active[cid] = bt
                except Exception as exc:  # noqa: BLE001
                    print(f"  [warn] could not watch {asset} {cid[:8]}: {exc}")

            # --- retire ended/expired watchers ---
            for cid in list(active):
                bt = active[cid]
                _thr, entry_max = RULES[bt.window_min]
                if now >= bt.end_ts or (not bt.entered and (now - bt.start_ts) > entry_max):
                    bt.stop()
                    if bt.entered:
                        pending[cid] = now
                    del active[cid]

            # --- settle pending positions on the real outcome ---
            if pending and now - last_resolve >= RESOLVE_RETRY_S:
                last_resolve = now
                for cid in list(pending):
                    entry = wallet.open.get(cid)
                    if entry is None:
                        del pending[cid]
                        continue
                    if now < entry["end_ts"] + 30:
                        continue  # not even closed yet
                    try:
                        winner = gamma.settled_winner(cid)
                    except Exception:  # noqa: BLE001
                        winner = None
                    if winner:
                        rec = wallet.settle(cid, winner)
                        del pending[cid]
                        if rec:
                            tag = "WIN " if rec["won"] else "LOSS"
                            print(f"[{tag}] {entry['asset']:>8} {entry['window_min']}m {entry['side']} → "
                                  f"{winner} | pnl {rec['pnl']:+.2f} | balance ${rec['balance_after']:.2f}")
                    elif now - pending[cid] > RESOLVE_GIVEUP_S:
                        wallet.abandon(cid)
                        del pending[cid]
                        print(f"  [warn] {cid[:10]} never resolved on Gamma — abandoned (investigate)")

            mono = time.monotonic()
            if mono - last_status >= args.status_every:
                last_status = mono
                st = wallet.state
                pnl = st["balance"] - st["start_balance"] + sum(e["spent"] for e in wallet.open.values())
                print(f"[status] balance ${st['balance']:.2f} · {len(wallet.open)} open "
                      f"(${sum(e['spent'] for e in wallet.open.values()):.2f} at risk) · "
                      f"realized P&L {pnl:+.2f} · watching {len(active)}")
            time.sleep(8)
    except KeyboardInterrupt:
        print("\n(stopping — open positions stay in the wallet and settle on next run)")
    finally:
        for bt in active.values():
            bt.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
