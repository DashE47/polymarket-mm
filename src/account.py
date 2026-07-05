"""
Reads your account state: pUSD collateral balance and open positions.

Two different data sources, on purpose:

  * pUSD balance comes from the CLOB itself, via the authenticated (L2)
    `get_balance_allowance` call. "Allowance" is the amount you've approved the
    exchange contract to move on your behalf; "balance" is what you actually
    hold. Both matter: you can have funds but a zero allowance and still get a
    "not enough balance or allowance" error when trading.

  * Positions come from the public Data API (data-api.polymarket.com), which is
    read-only and (for this endpoint) doesn't need auth. The CLOB SDK doesn't
    expose positions, so this is the canonical source.

pUSD, like USDC, uses 6 decimals on-chain: an on-chain integer of 1_000_000
means 1.00 pUSD. We convert to human units before displaying.
"""

from __future__ import annotations

from typing import Any

from config.settings import SETTINGS
from src.http_utils import get_json

# pUSD (and USDC) use 6 decimal places on Polygon.
PUSD_DECIMALS = 6

# ---------------------------------------------------------------------------
# Importing BalanceAllowanceParams / AssetType.
#
# The V2 README's headline import line doesn't list these helper types, and
# their exact module path can shift between SDK versions. Rather than hard-code
# one path and risk an ImportError, we try the most likely locations in order.
# If all fail we fall back to a plain dict, which the SDK also accepts in most
# versions. Each branch is commented so you can see what's going on.
# ---------------------------------------------------------------------------
_BalanceAllowanceParams: Any = None
_AssetType: Any = None
try:
    # Most likely: exported from the package root alongside the other types.
    from py_clob_client_v2 import BalanceAllowanceParams as _BalanceAllowanceParams  # type: ignore
    from py_clob_client_v2 import AssetType as _AssetType  # type: ignore
except Exception:  # noqa: BLE001
    try:
        # Next most likely: under a `clob_types` submodule (legacy layout).
        from py_clob_client_v2.clob_types import (  # type: ignore
            BalanceAllowanceParams as _BalanceAllowanceParams,
            AssetType as _AssetType,
        )
    except Exception:  # noqa: BLE001
        # Leave them as None; get_pusd_balance() handles the fallback.
        pass


def _collateral_params() -> Any:
    """Build the argument for get_balance_allowance for the COLLATERAL (pUSD).

    Uses the SDK's typed params if we found them; otherwise a plain dict, which
    the SDK accepts in most versions. Either way we're asking the same thing:
    "what's my collateral balance and allowance?"
    """
    if _BalanceAllowanceParams is not None and _AssetType is not None:
        return _BalanceAllowanceParams(asset_type=_AssetType.COLLATERAL)
    # Fallback shape. If your SDK rejects this, import the real types above.
    return {"asset_type": "COLLATERAL"}


def get_pusd_balance(client: Any, refresh: bool = True) -> dict[str, float]:
    """Return the wallet's pUSD balance and allowance in human (pUSD) units.

    `client` is an authenticated (L2) ClobClient from connection.build_clob_client.

    IMPORTANT — why `refresh`:
        The CLOB serves a *cached* balance from `/balance-allowance`. That cache
        reflects whatever it last synced from the Polygon chain, and for a wallet
        it has never synced (e.g. you just funded it, or it has only held outcome
        tokens) the cache is 0. Calling `/balance-allowance/update` first tells
        the CLOB to re-read your on-chain pUSD, after which the regular read
        returns the real number. This is the #1 reason "my balance shows 0".

        `update` only refreshes the server's view of your balance — it does NOT
        move funds or place orders — so it's safe to call in any mode.
    """
    params = _collateral_params()

    if refresh:
        try:
            client.update_balance_allowance(params)
        except Exception as exc:  # noqa: BLE001 - refresh is best-effort
            # If the refresh endpoint hiccups we still try the read below; the
            # caller will just see a possibly-stale value rather than crashing.
            print(f"  [balance] (refresh failed, reading cached value: {exc})")

    raw = client.get_balance_allowance(params)

    # Real response shape (confirmed against a live account):
    #   {'balance': '19971681',
    #    'allowances': {'<exchange_addr>': '0', '<exchange_addr>': '0', ...}}
    # i.e. `balance` is a single integer string (base units), and `allowances`
    # is a dict mapping each Polymarket exchange contract to the amount of pUSD
    # you've approved it to spend. We surface the SMALLEST approval, because
    # trading is gated by whichever exchange has the least allowance.
    balance_raw = float(raw.get("balance", 0) or 0)

    allowances = raw.get("allowances", {})
    if isinstance(allowances, dict) and allowances:
        allowance_values = [float(v or 0) for v in allowances.values()]
        allowance_raw = min(allowance_values)
    else:
        # Fallback for any version that returns a flat 'allowance' field.
        allowance_raw = float(raw.get("allowance", 0) or 0)

    scale = 10 ** PUSD_DECIMALS
    return {
        "balance_pusd": balance_raw / scale,
        "allowance_pusd": allowance_raw / scale,
        "_raw": raw,  # the unparsed response; printed by show_account for debugging
    }


def get_positions(address: str, size_threshold: float = 1.0, limit: int = 100) -> list[dict]:
    """Fetch open positions for `address` from the public Data API.

    `address` should be the funder/proxy address that actually holds positions
    (the same one you'd see in the Polymarket UI). `size_threshold` hides dust
    positions below that size; `limit` caps how many rows come back (max 500).
    """
    url = f"{SETTINGS.data_host}/positions"
    params = {
        "user": address,
        "sizeThreshold": size_threshold,
        "limit": limit,
    }
    data = get_json(url, params=params)
    # The endpoint returns a JSON array of position objects.
    return data if isinstance(data, list) else []
