"""
Phase 1 smoke test: prove we can reach Polymarket and authenticate.

Run it:
    python scripts/check_connection.py

What it does:
  1. Prints the active configuration (secrets redacted) so you can confirm
     you're pointed at the right network and in the mode you expect.
  2. Does an unauthenticated connectivity check against the CLOB.
  3. Runs L1 -> L2 auth and reports success.

It sends NO orders and moves NO money. Safe to run anytime.
"""

import sys
from pathlib import Path

# Make the project root importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SETTINGS, Mode  # noqa: E402
from src.connection import build_clob_client  # noqa: E402
from src.safety import kill_switch_engaged  # noqa: E402


def main() -> int:
    print("=" * 60)
    print("Polymarket CLOB V2 — connection check")
    print("=" * 60)

    # Show the resolved config first. If something's wrong (wrong host, live
    # mode unexpectedly), you want to see it before anything else happens.
    print("\nActive configuration (secrets redacted):")
    for key, value in SETTINGS.redacted().items():
        print(f"  {key:18} = {value}")

    if kill_switch_engaged():
        print("\n[!] KILL switch file is present. (Doesn't block reads, just FYI.)")

    if SETTINGS.mode == Mode.READONLY:
        print(
            "\nMODE=readonly: skipping authenticated client. "
            "Switch to simulation/live to test L1->L2 auth."
        )
        return 0

    print()
    build_clob_client()  # performs connectivity + L1->L2 auth, prints progress

    print("\n✅ All good: server reachable and authenticated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
