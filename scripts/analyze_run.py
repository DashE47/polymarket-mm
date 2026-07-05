r"""
Analyse a single market-making run and save charts.

USAGE
    # analyse the most recent run in logs/
    .\.venv\Scripts\python.exe scripts\analyze_run.py

    # analyse a specific log
    .\.venv\Scripts\python.exe scripts\analyze_run.py logs\mm_20260626_223340.jsonl

Prints the performance scorecard and writes a PNG (P&L / inventory / price) to
reports/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT  # noqa: E402
from src.analytics import compute_metrics, load_events  # noqa: E402
from src.charts import save_run_charts  # noqa: E402


def _latest_log() -> Path:
    logs = sorted((PROJECT_ROOT / "logs").glob("mm_*.jsonl"))
    if not logs:
        raise SystemExit("No logs found. Run run_market_maker.py or backtest.py first.")
    return logs[-1]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_log()
    print(f"Analysing {path.name}\n")

    events = load_events(path)
    m = compute_metrics(events)

    print("PERFORMANCE SCORECARD")
    print(f"  total P&L          : {m.total_pnl:+.4f} pUSD")
    print(f"    realized         : {m.realized_pnl:+.4f}")
    print(f"    unrealized       : {m.unrealized_pnl:+.4f}")
    print(f"  fills              : {m.fills}  ({m.buys} buys / {m.sells} sells)")
    print(f"  fills per minute   : {m.fills_per_min:.2f}")
    print(f"  closing trades     : {m.closing_trades}")
    print(f"  win rate           : {m.win_rate:.1%}")
    print(f"  avg spread captured: {m.avg_spread_captured:+.5f} pUSD / closing trade")
    print(f"  max |inventory|    : {m.max_abs_inventory:.0f} shares")
    print(f"  max drawdown       : {m.max_drawdown:.4f} pUSD")
    print(f"  Sharpe (per-step)  : {m.sharpe:.3f}")
    print(f"  duration           : {m.duration_min:.2f} min")
    if m.halted:
        print(f"  HALTED             : {m.halt_reason}")

    chart = save_run_charts(m, name=path.stem, title=path.name)
    print(f"\nchart saved -> {chart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
