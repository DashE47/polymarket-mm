"""
Builds and authenticates the Polymarket CLOB **V2** client.

Background on the two-step auth (this trips up most newcomers):

  L1 ("level 1") authentication = your wallet private key.
      Polymarket has you SIGN a message (EIP-712) with your key to prove you
      control the wallet. From that signature it can deterministically create
      or recover a set of API credentials.

  L2 ("level 2") authentication = those API credentials
      (api_key + secret + passphrase). They're used to HMAC-sign every
      subsequent request. This is what authorizes reads of your private data
      (balances) and, later, placing/cancelling orders.

So the flow is: use the key (L1) to fetch your API creds, then build a client
that holds those creds (L2). We never want to derive creds more than once per
run, so this module does it in a single place and hands back a ready client.

IMPORTANT: this module imports the V2 package `py_clob_client_v2`. The legacy
`py_clob_client` (no `_v2`) talks to the retired V1 exchange and will fail
against production.
"""

from __future__ import annotations

# The V2 client. If this import fails with ModuleNotFoundError, you almost
# certainly installed the legacy `py-clob-client` instead of `py_clob_client_v2`.
from py_clob_client_v2 import ApiCreds, ClobClient

from config.settings import SETTINGS, Mode


def _connectivity_check(client: ClobClient) -> None:
    """Confirm we can reach the CLOB before doing anything that needs auth.

    `get_ok()` is an unauthenticated health check — it just asks the server
    "are you there?". Doing this first means a network/DNS/outage problem
    surfaces as a clear connectivity error instead of being misread as an
    auth failure later.
    """
    ok = client.get_ok()
    print(f"  [connectivity] CLOB reachable -> {ok!r}")

    # Server time is also unauthenticated and handy: a large clock skew between
    # your machine and the server can break request signing, so it's worth
    # eyeballing once.
    try:
        server_time = client.get_server_time()
        print(f"  [connectivity] CLOB server time -> {server_time}")
    except Exception as exc:  # noqa: BLE001 - non-fatal, informational only
        print(f"  [connectivity] (server time unavailable: {exc})")


def _derive_creds(l1_client: ClobClient) -> ApiCreds:
    """Run L1 auth to obtain L2 API credentials.

    The V2 client's `create_or_derive_api_key()` does two things in sequence
    (see client.py): it FIRST tries to *create* a brand-new key, and if that
    fails it falls back to *deriving* (fetching) the key your wallet already has.

    HEADS UP — the scary-looking line you may see on a wallet that has traded
    before:

        [py_clob_client_v2] request error status=400 ...
        body={"error":"Could not create api key"}

    ...is EXPECTED and harmless. It's just the "create" attempt failing because
    your wallet already has API creds; the SDK then silently derives the
    existing ones. We verify success explicitly below, so we don't have to trust
    that log line either way.
    """
    creds = l1_client.create_or_derive_api_key()
    # Make sure we actually got real credentials back. If both create AND derive
    # failed, the api_key would be empty/None — catch that here instead of
    # sailing on and reporting a hollow "authenticated".
    if not creds or not getattr(creds, "api_key", None):
        raise RuntimeError(
            "L1->L2 auth failed: no API credentials were returned. "
            "Check that PRIVATE_KEY is correct and the wallet is registered "
            "with Polymarket."
        )
    return creds


def _verify_l2(client: ClobClient) -> None:
    """Prove the L2 credentials actually work with a real authenticated call.

    Deriving creds isn't the same as them working: the HMAC signing, clock,
    headers, etc. all have to be right. `get_api_keys()` is a cheap, read-only
    L2 endpoint, so a successful response is genuine proof of authentication —
    much better than printing "authenticated" and hoping.
    """
    keys = client.get_api_keys()
    # The endpoint returns the set of api keys registered to this wallet.
    n = len(keys.get("apiKeys", keys)) if isinstance(keys, dict) else len(keys)
    print(f"  [auth] L2 verified via get_api_keys (wallet has {n} key(s)).")


def build_public_client() -> ClobClient:
    """Return an UNauthenticated CLOB client for public, read-only market data.

    Order books, midpoints, prices and spreads are public — they don't need a
    key or API creds. Building without a key means market-data scripts work even
    before you've set up a wallet, and they can't accidentally do anything that
    moves funds. This is the right client for everything in Phase 2.
    """
    return ClobClient(host=SETTINGS.clob_host, chain_id=SETTINGS.chain_id)


def build_clob_client() -> ClobClient:
    """Return a fully L2-authenticated CLOB V2 client.

    Refuses to build in readonly mode, because an authenticated client's whole
    point is to act on your behalf. Public, unauthenticated reads (Gamma/Data
    APIs) don't need this client at all.
    """
    if SETTINGS.mode == Mode.READONLY:
        raise RuntimeError(
            "MODE=readonly: refusing to build an authenticated client. "
            "Use the public Gamma/Data API helpers instead."
        )

    if not SETTINGS.private_key:
        raise RuntimeError(
            "PRIVATE_KEY is not set. Copy .env.example to .env and fill it in "
            "to use authenticated features (balance, trading)."
        )

    # `funder` is the wallet that holds the money. For a proxy setup
    # (signature_type 1 or 2) it's your Polymarket proxy address. For a raw EOA
    # (signature_type 0) you can omit it and the SDK uses the signer address.
    funder = SETTINGS.funder_address or None

    print("Building CLOB V2 client …")
    print(f"  host           = {SETTINGS.clob_host}")
    print(f"  chain_id       = {SETTINGS.chain_id}")
    print(f"  signature_type = {SETTINGS.signature_type}")
    print(f"  funder         = {funder or '(EOA from key)'}")

    # --- Step 1: L1 client (key only) ------------------------------------
    # With just the key, this client can sign the message that derives creds.
    l1_client = ClobClient(
        host=SETTINGS.clob_host,
        chain_id=SETTINGS.chain_id,
        key=SETTINGS.private_key,
        signature_type=SETTINGS.signature_type,
        funder=funder,
    )

    # Verify the server is reachable before we try to authenticate.
    _connectivity_check(l1_client)

    # --- Step 1b: derive the L2 API credentials --------------------------
    print("  [auth] deriving L2 API credentials from wallet (L1) …")
    creds: ApiCreds = _derive_creds(l1_client)
    print("  [auth] got API credentials (api_key, secret, passphrase).")

    # --- Step 2: L2 client (key + creds) ---------------------------------
    # Re-create the client, this time carrying the creds so it can make
    # authenticated requests. (Re-instantiating is the pattern shown in the
    # V2 README; it's cleaner than mutating the existing client.)
    l2_client = ClobClient(
        host=SETTINGS.clob_host,
        chain_id=SETTINGS.chain_id,
        key=SETTINGS.private_key,
        creds=creds,
        signature_type=SETTINGS.signature_type,
        funder=funder,
    )

    # Don't claim success — prove it with a real authenticated call.
    _verify_l2(l2_client)
    return l2_client


# Allow `python -m src.connection` as a quick smoke test of just the connection.
if __name__ == "__main__":
    client = build_clob_client()
    print("\nConnection OK. Authenticated CLOB V2 client is ready to use.")
