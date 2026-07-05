r"""
Reclaim disk space from the HD recordings — safely.

The raw tick recordings are huge (the 5-min ones alone ~11 GB), but every analysis
result lives in the tiny replay cache (data/updown_hd/_replay_cache, ~25 MB) plus
the resolution sidecar. Once a market length is CONCLUDED (the 5-min market proved
efficient — no edge either direction on 2,360 buckets), its raw ticks are only
needed if we ever want to re-replay with different execution params. This tool
deletes raw recordings for a chosen window length while KEEPING the cache and
sidecar, so every grid/equity/report result stays available.

Default is a DRY RUN (shows what would be deleted, frees nothing). Add --yes to
actually delete. Keeps the newest --keep files of that length as a sample.

USAGE
    .\.venv\Scripts\python.exe scripts\updown_prune.py --window-len 5           # dry run
    .\.venv\Scripts\python.exe scripts\updown_prune.py --window-len 5 --yes     # delete
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.hd import _recordings  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Delete raw HD recordings for one market length (cache kept).")
    ap.add_argument("--window-len", type=int, required=True, help="which length to prune (e.g. 5)")
    ap.add_argument("--keep", type=int, default=20, help="keep this many newest files as a sample")
    ap.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()

    victims = sorted(
        ((p, m) for p, m in _recordings() if m["window_min"] == args.window_len),
        key=lambda x: x[1].get("end_ts") or 0,
    )
    if args.keep:
        victims = victims[:-args.keep] if len(victims) > args.keep else []
    total = sum(p.stat().st_size for p, _ in victims)
    print(f"{len(victims)} {args.window_len}-min recordings selected "
          f"({total / 1e9:.2f} GB), keeping the newest {args.keep} as a sample.")
    print("Replay cache + resolution sidecar are NOT touched — all results stay available.")
    if not victims:
        return 0
    if not args.yes:
        print("\nDRY RUN — nothing deleted. Re-run with --yes to reclaim the space.")
        return 0
    freed = 0
    for p, _ in victims:
        freed += p.stat().st_size
        p.unlink()
    print(f"deleted {len(victims)} files, freed {freed / 1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
