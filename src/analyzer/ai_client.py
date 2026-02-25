"""Mostaql Notifier — Unified AI Client.

Wraps GeminiClient and GroqClient behind a single interface with
automatic fallback and circuit breaker protection.

Circuit breakers prevent hammering a failed provider:
  - After 5 consecutive failures → circuit opens for 5 minutes
  - Automatically switches to fallback provider
  - Half-open test after cooldown
"""

from __future__ import annotations

from typing import Any, Optional

from src.config import AIConfig
from src.analyzer.gemini_client import GeminiClient
from src.analyzer.groq_client import GroqClient
from src.utils.logger import get_logger
from src.utils.resilience import CircuitBreaker, CircuitOpenError

logger = get_logger(__name__)


class AIClient:
    """Unified AI client with circuit breakers and fallback.

    Both providers share an identical generate() interface, so the
    caller doesn't need to know which one is being used. Circuit
    breakers prevent hammering a failing provider.

    Attributes:
        primary: The primary provider client.
        fallback: The fallback provider client.
        cb_primary: Circuit breaker for the primary provider.
        cb_fallback: Circuit breaker for the fallback provider.
    """

    def __init__(self, config: AIConfig) -> None:
        """Initialize both AI provider clients with circuit breakers.

        Args:
            config: AIConfig with provider settings.
        """
        self._gemini = GeminiClient(config.gemini)
        self._groq = GroqClient(config.groq)

        if config.primary_provider == "gemini":
            self.primary = self._gemini
            self.fallback = self._groq
        else:
            self.primary = self._groq
            self.fallback = self._gemini

        # Circuit breakers for each provider
        self.cb_primary = CircuitBreaker(
            name=self.primary.name,
            failure_threshold=5,
            cooldown_seconds=300,   # 5 minutes
        )
        self.cb_fallback = CircuitBreaker(
            name=self.fallback.name,
            failure_threshold=5,
            cooldown_seconds=300,
        )

        logger.info(
            "AIClient initialized: primary=%s, fallback=%s (with circuit breakers)",
            self.primary.name, self.fallback.name,
        )

    @property
    def circuit_breakers(self) -> list[CircuitBreaker]:
        """Return all circuit breakers for health monitoring."""
        return [self.cb_primary, self.cb_fallback]

    async def __aenter__(self) -> "AIClient":
        """Enter both provider contexts.

        Returns:
            The AIClient instance with both sessions active.
        """
        await self._gemini.__aenter__()
        await self._groq.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit both provider contexts.

        Args:
            *args: Exception info (unused).
        """
        await self._gemini.__aexit__(*args)
        await self._groq.__aexit__(*args)

    async def analyze(self, prompt: str) -> Optional[dict[str, Any]]:
        """Send a prompt to the primary provider with fallback.

        Flow:
          1. Try primary through its circuit breaker
          2. If circuit open or call fails → try fallback
          3. If both fail → return None

        Args:
            prompt: The full text prompt to send.

        Returns:
            Parsed JSON dict with provider metadata, or None if
            both providers failed.
        """
        # ── Try primary ──────────────────────────────────
        try:
            result = await self.cb_primary.call(
                self.primary.generate, prompt,
            )
            if result is not None:
                logger.info("Analysis complete via %s", self.primary.name)
                return result
            # generate() returned None → count as failure
            self.cb_primary._on_failure(
                self.cb_primary.state,
                Exception("generate() returned None"),
            )
        except CircuitOpenError:
            logger.debug(
                "Primary (%s) circuit is OPEN, skipping to fallback",
                self.primary.name,
            )
        except Exception as e:
            logger.warning(
                "Primary (%s) failed: %s — trying fallback",
                self.primary.name, str(e)[:100],
            )

        # ── Try fallback ─────────────────────────────────
        try:
            result = await self.cb_fallback.call(
                self.fallback.generate, prompt,
            )
            if result is not None:
                logger.info(
                    "Analysis complete via fallback %s",
                    self.fallback.name,
                )
                return result
            self.cb_fallback._on_failure(
                self.cb_fallback.state,
                Exception("generate() returned None"),
            )
        except CircuitOpenError:
            logger.error(
                "Both AI circuits OPEN: %s and %s",
                self.primary.name, self.fallback.name,
            )
        except Exception as e:
            logger.error(
                "Fallback (%s) also failed: %s",
                self.fallback.name, str(e)[:100],
            )

        logger.error("Both AI providers failed")
        return None
