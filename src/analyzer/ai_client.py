"""Mostaql Notifier — Unified AI Client.

Wraps GeminiClient and GroqClient behind a single interface with
automatic fallback. Tries the primary provider first; if it fails,
transparently falls back to the secondary provider.
"""

from __future__ import annotations

from typing import Any, Optional

from src.config import AIConfig
from src.analyzer.gemini_client import GeminiClient
from src.analyzer.groq_client import GroqClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AIClient:
    """Unified AI client with automatic primary/fallback switching.

    Both providers share an identical generate() interface, so the
    caller doesn't need to know which one is being used.

    Attributes:
        primary: The primary provider client.
        fallback: The fallback provider client.
    """

    def __init__(self, config: AIConfig) -> None:
        """Initialize both AI provider clients.

        Determines primary and fallback based on config.primary_provider.

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

        logger.info(
            "AIClient initialized: primary=%s, fallback=%s",
            self.primary.name, self.fallback.name,
        )

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

        Tries the primary provider first. If it returns None (any
        failure), transparently retries with the fallback provider.

        Args:
            prompt: The full text prompt to send.

        Returns:
            Parsed JSON dict with provider metadata, or None if
            both providers failed.
        """
        # Try primary
        logger.debug("Trying primary provider: %s", self.primary.name)
        result = await self.primary.generate(prompt)

        if result is not None:
            logger.info("Analysis complete via %s", self.primary.name)
            return result

        # Fallback
        logger.warning(
            "Primary (%s) failed — falling back to %s",
            self.primary.name, self.fallback.name,
        )
        result = await self.fallback.generate(prompt)

        if result is not None:
            logger.info("Analysis complete via fallback %s", self.fallback.name)
            return result

        logger.error("Both AI providers failed")
        return None
