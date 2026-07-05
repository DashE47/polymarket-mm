"""
Phase 1 deliverable: print my wallet's pUSD balance and open positions.

Run it:
    python scripts/show_account.py

It authenticates (L1 -> L2) to read your pUSD balance from the CLOB, then hits
the public Data API for your open positions. Read-only: no orders, no transfers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SETTINGS, Mode  # noqa: E402
from src.account import get_positions, get_pusd_balance  # noqa: E402
from src.connection import build_clob_client  # noqa: E402


def _print_balance() -> None:
    if SETTINGS.mode == Mode.READONLY:
        print("MODE=readonly: skipping authenticated balance read.")
        return

    print("\n--- pUSD collateral (from CLOB, authenticated) ---")
    client = build_clob_client()
    bal = get_pusd_balance(client)
    print(f"  balance   : {bal['balance_pusd']:.6f} pUSD")
    print(f"  allowance : {bal['allowance_pusd']:.6f} pUSD")
    # Show the raw server response too. If the parsed balance ever looks wrong,
    # this tells us the exact field names/values the CLOB returned.
    print(f"  raw       : {bal['_raw']}")
    if bal["allowance_pusd"] <= 0:
        print("  [!] Allowance is 0 — you'd hit 'not enough allowance' when trading.")


def _print_positions() -> None:
    # Positions are held by the funder/proxy address. Fall back to nothing
    # sensible if it's unset — but warn, because that's the usual mistake.
    address = SETTINGS.funder_address
    print("\n--- open positions (from public Data API) ---")
    if not address:
        print("  FUNDER_ADDRESS is unset, so there's no address to query.")
        print("  Set it in .env to your Polymarket proxy/profile address.")
        return

    positions = get_positions(address)
    if not positions:
        print("  No open positions (or all below the size threshold).")
        return

    # Print a compact, readable table of the fields that matter most.
    print(f"  {'OUTCOME':<10} {'SIZE':>10} {'AVG':>7} {'CUR':>7} {'VALUE':>10}  MARKET")
    for p in positions:
        outcome = str(p.get("outcome", "?"))[:10]
        size = float(p.get("size", 0) or 0)
        avg = float(p.get("avgPrice", 0) or 0)
        cur = float(p.get("curPrice", 0) or 0)
        value = float(p.get("currentValue", 0) or 0)
        title = str(p.get("title", ""))[:50]
        print(f"  {outcome:<10} {size:>10.2f} {avg:>7.3f} {cur:>7.3f} {value:>10.2f}  {title}")


def main() -> int:
    print("=" * 60)
    print("Polymarket account snapshot")
    print(f"  mode   = {SETTINGS.mode.value}")
    print(f"  funder = {SETTINGS.funder_address or '(unset)'}")
    print("=" * 60)

    _print_balance()
    _print_positions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
