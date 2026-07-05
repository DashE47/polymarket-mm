r"""
Paper-trader endpoints: start/stop the demo-wallet daemon from the site and read
its wallet, positions, trade history and equity curve. The daemon is a subprocess
(scripts/updown_paper.py) so it survives API restarts and can equally be run from
a terminal — this API just manages and reads its on-disk state. Simulation only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import PROJECT_ROOT

router = APIRouter(prefix="/paper", tags=["paper-trading"])

PAPER_DIR = PROJECT_ROOT / "data" / "paper"


class _Daemon:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.log: deque[str] = deque(maxlen=400)
        self.args: dict | None = None
        self.started: float | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, windows: list[int], stake: float) -> None:
        cmd = [sys.executable, "-u", str(PROJECT_ROOT / "scripts" / "updown_paper.py"),
               "--windows", ",".join(map(str, windows)), "--stake", str(stake)]
        self.proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1)
        self.args = {"windows": windows, "stake": stake}
        self.started = time.time()
        self.log.clear()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.log.append(line.rstrip())
        self.log.append(f"[paper trader exited, code {proc.poll()}]")

    def stop(self) -> None:
        if self.running:
            self.proc.terminate()  # open positions persist and settle on next start
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def status(self) -> dict:
        return {"running": self.running,
                "uptime_s": round(time.time() - self.started) if self.running and self.started else None,
                "args": self.args if self.running else None}


_daemon = _Daemon()


class PaperStart(BaseModel):
    windows: list[int] = [15, 60]
    stake: float = 10.0


@router.post("/start")
def paper_start(req: PaperStart) -> dict:
    if _daemon.running:
        raise HTTPException(status_code=409, detail="paper trader already running")
    _daemon.start(req.windows, req.stake)
    return _daemon.status()


@router.post("/stop")
def paper_stop() -> dict:
    if not _daemon.running:
        raise HTTPException(status_code=409, detail="paper trader is not running")
    _daemon.stop()
    return _daemon.status()


@router.get("/log")
def paper_log(lines: int = 30) -> dict:
    return {"lines": list(_daemon.log)[-lines:]}


@router.get("/status")
def paper_status() -> dict:
    """Wallet + positions + recent trades + realized equity curve, from disk."""
    wallet_path = PAPER_DIR / "wallet.json"
    trades_path = PAPER_DIR / "trades.jsonl"
    wallet = json.loads(wallet_path.read_text(encoding="utf-8")) if wallet_path.exists() else None

    entries: dict[str, dict] = {}
    settles: list[dict] = []
    if trades_path.exists():
        with trades_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec["type"] == "entry":
                    entries[rec["cid"]] = rec
                elif rec["type"] == "settle":
                    settles.append(rec)
                elif rec["type"] == "abandon":
                    entries.pop(rec["cid"], None)

    settled_cids = {s["cid"] for s in settles}
    open_positions = [e for cid, e in entries.items() if cid not in settled_cids]
    wins = sum(1 for s in settles if s["won"])
    realized = sum(s["pnl"] for s in settles)

    # Trade history rows (settles joined with their entries), newest first.
    history = []
    for s in settles[-60:]:
        e = entries.get(s["cid"], {})
        history.append({"ts": s["ts"], "asset": e.get("asset"), "window_min": e.get("window_min"),
                        "side": e.get("side"), "avg": e.get("avg"), "spent": e.get("spent"),
                        "winner": s["winner"], "won": s["won"], "pnl": s["pnl"],
                        "balance_after": s["balance_after"]})
    history.reverse()

    return {
        "daemon": _daemon.status(),
        "wallet": wallet,
        "open_positions": [{k: e.get(k) for k in ("ts", "asset", "window_min", "side", "shares",
                                                  "spent", "avg", "end_ts", "question")}
                           for e in sorted(open_positions, key=lambda x: x.get("ts_unix") or 0)],
        "trades": len(settles),
        "wins": wins,
        "hit": round(wins / len(settles) * 100, 1) if settles else None,
        "realized_pnl": round(realized, 2),
        "history": history,
        "equity": [{"ts": s["ts"], "balance": s["balance_after"]} for s in settles],
    }
