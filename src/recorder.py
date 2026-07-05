"""
Record the live market WebSocket feed to disk so it can be replayed later.

A recording is a JSON-Lines file under data/recordings/. Each line wraps one raw
WS event with the time we received it:

    {"recv_ts": "2026-06-26T21:40:03.123Z", "recv_mono": 12.34, "event": {...}}

We store the events verbatim (book snapshots and price_change deltas), so replay
can reconstruct the exact order book the strategy would have seen live — making a
backtest a faithful re-run rather than an approximation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config.settings import PROJECT_ROOT

RECORDINGS_DIR = PROJECT_ROOT / "data" / "recordings"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Recorder:
    """Append-only writer for raw WS events. Use as a context manager."""

    def __init__(self, label: str) -> None:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Keep the filename filesystem-safe (token ids are long but digit-only).
        safe = "".join(c for c in label if c.isalnum() or c in "-_")[:40]
        self.path: Path = RECORDINGS_DIR / f"rec_{safe}_{stamp}.jsonl"
        self._fh = None
        self.count = 0

    def __enter__(self) -> "Recorder":
        self._fh = self.path.open("w", encoding="utf-8")
        return self

    def write(self, event: dict) -> None:
        """Persist one raw WS event. Wire this to MarketStream(on_raw=...)."""
        rec = {"recv_ts": _now_iso(), "event": event}
        self._fh.write(json.dumps(rec) + "\n")
        self._fh.flush()
        self.count += 1

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            self._fh.close()
