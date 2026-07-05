"""
Request schemas for the API (Pydantic models).

FastAPI uses these to validate incoming JSON and to auto-generate the docs at
/docs. Responses are returned as plain dicts (serialised from our existing
dataclasses) to keep things simple and flexible.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class StrategyParams(BaseModel):
    """The quoting knobs — mirror StrategyConfig, with the same defaults."""

    spread: float = 0.02
    size: float = 100.0
    skew: float = 0.005
    widen: float = 0.005
    requote: float = 0.002


class BacktestRequest(BaseModel):
    source: Literal["history", "recording"]
    # history mode
    token_id: Optional[str] = None
    interval: str = "1d"
    fidelity: int = 5
    # recording mode
    recording: Optional[str] = None
    # strategy
    params: StrategyParams = Field(default_factory=StrategyParams)


class RecordRequest(BaseModel):
    token_id: str
    duration: float = 300.0


class SweepRequest(BaseModel):
    source: Literal["history", "recording"]
    token_id: Optional[str] = None
    interval: str = "1d"
    fidelity: int = 5
    recording: Optional[str] = None
    spreads: list[float] = [0.01, 0.02, 0.04]
    sizes: list[float] = [50.0]
    skews: list[float] = [0.0, 0.005, 0.01]
    widen: float = 0.005
    requote: float = 0.002
