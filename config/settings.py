"""
Central configuration for the whole project.

Everything that varies between machines or that is secret (private key, hosts,
trading mode, risk limits) is read from the local `.env` file exactly once,
here, and exposed as a single `SETTINGS` object. The rest of the codebase
imports `SETTINGS` instead of touching environment variables directly, so there
is one obvious place to look when you want to know "what is this bot configured
to do?".

Why a frozen dataclass instead of loose module-level variables?
  * It validates the values on load (e.g. MODE must be one of three strings),
    so a typo in .env fails fast with a clear message instead of silently doing
    the wrong thing later.
  * It's immutable (frozen=True), so no other part of the program can quietly
    change, say, the max-loss limit at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Locate and load the .env file.
#
# PROJECT_ROOT is the folder that contains this `config/` package (i.e. the
# repo root). We build paths relative to it so the code works no matter what
# directory you run the scripts from.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# load_dotenv reads KEY=VALUE lines from .env into the process environment.
# override=False means real OS environment variables win over the file, which
# is the convention most tooling expects.
load_dotenv(dotenv_path=ENV_PATH, override=False)


class Mode(str, Enum):
    """The three operating modes, from safest to most dangerous.

    Subclassing `str` means a Mode compares equal to its string value, so you
    can write `if SETTINGS.mode == "live"` as well as `== Mode.LIVE`.
    """

    READONLY = "readonly"      # only read data; never sign or send anything
    SIMULATION = "simulation"  # simulate fills locally; never send real orders
    LIVE = "live"              # send REAL orders with REAL money


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    """Read a single environment variable with optional default / requirement."""
    value = os.getenv(name, default)
    if required and (value is None or value.strip() == ""):
        raise RuntimeError(
            f"Required setting '{name}' is missing. "
            f"Copy .env.example to .env and fill it in."
        )
    return value if value is not None else ""


@dataclass(frozen=True)
class Settings:
    # --- wallet / signing -------------------------------------------------
    private_key: str          # signs auth message + orders (SECRET)
    funder_address: str       # the proxy wallet that holds funds/positions
    signature_type: int       # 0 = EOA, 1 = email/magic proxy, 2 = browser proxy

    # --- network ----------------------------------------------------------
    chain_id: int             # 137 = Polygon mainnet
    clob_host: str            # authenticated trading API
    gamma_host: str           # public market-discovery API
    data_host: str            # public positions/activity API

    # --- safety -----------------------------------------------------------
    mode: Mode                # readonly | simulation | live
    confirm_live: bool        # must be True for live mode to actually trade

    # --- risk limits ------------------------------------------------------
    max_position_usd: float   # max net exposure per market (pUSD)
    max_daily_loss_usd: float # daily loss cap (pUSD) before quoting halts

    @property
    def is_live(self) -> bool:
        """True only when we are BOTH in live mode AND have confirmed it.

        This is the single gate the trading code must check before sending a
        real order. Requiring two independent flags makes accidental live
        trading essentially impossible.
        """
        return self.mode == Mode.LIVE and self.confirm_live

    def redacted(self) -> dict:
        """A dict of the config that is safe to print/log (no secrets)."""
        return {
            "mode": self.mode.value,
            "confirm_live": self.confirm_live,
            "chain_id": self.chain_id,
            "clob_host": self.clob_host,
            "gamma_host": self.gamma_host,
            "data_host": self.data_host,
            "signature_type": self.signature_type,
            # Show only the last 4 chars of the funder so logs are useful but
            # not sensitive. The private key is NEVER included.
            "funder_address": _mask(self.funder_address),
            "max_position_usd": self.max_position_usd,
            "max_daily_loss_usd": self.max_daily_loss_usd,
        }


def _mask(addr: str) -> str:
    """Show an address as 0x1234…abcd so it's recognizable but not fully exposed."""
    if not addr or len(addr) < 10:
        return addr or "(unset)"
    return f"{addr[:6]}…{addr[-4:]}"


def _load() -> Settings:
    """Read, parse, and validate all settings from the environment."""
    # MODE defaults to the safest non-readonly choice: simulation.
    raw_mode = _get("MODE", default="simulation").strip().lower()
    try:
        mode = Mode(raw_mode)
    except ValueError:
        raise RuntimeError(
            f"MODE='{raw_mode}' is invalid. Use one of: "
            f"{', '.join(m.value for m in Mode)}."
        )

    # Live mode requires the literal string "YES" (case-insensitive) in
    # CONFIRM_LIVE. Anything else (including the default "NO") means "not
    # confirmed", so live trading stays disabled.
    confirm_live = _get("CONFIRM_LIVE", default="NO").strip().upper() == "YES"

    signature_type = int(_get("SIGNATURE_TYPE", default="2"))

    return Settings(
        # The key is only needed for AUTHENTICATED actions (balance reads,
        # later: trading). Public scripts — market data, backtests — must run
        # without one, so we don't require it at load time. build_clob_client()
        # checks for it when an authenticated client is actually requested.
        private_key=_get("PRIVATE_KEY", default=""),
        funder_address=_get("FUNDER_ADDRESS", default=""),
        signature_type=signature_type,
        chain_id=int(_get("CHAIN_ID", default="137")),
        clob_host=_get("CLOB_HOST", default="https://clob.polymarket.com"),
        gamma_host=_get("GAMMA_HOST", default="https://gamma-api.polymarket.com"),
        data_host=_get("DATA_HOST", default="https://data-api.polymarket.com"),
        mode=mode,
        confirm_live=confirm_live,
        max_position_usd=float(_get("MAX_POSITION_USD", default="100")),
        max_daily_loss_usd=float(_get("MAX_DAILY_LOSS_USD", default="50")),
    )


# The single shared settings instance. Import this everywhere:
#     from config.settings import SETTINGS
SETTINGS = _load()
