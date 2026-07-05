"""
Tiny HTTP helper for the PUBLIC, read-only Polymarket APIs (Gamma + Data).

Why this exists:
  * Public APIs are rate limited. If you hammer them you'll get HTTP 429
    ("Too Many Requests") and, sometimes, transient 5xx errors. The polite and
    robust way to handle that is *exponential backoff with jitter*: wait a
    little, then twice as long, then four times as long, etc., with a bit of
    randomness so many clients don't retry in lockstep.
  * Keeping this in one place means every public call gets the same retry
    behaviour for free.

We deliberately do NOT use this for the authenticated CLOB SDK — that client
manages its own HTTP. This helper is just for the plain JSON endpoints we hit
ourselves with `requests`.
"""

from __future__ import annotations

import random
import time
from typing import Any

import requests

# How many times to retry before giving up, and the base delay (seconds).
_MAX_RETRIES = 5
_BASE_DELAY = 0.5
# Status codes that are worth retrying (transient). 429 = rate limited.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
    """GET a URL and return parsed JSON, retrying transient failures.

    Raises requests.HTTPError on a non-retryable error (e.g. 400/404), or after
    exhausting retries on a retryable one.
    """
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=timeout)

            # If the server told us to slow down or had a hiccup, back off.
            if resp.status_code in _RETRYABLE_STATUS:
                _sleep_backoff(attempt, resp)
                continue

            # For any other 4xx/5xx, raise immediately — retrying a 404 is
            # pointless and a 401 means a real auth/config problem to surface.
            resp.raise_for_status()
            return resp.json()

        except (requests.ConnectionError, requests.Timeout) as exc:
            # Network blips are retryable too.
            last_exc = exc
            _sleep_backoff(attempt, None)

    # Exhausted all retries.
    raise RuntimeError(
        f"GET {url} failed after {_MAX_RETRIES} attempts"
    ) from last_exc


def _sleep_backoff(attempt: int, resp: requests.Response | None) -> None:
    """Sleep for an exponentially growing, jittered interval.

    If the server sent a `Retry-After` header (common with 429s), we honour it
    rather than guessing.
    """
    # Honour an explicit Retry-After if present.
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            time.sleep(float(retry_after))
            return

    # Otherwise: 0.5s, 1s, 2s, 4s, ... plus up to 250ms of random jitter.
    delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.25)
    time.sleep(delay)
