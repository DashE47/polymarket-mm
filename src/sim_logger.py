"""
Logging for simulated market-making runs.

Two outputs at once:
  * Human-readable lines to the console, so you can watch what's happening.
  * A machine-readable JSON-Lines file in logs/ (one JSON object per line), so a
    run can be replayed/analysed later (Phase 5 reads these).

Every event the engine emits — a quote, a simulated fill, a risk halt — flows
through here. Keeping all logging in one place means the event schema stays
consistent and easy to change.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT

LOGS_DIR = PROJECT_ROOT / "logs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class SimLogger:
    def __init__(self, token_id: str, params: dict[str, Any],
                 quiet: bool = False, to_file: bool = True) -> None:
        """`quiet` silences console output; `to_file` toggles the JSONL file.

        Sweeps run many backtests, so they use quiet + no file and read the
        in-memory `self.events` list for analytics instead.
        """
        self.quiet = quiet
        self.events: list[dict] = []  # full in-memory record for analytics
        # The engine sets this to the current book timestamp (ms) before each
        # log call, so events carry MARKET time. That makes duration / fills-per
        # -minute correct for backtests (where wall-clock replay time is
        # meaningless — a day of data can replay in under a second).
        self.mkt_ts: int | None = None
        self._fh = None
        self.path = None
        if to_file:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.path = LOGS_DIR / f"mm_{stamp}.jsonl"
            self._fh = self.path.open("w", encoding="utf-8")
        self.event("run_start", token_id=token_id, params=params)
        if not quiet and self.path:
            print(f"[log] writing run to {self.path}")

    def _say(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    # --- generic event ----------------------------------------------------

    def event(self, etype: str, **fields: Any) -> dict:
        rec = {"ts": _now_iso(), "mono": round(time.monotonic(), 4), "type": etype, **fields}
        if self.mkt_ts is not None:
            rec["mkt_ts"] = self.mkt_ts
        self.events.append(rec)
        if self._fh is not None:
            self._fh.write(json.dumps(rec) + "\n")
            self._fh.flush()
        return rec

    # --- typed helpers (also print a friendly line) -----------------------

    def quote(self, bid, ask, size, mid, position, pnl) -> None:
        self.event(
            "quote", bid=bid, ask=ask, size=size, mid=round(mid, 6),
            position=round(position, 4), pnl=round(pnl, 6),
        )
        b = f"{bid:.4f}" if bid is not None else "  -  "
        a = f"{ask:.4f}" if ask is not None else "  -  "
        self._say(f"  quote   bid {b} / ask {a}  x{size:g}   "
                  f"(mid {mid:.4f}, pos {position:+.1f}, pnl {pnl:+.4f})")

    def fill(self, side, price, size, mid, position, avg_price, realized) -> None:
        self.event(
            "fill", side=side, price=round(price, 6), size=size, mid=round(mid, 6),
            position=round(position, 4), avg_price=round(avg_price, 6),
            realized_pnl=round(realized, 6),
        )
        # ASCII-only so the console print never hits an encoding error on
        # non-UTF-8 Windows codepages (the JSON file keeps the full record).
        arrow = "BUY " if side == "BUY" else "SELL"
        self._say(f"  FILL {arrow} {size:g} @ {price:.4f}   "
                  f"-> pos {position:+.1f} @ avg {avg_price:.4f}, realized {realized:+.4f}")

    def halt(self, reason: str) -> None:
        self.event("halt", reason=reason)
        self._say(f"  !! HALT: {reason}")

    def status(self, mid, position, exposure, realized, unrealized) -> None:
        self.event(
            "status", mid=round(mid, 6), position=round(position, 4),
            exposure=round(exposure, 4), realized_pnl=round(realized, 6),
            unrealized_pnl=round(unrealized, 6), total_pnl=round(realized + unrealized, 6),
        )
        self._say(f"  - status mid {mid:.4f} | pos {position:+.1f} "
                  f"(${exposure:.2f}) | realized {realized:+.4f} "
                  f"| unrealized {unrealized:+.4f} | total {realized + unrealized:+.4f}")

    def close(self) -> None:
        self.event("run_end")
        if self._fh is not None:
            self._fh.close()
