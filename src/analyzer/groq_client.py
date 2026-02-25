"""Mostaql Notifier — Groq AI Client.

Async client for the Groq API (OpenAI-compatible). Sends structured
prompts and parses JSON responses for job analysis.

Uses aiohttp for HTTP calls and AsyncRateLimiter for RPM throttling.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import aiohttp

from src.config import GroqConfig
from src.utils.logger import get_logger
from src.utils.rate_limiter import AsyncRateLimiter

logger = get_logger(__name__)

_API_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = (
    "You are a freelancing job analyst. "
    "Always respond with valid JSON only, no markdown."
)


def _clean_json_text(text: str) -> str:
    """Strip markdown fences and whitespace from API response text.

    Args:
        text: Raw response text from the API.

    Returns:
        Cleaned text ready for JSON parsing.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


class GroqClient:
    """Async client for the Groq API (OpenAI-compatible).

    Same interface as GeminiClient for interchangeability.
    Uses the chat completions endpoint with json_object response format.

    Attributes:
        config: GroqConfig with api_key, model, temperature, etc.
        name: Provider name ('groq').
    """

    def __init__(self, config: GroqConfig) -> None:
        """Initialize the Groq client.

        Args:
            config: GroqConfig from the app configuration.
        """
        self.config = config
        self._rate_limiter = AsyncRateLimiter(
            max_calls=config.rpm_limit,
            period_seconds=60.0,
        )
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def name(self) -> str:
        """Provider name identifier.

        Returns:
            The string 'groq'.
        """
        return "groq"

    async def __aenter__(self) -> "GroqClient":
        """Create the aiohttp session with auth headers.

        Returns:
            The GroqClient instance with an active session.
        """
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
        )
        logger.debug("Groq client session created")
        return self

    async def __aexit__(self, *args: object) -> None:
        """Close the aiohttp session.

        Args:
            *args: Exception info (unused).
        """
        if self._session is not None:
            await self._session.close()
            self._session = None
            logger.debug("Groq client session closed")

    async def generate(self, prompt: str) -> Optional[dict[str, Any]]:
        """Send a prompt to Groq and return parsed JSON response.

        Applies rate limiting before each call. Handles all error cases
        gracefully, returning None on failure.

        Args:
            prompt: The full text prompt to send.

        Returns:
            Parsed JSON dict with _tokens_used, _provider, _model metadata,
            or None if the request failed.
        """
        if self._session is None:
            logger.error("Groq session not created — use async with")
            return None

        await self._rate_limiter.acquire()

        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            async with self._session.post(_API_URL, json=body) as resp:
                if resp.status == 429:
                    logger.warning("Groq rate limited (429). Waiting 60s...")
                    import asyncio
                    await asyncio.sleep(60)
                    return None

                if resp.status == 400:
                    error_body = await resp.text()
                    logger.error("Groq 400 error: %s", error_body[:500])
                    return None

                if resp.status >= 500:
                    error_body = await resp.text()
                    logger.error("Groq %d error: %s", resp.status, error_body[:300])
                    return None

                if resp.status != 200:
                    error_body = await resp.text()
                    logger.error("Groq unexpected %d: %s", resp.status, error_body[:300])
                    return None

                data = await resp.json()

        except aiohttp.ClientError as e:
            logger.error("Groq network error: %s", e)
            return None
        except Exception as e:
            logger.error("Groq unexpected error: %s", e)
            return None

        # ── Parse response ───────────────────────────────
        try:
            choices = data.get("choices", [])
            if not choices:
                logger.warning("Groq returned no choices")
                return None

            raw_text = choices[0]["message"]["content"]
            clean_text = _clean_json_text(raw_text)
            result = json.loads(clean_text)

        except (KeyError, IndexError) as e:
            logger.error("Groq response structure error: %s", e)
            logger.debug("Groq raw response: %s", json.dumps(data, ensure_ascii=False)[:500])
            return None
        except json.JSONDecodeError as e:
            logger.error("Groq JSON parse error: %s", e)
            logger.debug("Groq raw text: %s", raw_text[:500] if 'raw_text' in dir() else "N/A")
            return None

        # ── Add metadata ─────────────────────────────────
        usage = data.get("usage", {})
        result["_tokens_used"] = usage.get("total_tokens", 0)
        result["_provider"] = "groq"
        result["_model"] = self.config.model

        logger.info(
            "Groq response OK: %d tokens used",
            result["_tokens_used"],
        )

        return result
