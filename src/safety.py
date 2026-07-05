"""
Safety primitives shared across the project.

Phase 1 only reads data, so nothing here is *enforced* yet — but the market
maker in later phases will call these on every quoting loop. Defining them now
keeps "how do I stop this thing?" answerable from day one.

Three layers of protection (in addition to MODE in settings):
  1. Kill switch  — a file on disk whose mere presence halts all quoting.
                    `touch KILL` from anywhere stops the bot, even mid-run.
  2. Max position — refuse to grow exposure in a market past a configured size.
  3. Daily loss   — halt for the day once cumulative loss crosses a cap.

The kill switch is a *file* rather than a variable on purpose: you can trigger
it from another terminal, a cron job, or a phone SSH session without touching
the running process.
"""

from __future__ import annotations

from pathlib import Path

from config.settings import SETTINGS, PROJECT_ROOT

# The kill-switch file lives at the repo root and is git-ignored. Create it to
# stop trading; delete it to allow trading again.
KILL_FILE = PROJECT_ROOT / "KILL"


def kill_switch_engaged() -> bool:
    """True if the KILL file exists — meaning: stop quoting right now."""
    return KILL_FILE.exists()


def engage_kill_switch(reason: str = "") -> None:
    """Create the KILL file (used by the bot itself when a limit is breached)."""
    KILL_FILE.write_text(reason or "engaged", encoding="utf-8")


def position_within_limit(current_exposure_usd: float, additional_usd: float) -> bool:
    """Would adding `additional_usd` of exposure stay within MAX_POSITION_USD?

    `current_exposure_usd` should be the absolute net exposure already held in
    the market. Returns False if the new order would push us over the cap.
    """
    projected = abs(current_exposure_usd) + abs(additional_usd)
    return projected <= SETTINGS.max_position_usd


def daily_loss_within_limit(daily_pnl_usd: float) -> bool:
    """True while today's loss is still under the cap.

    `daily_pnl_usd` is signed: profits are positive, losses negative. We only
    halt on losses, so a profit always passes.
    """
    if daily_pnl_usd >= 0:
        return True
    return abs(daily_pnl_usd) < SETTINGS.max_daily_loss_usd
