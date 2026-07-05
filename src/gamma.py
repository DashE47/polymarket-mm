"""
Gamma API client — market DISCOVERY (public, read-only, no auth).

Gamma (https://gamma-api.polymarket.com) is the catalogue: it knows what markets
exist, their human-readable questions, and — crucially — how to translate a
market into the on-chain identifiers the trading API speaks:

    market  --(conditionId)-->  a single market on-chain
            --(clobTokenIds)-->  one ERC-1155 token per outcome (Yes / No)

Two endpoints we use:
    * GET /public-search?q=...   keyword search. Returns `events` (a market or
      group of related markets), each holding a `markets` array. This is how the
      website's search box works; the plain /markets endpoint has NO text search.
    * GET /markets?...           structured listing/filtering (by id, slug,
      volume, etc.). We use it to look a market up by its conditionId.

Gotcha baked into Gamma: `clobTokenIds`, `outcomes`, and `outcomePrices` come
back as JSON *strings* (e.g. the string '["Yes", "No"]'), not real arrays, so we
json.loads them. And `clobTokenIds[i]` corresponds to `outcomes[i]`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Parse an Up/Down market's time window from its title, e.g. "2:50PM-2:55PM ET".
_WINDOW_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap]m)\s*[-–]\s*(\d{1,2}):(\d{2})\s*([ap]m)", re.I)


def window_minutes(question: str) -> int | None:
    """Length (minutes) of an Up/Down market's window, from its title:
    "2:50PM-2:55PM ET" -> 5, "2:45PM-3:00PM" -> 15. A single time ("2PM ET") ->
    60 (hourly). None if there's no intra-day window (e.g. daily markets).
    NOTE: Gamma's startDate is the market's creation time (~a day early), so the
    title is the only reliable source of the actual bucket length."""
    m = _WINDOW_RE.search(question)
    if m:
        h1, mn1, ap1, h2, mn2, ap2 = m.groups()

        def mins(h: str, mn: str, ap: str) -> int:
            return ((int(h) % 12) + (12 if ap.lower() == "pm" else 0)) * 60 + int(mn)

        return ((mins(h2, mn2, ap2) - mins(h1, mn1, ap1)) % (24 * 60)) or None
    if re.search(r"\b\d{1,2}(?::\d{2})?\s*[ap]m\b", question, re.I):
        return 60
    return None

from config.settings import SETTINGS
from src.http_utils import get_json


@dataclass
class Market:
    """A trimmed, friendly view of a Gamma market."""

    question: str
    slug: str
    condition_id: str
    # outcome label -> token_id, e.g. {"Yes": "8072…", "No": "1009…"}
    tokens: dict[str, str] = field(default_factory=dict)
    active: bool = False
    closed: bool = False
    accepting_orders: bool = False
    enable_order_book: bool = False
    volume: float = 0.0
    # Extra fields used by the API's market-stats endpoint (and a future UI's
    # stats bar). All optional with safe defaults so nothing else breaks.
    liquidity: float = 0.0
    one_day_price_change: float = 0.0
    one_hour_price_change: float = 0.0
    end_date: str = ""
    start_date: str = ""    # market open time (ISO) — needed to time short buckets
    # current implied price per outcome, e.g. {"Yes": 0.46, "No": 0.54}.
    outcome_prices: dict[str, float] = field(default_factory=dict)

    @property
    def tradeable(self) -> bool:
        """Can we actually quote here right now?

        A market is only useful to a market maker if it's live, not closed, has
        an order book, and is currently accepting orders.
        """
        return (
            self.active
            and not self.closed
            and self.enable_order_book
            and self.accepting_orders
        )

    def token_id(self, outcome: str) -> str:
        """Resolve an outcome label (e.g. 'Yes') to its token_id."""
        # Case-insensitive match so "yes"/"Yes"/"YES" all work.
        for label, tid in self.tokens.items():
            if label.lower() == outcome.lower():
                return tid
        raise KeyError(
            f"Outcome {outcome!r} not found. Available: {list(self.tokens)}"
        )


def _parse_json_list(raw) -> list:
    """Gamma returns some array fields as JSON strings; decode defensively."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _to_market(raw: dict) -> Market | None:
    """Convert a raw Gamma market dict into our Market, or None if unusable."""
    token_ids = _parse_json_list(raw.get("clobTokenIds"))
    outcomes = _parse_json_list(raw.get("outcomes"))
    if not token_ids or not outcomes or len(token_ids) != len(outcomes):
        # Without a clean outcome<->token mapping there's nothing to trade.
        return None

    # Current implied price per outcome (parallel to `outcomes`), if present.
    price_list = _parse_json_list(raw.get("outcomePrices"))
    outcome_prices = {
        o: float(p) for o, p in zip(outcomes, price_list)
        if str(p).replace(".", "", 1).replace("-", "", 1).isdigit()
    }

    return Market(
        question=raw.get("question") or raw.get("title") or "(no question)",
        slug=raw.get("slug", ""),
        condition_id=raw.get("conditionId", ""),
        tokens=dict(zip(outcomes, token_ids)),
        active=bool(raw.get("active")),
        closed=bool(raw.get("closed")),
        accepting_orders=bool(raw.get("acceptingOrders")),
        enable_order_book=bool(raw.get("enableOrderBook")),
        volume=float(raw.get("volumeNum") or raw.get("volume") or 0),
        liquidity=float(raw.get("liquidityNum") or raw.get("liquidity") or 0),
        one_day_price_change=float(raw.get("oneDayPriceChange") or 0),
        one_hour_price_change=float(raw.get("oneHourPriceChange") or 0),
        end_date=str(raw.get("endDate") or raw.get("endDateIso") or ""),
        start_date=str(raw.get("startDate") or raw.get("startDateIso") or ""),
        outcome_prices=outcome_prices,
    )


def search_markets(keyword: str, limit: int = 20, tradeable_only: bool = True) -> list[Market]:
    """Search markets by keyword via /public-search.

    Returns a flat list of Market objects (events are flattened into their
    constituent markets). If `tradeable_only`, markets that are closed or have
    no live order book are dropped — usually what you want for market making.
    """
    data = get_json(
        f"{SETTINGS.gamma_host}/public-search",
        params={"q": keyword, "limit_per_type": limit},
    )

    markets: list[Market] = []
    seen: set[str] = set()
    for event in data.get("events", []):
        for raw in event.get("markets", []):
            m = _to_market(raw)
            if m is None or m.condition_id in seen:
                continue
            if tradeable_only and not m.tradeable:
                continue
            seen.add(m.condition_id)
            markets.append(m)

    # Most-traded first — the liquid markets are the interesting ones.
    markets.sort(key=lambda m: m.volume, reverse=True)
    return markets[:limit]


def top_markets(limit: int = 24, tradeable_only: bool = True) -> list[Market]:
    """Trending markets by 24h volume (no search term) — for the Explorer's
    'suggestions' view. Over-fetches a bit so filtering still leaves a full grid.
    """
    data = get_json(
        f"{SETTINGS.gamma_host}/markets",
        params={
            "order": "volume24hr", "ascending": "false",
            "closed": "false", "active": "true", "limit": limit * 3,
        },
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    out: list[Market] = []
    seen: set[str] = set()
    for raw in rows:
        m = _to_market(raw)
        if m is None or m.condition_id in seen:
            continue
        if tradeable_only and not m.tradeable:
            continue
        seen.add(m.condition_id)
        out.append(m)
    return out[:limit]


def crypto_updown(limit: int = 24) -> list[Market]:
    """Currently-LIVE short-term crypto 'Up or Down' markets, soonest-resolving
    first. Gamma is messy here (many stale 'open' markets with past end dates and
    no book), so we filter hard: title contains 'up or down', accepting orders,
    has an order book, and end date in the future. Returns whatever is genuinely
    live right now (often just a daily one) — the UI handles a thin/empty result.
    """
    # The crucial filter is end_date_min=now (server-side): new 5-min buckets have
    # ~zero volume, so volume-ordering misses them — but a future-end-date filter
    # surfaces them. Order soonest-resolving first.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = get_json(
        f"{SETTINGS.gamma_host}/markets",
        params={"closed": "false", "active": "true", "end_date_min": now,
                "order": "endDate", "ascending": "true", "limit": 150},
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    out: list[Market] = []
    for raw in rows:
        if "up or down" not in (raw.get("question") or "").lower():
            continue
        if not raw.get("acceptingOrders") or not raw.get("enableOrderBook"):
            continue
        m = _to_market(raw)
        if m is not None:
            out.append(m)
    return out[:limit]


def resolve_token(target: str, outcome: str = "Yes") -> tuple[str, "Market | None"]:
    """Turn a CLI target into a token id, with friendly errors.

    `target` is either a raw token id (digits) or a 0x… conditionId. For a
    conditionId we look the market up and pick the requested outcome — raising a
    clear ValueError (listing the real outcome names) if it doesn't exist, since
    not every market is Yes/No (e.g. Up/Down price markets).
    """
    if not target.startswith("0x"):
        return target, None  # already a token id
    market = get_market(target)
    if market is None:
        raise ValueError(f"No market found for condition id {target}")
    try:
        return market.token_id(outcome), market
    except KeyError:
        raise ValueError(
            f"Outcome {outcome!r} is not in this market. "
            f"Available: {list(market.tokens)}. Re-run with --outcome <one of those>."
        )


def get_market(condition_id: str) -> Market | None:
    """Look up a single market by its conditionId via /markets."""
    data = get_json(
        f"{SETTINGS.gamma_host}/markets",
        params={"condition_ids": condition_id, "limit": 1},
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    if not rows:
        return None
    return _to_market(rows[0])


def settled_winner(condition_id: str) -> str | None:
    """The RESOLVED outcome of a closed market, or None if not settled yet.

    Gamma's /markets hides closed markets unless closed=true is passed, and these
    short-term markets settle minutes-to-hours after their end time — so poll this
    after close until it returns a name (e.g. 'Up' / 'Down').
    """
    data = get_json(
        f"{SETTINGS.gamma_host}/markets",
        params={"condition_ids": condition_id, "closed": "true", "limit": 1},
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    if not rows or not bool(rows[0].get("closed")):
        return None
    outs = _parse_json_list(rows[0].get("outcomes"))
    prices = _parse_json_list(rows[0].get("outcomePrices"))
    opx: dict[str, float] = {}
    for o, p in zip(outs, prices):
        try:
            opx[o] = float(p)
        except (TypeError, ValueError):
            pass
    if not opx or max(opx.values()) < 0.99:
        return None  # closed but not decisively priced yet
    return max(opx, key=opx.get)
