r"""
Parallel prewarm of the HD replay cache — replay every finished recording ONCE,
across all CPU cores, so the web grids and the report are instant afterwards.

Each recording is independent and replay is CPU-bound (JSON + book reconstruction),
so we fan out across a process pool. Both fade and momentum, all entry windows, are
computed in a single pass per file (see api.hd._replay_one) and cached under
data/updown_hd/_replay_cache/ keyed by the execution-parameter hash.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_prewarm.py                 # default params
    .\.venv\Scripts\python.exe scripts\updown_prewarm.py --latency-ms 300 --workers 6
"""

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _work(job):
    """Worker: replay one file in both modes and write its cache. Returns 1/0."""
    path_str, meta, phash, cfgd = job
    from api.hd import _cache_path, _replay_one
    from src.updown_replay import FillCfg
    p = Path(path_str)
    if _cache_path(p, phash).exists():
        return 0
    try:
        _replay_one(p, meta, FillCfg(**cfgd), phash)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[prewarm] {p.name}: {exc}")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Parallel prewarm of the HD replay cache.")
    ap.add_argument("--stake", type=float, default=1.0)
    ap.add_argument("--max-spread", type=float, default=0.05)
    ap.add_argument("--latency-ms", type=float, default=0.0)
    ap.add_argument("--min-fill-frac", type=float, default=0.0)
    ap.add_argument("--workers", type=int, default=6, help="process pool size (leave cores for the recorder/OS)")
    args = ap.parse_args()

    from api.hd import _cache_path, _finished, _phash, _recordings
    cfgd = {"stake": args.stake, "max_spread": args.max_spread,
            "latency_ms": args.latency_ms, "min_fill_frac": args.min_fill_frac}
    phash = _phash(args.stake, args.max_spread, args.latency_ms, args.min_fill_frac)

    todo = [(str(p), m, phash, cfgd) for p, m in _recordings()
            if _finished(m) and not _cache_path(p, phash).exists()]
    total = len(todo)
    print(f"prewarm phash={phash} · {total} uncached finished recordings · {args.workers} workers")
    if not total:
        print("nothing to do — cache is complete for these params.")
        return 0

    done = fresh = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_work, j) for j in todo]
        for f in as_completed(futs):
            fresh += f.result()
            done += 1
            if done % 100 == 0 or done == total:
                rate = done / max(1e-9, time.time() - t0)
                eta = (total - done) / max(1e-9, rate)
                print(f"  {done}/{total}  ({rate:.1f}/s, eta {eta/60:.1f} min)")
    print(f"done — {fresh} newly cached in {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
