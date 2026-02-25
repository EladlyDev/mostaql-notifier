"""Mostaql Notifier — Google Gemini AI Client.

Async client for the Google Gemini generative AI API. Sends structured
prompts and parses JSON responses for job analysis.

Uses aiohttp for HTTP calls and AsyncRateLimiter for RPM throttling.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import aiohttp

from src.config import GeminiConfig
from src.utils.logger import get_logger
from src.utils.rate_limiter import AsyncRateLimiter

logger = get_logger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Disable all safety filters for analysis prompts
_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


def _clean_json_text(text: str) -> str:
    """Strip markdown fences, thinking text, and whitespace from response.

    Gemini (especially 2.5-flash with thinking) may output:
    - Markdown fences: ```json ... ```
    - Thinking/reasoning before the JSON
    - Mixed text and JSON

    This function extracts the first valid JSON object.

    Args:
        text: Raw response text from the API.

    Returns:
        Cleaned text ready for JSON parsing.
    """
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    # If text starts with '{', it's likely already JSON
    if text.startswith("{"):
        return text

    # Try to find the first JSON object by matching braces
    brace_start = text.find("{")
    if brace_start != -1:
        # Find matching closing brace by counting
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[brace_start : i + 1]
        # If no matching close, return from first brace to end
        return text[brace_start:]

    return text


class GeminiClient:
    """Async client for the Google Gemini generative AI API.

    Sends prompts to the Gemini API, enforces rate limits, and
    returns parsed JSON responses with metadata.

    Attributes:
        config: GeminiConfig with api_key, model, temperature, etc.
        name: Provider name ('gemini').
    """

    def __init__(self, config: GeminiConfig) -> None:
        """Initialize the Gemini client.

        Args:
            config: GeminiConfig from the app configuration.
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
            The string 'gemini'.
        """
        return "gemini"

    async def __aenter__(self) -> "GeminiClient":
        """Create the aiohttp session.

        Returns:
            The GeminiClient instance with an active session.
        """
        self._session = aiohttp.ClientSession()
        logger.debug("Gemini client session created")
        return self

    async def __aexit__(self, *args: object) -> None:
        """Close the aiohttp session.

        Args:
            *args: Exception info (unused).
        """
        if self._session is not None:
            await self._session.close()
            self._session = None
            logger.debug("Gemini client session closed")

    async def generate(self, prompt: str) -> Optional[dict[str, Any]]:
        """Send a prompt to Gemini and return parsed JSON response.

        Applies rate limiting before each call. Handles all error cases
        gracefully, returning None on failure.

        Args:
            prompt: The full text prompt to send.

        Returns:
            Parsed JSON dict with _tokens_used, _provider, _model metadata,
            or None if the request failed.
        """
        if self._session is None:
            logger.error("Gemini session not created — use async with")
            return None

        await self._rate_limiter.acquire()

        url = f"{_API_BASE}/{self.config.model}:generateContent"
        params = {"key": self.config.api_key}

        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_tokens,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 0},
            },
            "safetySettings": _SAFETY_SETTINGS,
        }

        try:
            async with self._session.post(
                url, params=params, json=body
            ) as resp:
                if resp.status == 429:
                    logger.warning("Gemini rate limited (429). Waiting 60s...")
                    import asyncio
                    await asyncio.sleep(60)
                    return None

                if resp.status == 400:
                    error_body = await resp.text()
                    logger.error("Gemini 400 error: %s", error_body[:500])
                    return None

                if resp.status >= 500:
                    error_body = await resp.text()
                    logger.error("Gemini %d error: %s", resp.status, error_body[:300])
                    return None

                if resp.status != 200:
                    error_body = await resp.text()
                    logger.error("Gemini unexpected %d: %s", resp.status, error_body[:300])
                    return None

                data = await resp.json()

        except aiohttp.ClientError as e:
            logger.error("Gemini network error: %s", e)
            return None
        except Exception as e:
            logger.error("Gemini unexpected error: %s", e)
            return None

        # ── Parse response ───────────────────────────────
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("Gemini returned no candidates")
                return None

            parts = candidates[0]["content"]["parts"]
            # Filter out thinking parts (gemini-2.5+ thinking models)
            text_parts = [
                p["text"] for p in parts
                if "text" in p and not p.get("thought", False)
            ]
            if not text_parts:
                logger.warning("Gemini returned no text parts")
                return None
            raw_text = text_parts[-1]  # Take the last non-thought part
            clean_text = _clean_json_text(raw_text)
            result = json.loads(clean_text)

        except (KeyError, IndexError) as e:
            logger.error("Gemini response structure error: %s", e)
            logger.debug("Gemini raw response: %s", json.dumps(data, ensure_ascii=False)[:500])
            return None
        except json.JSONDecodeError as e:
            logger.error("Gemini JSON parse error: %s", e)
            logger.debug("Gemini raw text: %s", raw_text[:500] if 'raw_text' in dir() else "N/A")
            return None

        # ── Add metadata ─────────────────────────────────
        usage = data.get("usageMetadata", {})
        result["_tokens_used"] = usage.get("totalTokenCount", 0)
        result["_provider"] = "gemini"
        result["_model"] = self.config.model

        logger.info(
            "Gemini response OK: %d tokens used",
            result["_tokens_used"],
        )

        return result
