r"""
Figure out the correct SIGNATURE_TYPE for your account.

WHY THIS EXISTS
    The CLOB reports your pUSD balance based on a proxy address it derives from
    your wallet + signature type. Polymarket uses different proxy schemes:
        0 = EOA            (trade straight from the key's own address)
        1 = Email / Magic  (Polymarket-managed proxy)
        2 = Browser wallet (MetaMask etc. via a Gnosis-Safe proxy)
    If SIGNATURE_TYPE is wrong, the server looks at the WRONG address and your
    balance shows 0 even though your funds are sitting safely in your real proxy.

WHAT THIS DOES
    Derives your API creds once (L1), then asks the CLOB for your pUSD balance
    under EACH signature type. Whichever one reports your real balance is the
    value to put in .env. Read-only: no orders, no transfers.

RUN
    .\.venv\Scripts\python.exe scripts\diagnose_signature_type.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py_clob_client_v2 import AssetType, BalanceAllowanceParams, ClobClient  # noqa: E402

from config.settings import SETTINGS  # noqa: E402

PUSD_DECIMALS = 6


def _balance_for(signature_type: int, creds, funder):
    """Build an L2 client pinned to one signature type and read its pUSD balance."""
    client = ClobClient(
        host=SETTINGS.clob_host,
        chain_id=SETTINGS.chain_id,
        key=SETTINGS.private_key,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )
    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    # Refresh the server's cached view from chain, then read it.
    try:
        client.update_balance_allowance(params)
    except Exception as exc:  # noqa: BLE001
        print(f"      (update failed: {exc})")
    raw = client.get_balance_allowance(params)
    balance = float(raw.get("balance", 0) or 0) / 10 ** PUSD_DECIMALS
    return balance, raw


def main() -> int:
    print("Deriving API credentials once (L1) …")
    # L1 auth is based on your key (EOA) and is independent of signature type,
    # so one set of creds works for probing all three.
    l1 = ClobClient(
        host=SETTINGS.clob_host,
        chain_id=SETTINGS.chain_id,
        key=SETTINGS.private_key,
    )
    creds = l1.create_or_derive_api_key()  # the 400 'could not create' is benign
    print("Got creds. Probing each signature type for your pUSD balance:\n")

    results = {}
    for st in (0, 1, 2):
        # For an EOA (type 0) there is no proxy, so don't pass a funder.
        funder = None if st == 0 else (SETTINGS.funder_address or None)
        label = {0: "EOA", 1: "Email/Magic", 2: "Browser wallet"}[st]
        try:
            balance, raw = _balance_for(st, creds, funder)
            results[st] = balance
            flag = "  <-- has your funds!" if balance > 0 else ""
            print(f"  SIGNATURE_TYPE={st} ({label:14}) -> {balance:.6f} pUSD{flag}")
        except Exception as exc:  # noqa: BLE001
            print(f"  SIGNATURE_TYPE={st} ({label:14}) -> error: {exc}")

    winners = [st for st, bal in results.items() if bal > 0]
    print()
    if len(winners) == 1:
        st = winners[0]
        print(f"✅ Set SIGNATURE_TYPE={st} in your .env — that's where your pUSD is.")
        if st != SETTINGS.signature_type:
            print(f"   (It's currently {SETTINGS.signature_type}, which is why balance read 0.)")
    elif not winners:
        print("⚠ All three reported 0. Either the funds aren't pUSD on this wallet,")
        print("  or FUNDER_ADDRESS doesn't match this key. Tell Claude this result.")
    else:
        print(f"⚠ Multiple types showed a balance: {winners}. Unusual — share this output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
