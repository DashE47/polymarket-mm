r"""
Parameter sweep (CLI): run the strategy across many settings on the SAME data
and compare. The sweep itself lives in src/runner.run_sweep so the UI and CLI
share identical logic; this script just handles args and presents the results.

USAGE
    .\.venv\Scripts\python.exe scripts\sweep.py --recording data\recordings\rec_....jsonl `
        --spreads 0.004,0.01,0.02,0.04 --sizes 50,100 --skews 0,0.002,0.01
    .\.venv\Scripts\python.exe scripts\sweep.py 0x<conditionId> --outcome Up --history `
        --interval 6h --fidelity 1 --spreads 0.01,0.02,0.04 --skews 0,0.005
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src import runner  # noqa: E402
from src.charts import REPORTS_DIR, save_sweep_chart  # noqa: E402
from src.gamma import resolve_token  # noqa: E402
from src.history import VALID_INTERVALS  # noqa: E402


def _floats(csv: str) -> list[float]:
    return [float(x) for x in csv.split(",") if x.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description="Sweep strategy parameters.")
    p.add_argument("target", nargs="?", help="token id or 0x… conditionId (history mode)")
    p.add_argument("--recording", help="path to a recording")
    p.add_argument("--history", action="store_true")
    p.add_argument("--outcome", default="Yes")
    p.add_argument("--interval", default="1d")
    p.add_argument("--fidelity", type=int, default=5)
    p.add_argument("--spreads", default="0.004,0.01,0.02,0.04")
    p.add_argument("--sizes", default="50")
    p.add_argument("--skews", default="0,0.002,0.01")
    p.add_argument("--widen", type=float, default=0.005)
    p.add_argument("--requote", type=float, default=0.002)
    args = p.parse_args()

    # Resolve the data source into kwargs for runner.run_sweep.
    if args.recording:
        source = f"recording {Path(args.recording).name}"
        src_kwargs = {"recording": args.recording}
    elif args.history and args.target:
        if args.interval not in VALID_INTERVALS:
            raise SystemExit(f"--interval must be one of {sorted(VALID_INTERVALS)}")
        try:
            token_id, _ = resolve_token(args.target, args.outcome)
        except ValueError as e:
            raise SystemExit(str(e))
        source = f"history {args.interval}@{args.fidelity}m"
        src_kwargs = {"token_id": token_id, "interval": args.interval, "fidelity": args.fidelity}
    else:
        raise SystemExit("Provide --recording <path>, or <target> with --history.")

    spreads, sizes, skews = _floats(args.spreads), _floats(args.sizes), _floats(args.skews)
    print(f"Sweeping {len(spreads) * len(sizes) * len(skews)} combinations over {source} ...\n")

    df = runner.run_sweep(
        spreads=spreads, sizes=sizes, skews=skews,
        widen=args.widen, requote=args.requote, **src_kwargs,
    )

    print("=" * 78)
    print("SWEEP RESULTS (ranked by total P&L)")
    print("=" * 78)
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(df.to_string(index=False))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = REPORTS_DIR / f"sweep_{stamp}.csv"
    df.to_csv(csv_path, index=False)
    labels = [f"s{r.spread}/z{r.size:g}/k{r.skew}" for r in df.itertuples()]
    chart = save_sweep_chart(labels[::-1], list(df["total_pnl"])[::-1], f"sweep_{stamp}")

    print(f"\nbest: {df.iloc[0].to_dict()}")
    print(f"CSV   -> {csv_path}")
    print(f"chart -> {chart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
