"""Token-bucket rate limiter for parallel test execution.

Prevents hitting agent API rate limits when running tests concurrently.
Implements a simple token-bucket algorithm — allows bursts up to the
bucket size, then throttles to the configured requests-per-second.

Usage:
    limiter = RateLimiter(requests_per_second=10)
    await limiter.acquire()  # blocks if over rate
"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Async token-bucket rate limiter."""

    def __init__(self, requests_per_second: float = 10.0, burst: int = 0):
        """
        Args:
            requests_per_second: Max sustained request rate.
            burst: Extra burst capacity above the per-second rate.
                   Defaults to requests_per_second (allows 1-second burst).
        """
        self._rate = requests_per_second
        self._max_tokens = burst or int(requests_per_second)
        self._tokens = float(self._max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request token is available."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._max_tokens,
                    self._tokens + elapsed * self._rate,
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

            # Wait for a token to become available
            wait_time = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(min(wait_time, 0.1))
