r"""mm — one short command to drive and inspect the whole pipeline.

Run `mm help` for the cheat sheet. Designed so nothing needs a path or a URL:
it talks to the local API (:8040) and falls back to reading the on-disk state
directly when the API is down. ASCII-only output (the console is cp1255).

    mm              status dashboard (same as `mm status`)
    mm wallet       daily P&L table + recent trades
    mm log paper    live daemon output           (also: mm log rec)
    mm start        start API + recorder + paper trader (idempotent)
    mm stop paper   stop the paper trader        (also: mm stop rec / mm stop all)
    mm replay ...   exact-fill replay grids      (args passed to updown_replay.py)
    mm report       the full HD study report
    mm resolve      backfill settled winners from Gamma
    mm prune ...    reclaim disk from old raw ticks (dry-run by default)
    mm help         cheat sheet with examples
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
API = "http://localhost:8040"
TRADES = ROOT / "data" / "paper" / "trades.jsonl"
WALLET = ROOT / "data" / "paper" / "wallet.json"

HELP = """\
mm — your trading-pipeline remote control (run from ANY folder)

SEE WHAT'S HAPPENING
  mm                     status: daemons, wallet, today's P&L
  mm wallet              P&L per day + the last 12 trades
  mm wallet -n 30        ... last 30 trades
  mm log paper           what the paper trader is doing right now
  mm log rec             what the recorder is doing right now

CONTROL
  mm start               bring everything up (API + recorder + paper trader)
  mm stop paper          stop paper trading (positions settle on next start)
  mm stop rec            stop recording
  mm stop all            stop both (API stays up)

RESEARCH (the tools we used for every study)
  mm replay --window-len 60 --mode momentum --stake 1 --min-fill-frac 0.5
                         exact-fill grid: which rule made money at 60-min
  mm replay --window-len 60 --mode momentum --null
                         ... with the luck test (block bootstrap)
  mm replay --window-len 60 --mode momentum --split
                         ... first half vs second half (overfitting check)
  mm report              the full multi-window report from the cache
  mm resolve             fetch real winners from Gamma into the sidecar
  mm prune               show what old raw tick data could be deleted (safe)

RULES OF THUMB
  - the paper trader holds to resolution; scary mid-flight dips are normal
  - never run two paper traders (it refuses now, but don't try)
  - after a reboot: just run `mm start` (or install scripts\\autostart.cmd
    into shell:startup so it happens by itself)
"""


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 8):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            return {"detail": str(e)}
    except Exception:  # noqa: BLE001
        return None  # API down


def load_ledger():
    entries: dict[str, list[dict]] = defaultdict(list)
    settles: list[dict] = []
    if TRADES.exists():
        for line in TRADES.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["type"] == "entry":
                entries[r["cid"]].append(r)
            elif r["type"] == "settle":
                settles.append(r)
    return entries, settles


def cmd_status():
    h = api("/health", timeout=3)
    print("API        :", "up" if h else "DOWN (run: mm start)")
    hd = api("/hd/summary", timeout=30) if h else None  # scans thousands of files
    if hd and hd.get("recorder"):
        rec = hd["recorder"]
        state = f"recording {rec['args']['windows']}m" if rec.get("running") else "STOPPED"
        print(f"recorder   : {state} | {hd.get('buckets', '?')} buckets on disk, "
              f"{hd.get('disk_free_gb', '?')} GB free")
    ps = api("/paper/status") if h else None
    if ps:
        d = ps["daemon"]
        state = (f"trading {d['args']['windows']}m at ${d['args']['stake']:g}/window, "
                 f"up {(d['uptime_s'] or 0) / 3600:.1f}h" if d["running"] else "STOPPED")
        print(f"paper bot  : {state}")
        w = ps["wallet"]
        at_risk = sum(p["spent"] for p in ps["open_positions"])
        print(f"wallet     : ${w['balance']:.2f} (started ${w['start_balance']:g}) | "
              f"{len(ps['open_positions'])} open (${at_risk:.2f} at risk) | "
              f"{ps['trades']} settled, {ps['hit']}% won")
    # today from the ledger (works even with API down)
    entries, settles = load_ledger()
    flat = {(r["cid"], i): r for cid, rs in entries.items() for i, r in enumerate(rs)}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tp = [s["pnl"] for s in settles if s["ts"][:10] == today]
    if tp:
        print(f"today      : {len(tp)} settled, P&L {sum(tp):+.2f}")
    print("\n(mm help for all commands)")


def cmd_wallet(n_last: int = 12):
    entries, settles = load_ledger()
    ent_by_cid = {cid: rs[0] for cid, rs in entries.items()}
    if not settles:
        print("no settled trades yet")
        return
    days: dict[str, list[dict]] = defaultdict(list)
    for s in settles:
        days[s["ts"][:10]].append(s)
    print(f"{'day':>12} {'bets':>5} {'won':>5} {'win%':>6} {'P&L':>9}")
    for d in sorted(days):
        ss = days[d]
        wins = sum(1 for s in ss if s["won"])
        print(f"{d:>12} {len(ss):>5} {wins:>5} {wins / len(ss) * 100:>5.1f}% "
              f"{sum(s['pnl'] for s in ss):>+9.2f}")
    total = sum(s["pnl"] for s in settles)
    wins = sum(1 for s in settles if s["won"])
    print(f"{'TOTAL':>12} {len(settles):>5} {wins:>5} {wins / len(settles) * 100:>5.1f}% {total:>+9.2f}")
    print(f"\nlast {min(n_last, len(settles))} trades:")
    for s in settles[-n_last:]:
        e = ent_by_cid.get(s["cid"], {})
        el = e.get("elapsed_min")
        el_s = f"{el:>4.0f}m in" if el is not None else "   ?    "
        print(f"  {s['ts']} {e.get('asset', '?'):>9} {e.get('window_min', '?'):>3}m "
              f"{e.get('side', '?'):>4} @ {e.get('avg', 0):.2f} {el_s} -> "
              f"{'WIN ' if s['won'] else 'LOSS'} {s['pnl']:+.2f}")


def cmd_log(which: str, n: int = 20):
    path = "/paper/log" if which.startswith("p") else "/hd/recorder/log"
    r = api(f"{path}?lines={n}")
    if r is None:
        print("API is down - run: mm start")
        return
    for line in r.get("lines", []):
        print(line)


def cmd_start():
    if api("/health", timeout=3) is None:
        print("starting API server...")
        flags = 0x08000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([PY, "scripts/run_api.py"], cwd=ROOT, creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time
        for _ in range(30):
            time.sleep(2)
            if api("/health", timeout=3):
                break
        else:
            print("API did not come up - check logs")
            return
    print("API up")
    r = api("/hd/recorder/start", "POST",
            {"assets": ["Bitcoin", "Ethereum", "Solana", "XRP"], "windows": [15, 60]})
    print("recorder   :", "started" if r and r.get("running") else r.get("detail", r))
    r = api("/paper/start", "POST", {"windows": [60], "stake": 10})
    print("paper bot  :", "started" if r and r.get("running") else r.get("detail", r))


def cmd_stop(which: str):
    if which in ("paper", "all"):
        r = api("/paper/stop", "POST", {})
        print("paper bot  :", "stopped" if r and not r.get("running", True) else r.get("detail", r))
    if which in ("rec", "recorder", "all"):
        r = api("/hd/recorder/stop", "POST", {})
        print("recorder   :", "stopped" if r and not r.get("running", True) else r.get("detail", r))


def passthrough(script: str, args: list[str]) -> int:
    return subprocess.call([PY, str(ROOT / "scripts" / script), *args], cwd=ROOT)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    rest = args[1:]
    if cmd == "status":
        cmd_status()
    elif cmd == "wallet":
        n = int(rest[rest.index("-n") + 1]) if "-n" in rest else 12
        cmd_wallet(n)
    elif cmd == "log":
        cmd_log(rest[0] if rest else "paper", int(rest[rest.index("-n") + 1]) if "-n" in rest else 20)
    elif cmd == "start":
        cmd_start()
    elif cmd == "stop":
        cmd_stop(rest[0] if rest else "all")
    elif cmd == "replay":
        return passthrough("updown_replay.py", rest)
    elif cmd == "report":
        return passthrough("updown_hd_report.py", rest)
    elif cmd == "resolve":
        return passthrough("updown_resolve.py", rest)
    elif cmd == "prune":
        return passthrough("updown_prune.py", rest)
    elif cmd in ("help", "-h", "--help"):
        print(HELP)
    else:
        print(f"unknown command: {cmd}\n")
        print(HELP)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
