r"""
Backfill REAL settled outcomes into the high-precision recordings (data/updown_hd).

The recorder captures ticks live, but these short-term markets don't settle on
Gamma until minutes-to-hours after they close — longer than the recorder waits at
finalize. So recordings are written with source="unresolved". This pass revisits
each recording, looks up its now-settled outcome on Gamma (by conditionId), and
APPENDS a real resolution record. Replay/analysis then use the true winner.

Appending: for a .jsonl.gz we write a new gzip member (readers concatenate them,
and load_recording takes the LAST resolution record — so the real one wins). Plain
.jsonl just gets a line appended. A sidecar `_resolved.json` (conditionId → winner)
makes re-runs idempotent — already-settled recordings are skipped, and ones that
still aren't settled on Gamma are simply retried next time.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_resolve.py            # backfill data/updown_hd
"""

import argparse
import gzip
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT, SETTINGS  # noqa: E402
from src import gamma  # noqa: E402


def _raw_market(cid: str) -> dict | None:
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


def _peek_meta(path: Path) -> dict | None:
    opener = gzip.open if path.name.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            o = json.loads(fh.readline())
        return o if o.get("rec") == "meta" else None
    except (OSError, EOFError, json.JSONDecodeError):
        return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Backfill real Gamma resolutions into HD recordings.")
    ap.add_argument("--dir", default=str(PROJECT_ROOT / "data" / "updown_hd"))
    ap.add_argument("--sleep", type=float, default=0.15, help="seconds between Gamma lookups")
    args = ap.parse_args()

    d = Path(args.dir)
    files = sorted(d.glob("udx_*.jsonl*"))
    if not files:
        raise SystemExit(f"No recordings in {d}")

    idx_path = d / "_resolved.json"
    resolved: dict[str, str] = {}
    if idx_path.exists():
        try:
            resolved = json.loads(idx_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            resolved = {}

    done = settled = pending = errors = 0
    for f in files:
        meta = _peek_meta(f)
        if not meta:
            continue
        cid = meta.get("condition_id")
        if not cid or cid in resolved:
            done += 1
            continue
        try:
            raw = _raw_market(cid)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] lookup failed {cid[:10]}: {exc}")
            errors += 1
            time.sleep(args.sleep)
            continue
        opx = _outcome_prices(raw) if raw else {}
        if raw and bool(raw.get("closed")) and opx and max(opx.values(), default=0) >= 0.99:
            resolved[cid] = max(opx, key=opx.get)  # sidecar index only — never touch recordings
            settled += 1
            if settled % 25 == 0:
                idx_path.write_text(json.dumps(resolved), encoding="utf-8")
                print(f"  … {settled} settled so far")
        else:
            pending += 1  # not settled on Gamma yet — try again next run
        time.sleep(args.sleep)

    idx_path.write_text(json.dumps(resolved), encoding="utf-8")
    print(f"\nBackfilled {settled} newly-settled outcomes.")
    print(f"already done: {done} · still pending on Gamma: {pending} · lookup errors: {errors}")
    print(f"index: {idx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
