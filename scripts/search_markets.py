r"""
Search Polymarket markets by keyword and show their Yes/No token ids.

USAGE
    .\.venv\Scripts\python.exe scripts\search_markets.py "bitcoin"
    .\.venv\Scripts\python.exe scripts\search_markets.py "world cup" --all --limit 30

For each match it prints the question, the conditionId, and the per-outcome
token ids. Copy a token id into live_view.py to watch that book live.

Public, read-only: no key, no orders.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gamma import search_markets  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Polymarket markets.")
    parser.add_argument("keyword", help="text to search for, e.g. bitcoin")
    parser.add_argument("--limit", type=int, default=20, help="max results")
    parser.add_argument(
        "--all",
        action="store_true",
        help="include closed / non-tradeable markets (default: tradeable only)",
    )
    args = parser.parse_args()

    markets = search_markets(
        args.keyword, limit=args.limit, tradeable_only=not args.all
    )

    if not markets:
        print(f"No {'matching' if args.all else 'tradeable'} markets for "
              f"{args.keyword!r}. Try --all or a different keyword.")
        return 0

    print(f"\nFound {len(markets)} market(s) for {args.keyword!r} "
          f"(most-traded first):\n")
    for i, m in enumerate(markets, 1):
        status = "tradeable" if m.tradeable else "closed/inactive"
        print(f"[{i}] {m.question}")
        print(f"     volume    : ${m.volume:,.0f}   ({status})")
        print(f"     condition : {m.condition_id}")
        for outcome, tid in m.tokens.items():
            print(f"     {outcome:<3} token : {tid}")
        print()

    print("Tip: watch one live with:")
    first_tid = next(iter(markets[0].tokens.values()))
    print(f"  .\\.venv\\Scripts\\python.exe scripts\\live_view.py {first_tid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
