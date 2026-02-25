"""Mostaql Notifier — Async Rate Limiter.

Implements a token-bucket rate limiter for controlling the frequency
of async operations (API calls, web requests, etc.). Thread-safe
via asyncio.Lock.
"""

from __future__ import annotations

import asyncio
import time

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AsyncRateLimiter:
    """Async rate limiter using the sliding-window token bucket algorithm.

    Controls the rate of async operations by tracking timestamps of
    recent calls and sleeping until a slot becomes available.

    Attributes:
        max_calls: Maximum number of calls allowed within the time window.
        period: Time window in seconds.
    """

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        """Initialize the rate limiter.

        Args:
            max_calls: Maximum number of calls allowed per time period.
            period_seconds: Length of the sliding window in seconds.
        """
        self.max_calls = max_calls
        self.period = period_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

        logger.debug(
            "Rate limiter initialized: %d calls / %.1f seconds",
            max_calls,
            period_seconds,
        )

    def _cleanup_expired(self) -> None:
        """Remove timestamps that have fallen outside the current window.

        Called internally before checking available capacity.
        """
        now = time.monotonic()
        cutoff = now - self.period
        self._timestamps = [ts for ts in self._timestamps if ts > cutoff]

    @property
    def available_slots(self) -> int:
        """Return the number of available slots without acquiring the lock.

        Note: This is an approximate value — for thread-safe access,
        use acquire() instead.

        Returns:
            Number of remaining slots in the current window.
        """
        self._cleanup_expired()
        return max(0, self.max_calls - len(self._timestamps))

    async def acquire(self) -> None:
        """Acquire a rate-limit slot, blocking until one is available.

        If all slots are in use, this coroutine sleeps until the oldest
        timestamp expires and a new slot opens up.

        This method is safe to call from multiple concurrent coroutines.
        """
        async with self._lock:
            while True:
                self._cleanup_expired()

                if len(self._timestamps) < self.max_calls:
                    # Slot available — record this call
                    self._timestamps.append(time.monotonic())
                    logger.debug(
                        "Rate limit slot acquired (%d/%d used)",
                        len(self._timestamps),
                        self.max_calls,
                    )
                    return

                # No slots available — calculate wait time
                oldest = self._timestamps[0]
                wait_time = oldest + self.period - time.monotonic()

                if wait_time > 0:
                    logger.debug(
                        "Rate limit reached (%d/%d). Waiting %.2f seconds...",
                        len(self._timestamps),
                        self.max_calls,
                        wait_time,
                    )
                    # Release lock while sleeping so other coroutines
                    # don't deadlock
                    self._lock.release()
                    try:
                        await asyncio.sleep(wait_time)
                    finally:
                        await self._lock.acquire()

    async def __aenter__(self) -> "AsyncRateLimiter":
        """Support async context manager usage.

        Returns:
            The rate limiter instance after acquiring a slot.
        """
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the async context manager (no-op).

        Args:
            *args: Exception info (unused).
        """
        pass

    def __repr__(self) -> str:
        """Return a developer-friendly string representation.

        Returns:
            String showing max_calls and period configuration.
        """
        return f"AsyncRateLimiter(max_calls={self.max_calls}, period={self.period}s)"
