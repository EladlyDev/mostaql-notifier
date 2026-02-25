"""Mostaql Notifier — Resilience Utilities.

Circuit breaker pattern and retry decorator for external service calls.

Circuit Breaker states:
  CLOSED  → normal operation, requests flow through
  OPEN    → service is failing, requests blocked for cooldown period
  HALF_OPEN → cooldown expired, one test request allowed

Usage:
    cb = CircuitBreaker("gemini", failure_threshold=5, cooldown_seconds=300)
    result = await cb.call(some_async_func, arg1, arg2)

    @retry_async(max_attempts=3, base_delay=2.0)
    async def flaky_function():
        ...
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable, Optional, Sequence, Type

from src.utils.logger import get_logger

logger = get_logger(__name__)


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is OPEN and blocking requests."""

    def __init__(self, name: str, remaining_seconds: float) -> None:
        self.name = name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"Circuit '{name}' is OPEN — retry in {remaining_seconds:.0f}s"
        )


class CircuitBreaker:
    """Circuit breaker for external service calls.

    Tracks consecutive failures. After `failure_threshold` failures,
    the circuit opens and blocks all calls for `cooldown_seconds`.
    After cooldown, it enters HALF_OPEN and allows one test call.

    Attributes:
        name: Human-readable service name (for logging/alerts).
        state: Current state ('CLOSED', 'OPEN', 'HALF_OPEN').
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 300.0,
        half_open_cooldown: float = 600.0,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            name: Service name for logging.
            failure_threshold: Consecutive failures before opening.
            cooldown_seconds: Seconds to stay open before half-open.
            half_open_cooldown: Seconds to stay open if half-open test fails.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_cooldown = half_open_cooldown

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._opened_at: float = 0.0
        self._total_trips = 0
        self._alerted = False  # Track if we've sent an alert for current open state

    @property
    def state(self) -> str:
        """Current circuit state, accounting for cooldown expiry."""
        if self._state == self.OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.cooldown_seconds:
                return self.HALF_OPEN
        return self._state

    @property
    def is_open(self) -> bool:
        """Whether the circuit is currently blocking requests."""
        return self.state == self.OPEN

    @property
    def remaining_cooldown(self) -> float:
        """Seconds remaining in the open cooldown."""
        if self._state != self.OPEN:
            return 0.0
        elapsed = time.monotonic() - self._opened_at
        return max(0.0, self.cooldown_seconds - elapsed)

    @property
    def total_trips(self) -> int:
        """Total number of times the circuit has tripped open."""
        return self._total_trips

    @property
    def has_alerted(self) -> bool:
        """Whether an alert has been sent for the current open state."""
        return self._alerted

    def mark_alerted(self) -> None:
        """Mark that we've sent an alert for the current open state."""
        self._alerted = True

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a function through the circuit breaker.

        Args:
            func: Async callable to execute.
            *args: Positional arguments for func.
            **kwargs: Keyword arguments for func.

        Returns:
            The result of func(*args, **kwargs).

        Raises:
            CircuitOpenError: If the circuit is OPEN.
            Exception: Any exception from func (after recording failure).
        """
        current_state = self.state

        if current_state == self.OPEN:
            raise CircuitOpenError(self.name, self.remaining_cooldown)

        try:
            result = await func(*args, **kwargs)
            self._on_success(current_state)
            return result

        except Exception as e:
            self._on_failure(current_state, e)
            raise

    def _on_success(self, state: str) -> None:
        """Handle a successful call."""
        if state == self.HALF_OPEN:
            logger.info(
                "Circuit '%s': HALF_OPEN → CLOSED (test succeeded)",
                self.name,
            )
        if self._failure_count > 0:
            logger.debug(
                "Circuit '%s': failure count reset (was %d)",
                self.name, self._failure_count,
            )
        self._state = self.CLOSED
        self._failure_count = 0
        self._alerted = False

    def _on_failure(self, state: str, error: Exception) -> None:
        """Handle a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if state == self.HALF_OPEN:
            # Half-open test failed → back to OPEN with longer cooldown
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            self.cooldown_seconds = self.half_open_cooldown
            self._alerted = False
            logger.warning(
                "Circuit '%s': HALF_OPEN → OPEN (test failed: %s, "
                "cooldown: %.0fs)",
                self.name, type(error).__name__, self.cooldown_seconds,
            )
            return

        if self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            self._total_trips += 1
            self._alerted = False
            logger.warning(
                "Circuit '%s': CLOSED → OPEN (trip #%d, %d failures, "
                "cooldown: %.0fs). Error: %s",
                self.name, self._total_trips, self._failure_count,
                self.cooldown_seconds, str(error)[:200],
            )
        else:
            logger.debug(
                "Circuit '%s': failure %d/%d: %s",
                self.name, self._failure_count, self.failure_threshold,
                type(error).__name__,
            )

    def reset(self) -> None:
        """Force-reset the circuit to CLOSED."""
        self._state = self.CLOSED
        self._failure_count = 0
        self._alerted = False
        logger.info("Circuit '%s': manually reset to CLOSED", self.name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for health reporting.

        Returns:
            Dict with state, failure count, trips, cooldown remaining.
        """
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self._failure_count,
            "total_trips": self._total_trips,
            "remaining_cooldown": round(self.remaining_cooldown, 1),
        }


def retry_async(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: Sequence[Type[BaseException]] = (Exception,),
) -> Callable:
    """Decorator for async functions that should be retried on failure.

    Uses exponential backoff: delay = base_delay * 2^(attempt-1),
    capped at max_delay.

    Args:
        max_attempts: Maximum number of attempts (including first).
        base_delay: Base delay in seconds (doubles each retry).
        max_delay: Maximum delay between retries.
        exceptions: Tuple of exception types to retry on.

    Returns:
        Decorator function.

    Usage:
        @retry_async(max_attempts=3, base_delay=2.0)
        async def flaky_call():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except tuple(exceptions) as e:
                    last_error = e
                    if attempt == max_attempts:
                        logger.warning(
                            "Retry exhausted for %s after %d attempts: %s",
                            func.__name__, max_attempts, e,
                        )
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    logger.debug(
                        "Retry %d/%d for %s in %.1fs: %s",
                        attempt, max_attempts, func.__name__, delay, e,
                    )
                    await asyncio.sleep(delay)
            raise last_error  # type: ignore[misc]
        return wrapper
    return decorator
