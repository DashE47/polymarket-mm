r"""
HD research endpoints: everything the web UI needs to run the high-precision
Up/Down pipeline (record → resolve → exact-fill replay) without a terminal.

Design notes
  * REPLAY CACHE — a full tick replay of one bucket costs seconds (JSON-parsing up
    to ~100k events), so the grid endpoint never replays on demand. A background
    job replays each recording ONCE per execution-parameter set and caches the
    per-rule entry details (side, avg price, spent, shares, slippage …) under
    data/updown_hd/_replay_cache/. Both modes (fade + momentum) are computed in
    the same pass, and win/loss is NOT baked in — the grid joins the cached
    entries with the settled winners (sidecar _resolved.json) at request time, so
    re-resolving never requires re-replaying. New recordings only cost themselves.
  * RECORDER — the site can start/stop scripts/updown_record.py as a subprocess
    and tail its output. Stop is a hard kill (Windows): in-flight buckets keep
    their ticks (gzip tail is tolerated by the reader) and get their winner from
    the resolver afterwards, so nothing of value is lost.
  * DEDUPE — if two recorders ever overlap (site + terminal), the same bucket can
    exist in two files; aggregation dedupes by condition_id keeping the fuller one.

Simulation only: nothing here places orders.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import PROJECT_ROOT, SETTINGS
from src import gamma
from src.updown_replay import (
    FADE_THRESHOLDS, MOMENTUM_THRESHOLDS, FillCfg, entry_windows, load_recording,
    peek_meta, replay_bucket,
)

router = APIRouter(prefix="/hd", tags=["hd-research"])

HD_DIR = PROJECT_ROOT / "data" / "updown_hd"
CACHE_DIR = HD_DIR / "_replay_cache"
SIDECAR = HD_DIR / "_resolved.json"
CACHE_VERSION = 1       # bump to invalidate all caches when replay logic changes
FINISHED_GRACE = 90.0   # only replay files whose bucket ended ≥ this many s ago
MIN_SAMPLE = 10


# --- small shared helpers ---------------------------------------------------

def _sidecar() -> dict[str, str]:
    if SIDECAR.exists():
        try:
            return json.loads(SIDECAR.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _raw_closed_market(cid: str) -> dict | None:
    # closed=true is REQUIRED — Gamma's /markets hides settled markets by default.
    data = gamma.get_json(f"{SETTINGS.gamma_host}/markets",
                          params={"condition_ids": cid, "closed": "true", "limit": 1})
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


# Meta peeks are cached by (name, size, mtime) so summary polling stays cheap.
_meta_cache: dict[str, tuple[float, int, dict]] = {}


def _file_meta(p: Path) -> dict | None:
    st = p.stat()
    hit = _meta_cache.get(p.name)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    m = peek_meta(p)
    if not m:
        return None
    small = {"window_min": m.get("window_min"), "asset": m.get("asset"),
             "cid": m.get("condition_id"), "end_ts": m.get("end_ts"),
             "question": m.get("question")}
    _meta_cache[p.name] = (st.st_mtime, st.st_size, small)
    return small


def _recordings() -> list[tuple[Path, dict]]:
    if not HD_DIR.exists():
        return []
    out = []
    for p in sorted(HD_DIR.glob("udx_*.jsonl*")):
        m = _file_meta(p)
        if m:
            out.append((p, m))
    return out


# --- recorder control (one site-managed subprocess) -------------------------

class _Recorder:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.log: deque[str] = deque(maxlen=400)
        self.args: dict | None = None
        self.started: float | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, assets: list[str], windows: list[int]) -> None:
        # -u: unbuffered child stdout, so the live log tail updates line-by-line
        cmd = [sys.executable, "-u", str(PROJECT_ROOT / "scripts" / "updown_record.py"),
               "--assets", ",".join(assets), "--windows", ",".join(map(str, windows)),
               "--duration", "0", "--status-every", "60"]
        self.proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1)
        self.args = {"assets": assets, "windows": windows}
        self.started = time.time()
        self.log.clear()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.log.append(line.rstrip())
        self.log.append(f"[recorder exited, code {proc.poll()}]")

    def stop(self) -> None:
        if self.running:
            self.proc.terminate()  # hard kill; ticks are safe, resolver supplies winners
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def status(self) -> dict:
        return {
            "running": self.running,
            "pid": self.proc.pid if self.running else None,
            "uptime_s": round(time.time() - self.started) if self.running and self.started else None,
            "args": self.args if self.running else None,
        }


_recorder = _Recorder()


class RecorderStart(BaseModel):
    assets: list[str] = ["Bitcoin", "Ethereum", "Solana", "XRP"]
    windows: list[int] = [15, 60]  # 5-min proven efficient — record it only on purpose


@router.post("/recorder/start")
def recorder_start(req: RecorderStart) -> dict:
    if _recorder.running:
        raise HTTPException(status_code=409, detail="the site recorder is already running")
    if not req.assets or not req.windows:
        raise HTTPException(status_code=400, detail="pick at least one asset and one window")
    _recorder.start(req.assets, req.windows)
    return _recorder.status()


@router.post("/recorder/stop")
def recorder_stop() -> dict:
    if not _recorder.running:
        raise HTTPException(status_code=409, detail="no site recorder running")
    _recorder.stop()
    return _recorder.status()


@router.get("/recorder/log")
def recorder_log(lines: int = 30) -> dict:
    return {"lines": list(_recorder.log)[-lines:]}


# --- resolver (backfill settled winners into the sidecar) -------------------

_resolve_job = {"running": False, "checked": 0, "settled": 0, "pending": 0, "error": None}


def _resolve_worker() -> None:
    try:
        resolved = _sidecar()
        recs = _recordings()
        todo = [(p, m) for p, m in recs if m["cid"] and m["cid"] not in resolved]
        _resolve_job.update(checked=0, settled=0, pending=0)
        for _p, m in todo:
            try:
                raw = _raw_closed_market(m["cid"])
            except Exception:  # noqa: BLE001 - network hiccup: count as pending, keep going
                _resolve_job["pending"] += 1
                _resolve_job["checked"] += 1
                continue
            opx = _outcome_prices(raw) if raw else {}
            if raw and bool(raw.get("closed")) and opx and max(opx.values(), default=0) >= 0.99:
                resolved[m["cid"]] = max(opx, key=opx.get)
                _resolve_job["settled"] += 1
                if _resolve_job["settled"] % 25 == 0:
                    SIDECAR.write_text(json.dumps(resolved), encoding="utf-8")
            else:
                _resolve_job["pending"] += 1
            _resolve_job["checked"] += 1
            time.sleep(0.12)  # be polite to Gamma
        SIDECAR.write_text(json.dumps(resolved), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _resolve_job["error"] = str(exc)
    finally:
        _resolve_job["running"] = False


@router.post("/resolve/start")
def resolve_start() -> dict:
    if _resolve_job["running"]:
        raise HTTPException(status_code=409, detail="resolver already running")
    _resolve_job.update(running=True, error=None)
    threading.Thread(target=_resolve_worker, daemon=True).start()
    return _resolve_job


@router.get("/resolve/status")
def resolve_status() -> dict:
    return _resolve_job


# --- replay cache job --------------------------------------------------------

_replay_job = {"running": False, "done": 0, "total": 0, "fresh": 0, "error": None, "phash": None}


def _phash(stake: float, max_spread: float, latency_ms: float, min_fill_frac: float) -> str:
    key = json.dumps({"v": CACHE_VERSION, "stake": stake, "spread": max_spread,
                      "lat": latency_ms, "mff": min_fill_frac}, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()[:10]


def _cache_path(p: Path, phash: str) -> Path:
    stem = p.name.split(".jsonl")[0]
    return CACHE_DIR / f"{stem}.{phash}.json"


def _finished(m: dict) -> bool:
    end = m.get("end_ts")
    return bool(end) and (time.time() - end) >= FINISHED_GRACE


def _entry_slim(res: dict) -> dict | None:
    if not res.get("entered"):
        return None
    return {k: res.get(k) for k in ("side", "shares", "spent", "avg", "fill_frac",
                                    "slippage", "elapsed")}


def _replay_one(p: Path, m: dict, cfg: FillCfg, phash: str) -> None:
    """Replay one finished recording in BOTH modes and cache slim entry results."""
    meta, events, _res = load_recording(p)
    if not meta or not events:
        return
    windows = entry_windows(m["window_min"])
    out = {"cid": m["cid"], "asset": m["asset"], "window_min": m["window_min"],
           "end_ts": m["end_ts"], "n_events": len(events), "modes": {}}
    for mode, thresholds in (("fade", FADE_THRESHOLDS), ("momentum", MOMENTUM_THRESHOLDS)):
        rules = [(thr, w) for thr in thresholds for w in windows]
        results = replay_bucket(meta, events, None, rules, cfg, mode=mode)
        out["modes"][mode] = {f"{thr:.2f}|{w}": _entry_slim(r) for (thr, w), r in results.items()}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(p, phash).write_text(json.dumps(out), encoding="utf-8")


def _replay_worker(cfg: FillCfg, phash: str) -> None:
    try:
        todo = [(p, m) for p, m in _recordings() if _finished(m)]
        _replay_job.update(done=0, fresh=0, total=len(todo))
        for p, m in todo:
            if not _cache_path(p, phash).exists():
                try:
                    _replay_one(p, m, cfg, phash)
                    _replay_job["fresh"] += 1
                except Exception as exc:  # noqa: BLE001 - one bad file shouldn't kill the job
                    print(f"[hd] replay failed for {p.name}: {exc}")
            _replay_job["done"] += 1
    except Exception as exc:  # noqa: BLE001
        _replay_job["error"] = str(exc)
    finally:
        _replay_job["running"] = False


class ReplayStart(BaseModel):
    stake: float = 1.0
    max_spread: float = 0.05
    latency_ms: float = 0.0
    min_fill_frac: float = 0.0


@router.post("/replay/start")
def replay_start(req: ReplayStart) -> dict:
    if _replay_job["running"]:
        raise HTTPException(status_code=409, detail="a replay job is already running")
    cfg = FillCfg(stake=req.stake, max_spread=req.max_spread,
                  latency_ms=req.latency_ms, min_fill_frac=req.min_fill_frac)
    ph = _phash(req.stake, req.max_spread, req.latency_ms, req.min_fill_frac)
    _replay_job.update(running=True, error=None, phash=ph, done=0, total=0, fresh=0)
    threading.Thread(target=_replay_worker, args=(cfg, ph), daemon=True).start()
    return _replay_job


@router.get("/replay/status")
def replay_status() -> dict:
    return _replay_job


# --- aggregation: grid + equity ---------------------------------------------

def _cached_entries(window_len: int, phash: str) -> tuple[list[dict], int, int]:
    """Load cached per-bucket results for finished `window_len` recordings.

    Returns (rows, cached, total). Dedupes by condition_id keeping the recording
    with the most events (protects against overlapping site+terminal recorders).
    """
    total = cached = 0
    by_cid: dict[str, dict] = {}
    for p, m in _recordings():
        if m["window_min"] != window_len or not _finished(m):
            continue
        total += 1
        cp = _cache_path(p, phash)
        if not cp.exists():
            continue
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        cached += 1
        prev = by_cid.get(data["cid"])
        if prev is None or data.get("n_events", 0) > prev.get("n_events", 0):
            by_cid[data["cid"]] = data
    return list(by_cid.values()), cached, total


@router.get("/replay/grid")
def replay_grid(mode: str = "momentum", window_len: int = 5, stake: float = 1.0,
                max_spread: float = 0.05, latency_ms: float = 0.0,
                min_fill_frac: float = 0.0) -> dict:
    if mode not in ("fade", "momentum"):
        raise HTTPException(status_code=400, detail="mode must be fade or momentum")
    ph = _phash(stake, max_spread, latency_ms, min_fill_frac)
    entries, cached, total = _cached_entries(window_len, ph)
    winners = _sidecar()
    thresholds = MOMENTUM_THRESHOLDS if mode == "momentum" else FADE_THRESHOLDS
    windows = entry_windows(window_len)

    agg: dict[str, dict] = {}
    settled_buckets = 0
    for e in entries:
        win_side = winners.get(e["cid"])
        if win_side:
            settled_buckets += 1
        for key, r in e["modes"].get(mode, {}).items():
            a = agg.setdefault(key, {"entered": 0, "n": 0, "wins": 0, "pnl": 0.0,
                                     "paid": 0.0, "fill": 0.0, "slip": 0.0})
            if not r:
                continue
            a["entered"] += 1
            if not win_side:
                continue
            won = r["side"] == win_side
            a["n"] += 1
            a["wins"] += 1 if won else 0
            a["pnl"] += (r["shares"] - r["spent"]) if won else -r["spent"]
            a["paid"] += r["avg"]
            a["fill"] += r["fill_frac"]
            a["slip"] += r["slippage"] or 0.0

    cells = []
    for thr in thresholds:
        for w in windows:
            a = agg.get(f"{thr:.2f}|{w}")
            n = a["n"] if a else 0
            if a and n:
                hit = a["wins"] / n * 100
                paid = a["paid"] / n * 100
                cells.append({"thr": thr, "win": w, "bets": n, "entered": a["entered"],
                              "hit": round(hit, 1), "paid": round(paid, 1),
                              "edge": round(hit - paid, 2),
                              "pnl_per_bet": round(a["pnl"] / n / stake, 4),
                              "fill": round(a["fill"] / n * 100, 1),
                              "slip_c": round(a["slip"] / n * 100, 2)})
            else:
                cells.append({"thr": thr, "win": w, "bets": 0,
                              "entered": a["entered"] if a else 0, "hit": None, "paid": None,
                              "edge": None, "pnl_per_bet": None, "fill": None, "slip_c": None})
    return {"mode": mode, "window_len": window_len, "thresholds": thresholds,
            "windows": windows, "cells": cells, "cached": cached, "total": total,
            "complete": cached >= total, "buckets_settled": settled_buckets,
            "min_sample": MIN_SAMPLE}


@router.get("/replay/equity")
def replay_equity(thr: float, win: int, mode: str = "momentum", window_len: int = 5,
                  stake: float = 1.0, max_spread: float = 0.05, latency_ms: float = 0.0,
                  min_fill_frac: float = 0.0) -> dict:
    ph = _phash(stake, max_spread, latency_ms, min_fill_frac)
    entries, _cached, _total = _cached_entries(window_len, ph)
    winners = _sidecar()
    key = f"{thr:.2f}|{win}"
    rows = []
    for e in entries:
        r = e["modes"].get(mode, {}).get(key)
        win_side = winners.get(e["cid"])
        if not r or not win_side:
            continue
        won = r["side"] == win_side
        pnl = ((r["shares"] - r["spent"]) if won else -r["spent"]) / stake
        rows.append({"end_ts": e["end_ts"], "asset": e["asset"], "side": r["side"],
                     "avg": round(r["avg"], 4), "won": won, "pnl": round(pnl, 4)})
    rows.sort(key=lambda x: x["end_ts"] or 0)
    cum = peak = maxdd = 0.0
    wins = 0
    series = []
    for r in rows:
        cum += r["pnl"]
        wins += 1 if r["won"] else 0
        peak = max(peak, cum)
        maxdd = max(maxdd, peak - cum)
        series.append(round(cum, 3))
    n = len(rows)
    return {"thr": thr, "win": win, "mode": mode, "n": n, "wins": wins,
            "hit": round(wins / n * 100, 1) if n else None,
            "final": round(cum, 2), "per_bet": round(cum / n, 4) if n else None,
            "max_drawdown": round(maxdd, 2), "cum": series, "rows": rows[-40:]}


# --- summary ------------------------------------------------------------------

@router.get("/summary")
def summary() -> dict:
    recs = _recordings()
    winners = _sidecar()
    by_window: dict[int, int] = {}
    by_asset: dict[str, int] = {}
    resolved = 0
    newest_end = None
    for _p, m in recs:
        by_window[m["window_min"]] = by_window.get(m["window_min"], 0) + 1
        by_asset[m["asset"]] = by_asset.get(m["asset"], 0) + 1
        if m["cid"] in winners:
            resolved += 1
        if m["end_ts"] and (newest_end is None or m["end_ts"] > newest_end):
            newest_end = m["end_ts"]
    files = list(HD_DIR.glob("udx_*.jsonl*")) if HD_DIR.exists() else []
    size_mb = sum(f.stat().st_size for f in files) / 1e6
    now = time.time()
    recent_writes = sum(1 for f in files if now - f.stat().st_mtime < 120)
    du = shutil.disk_usage(HD_DIR if HD_DIR.exists() else PROJECT_ROOT)
    return {
        "buckets": len(recs), "by_window": dict(sorted(by_window.items())),
        "by_asset": by_asset, "resolved": resolved, "unresolved": len(recs) - resolved,
        "size_mb": round(size_mb, 1), "disk_free_gb": round(du.free / 1e9, 1),
        "newest_end_ts": newest_end, "recent_writes": recent_writes,
        "recorder": _recorder.status(), "resolver": _resolve_job, "replay": _replay_job,
    }
