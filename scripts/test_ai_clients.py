"""Mostaql Notifier — AI Clients Test Script.

Tests the Gemini and Groq AI clients individually and the unified
AIClient with fallback. Requires real API keys in .env:
  GEMINI_API_KEY and GROQ_API_KEY

Run: python scripts/test_ai_clients.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Simple test prompt returning JSON
TEST_PROMPT = (
    "Analyze this text and return JSON with exactly these keys:\n"
    '{"sentiment": "positive" or "negative", "confidence": 0.0-1.0, "language": "ar" or "en"}\n\n'
    "Text: 'أنا سعيد جداً بهذا المشروع الرائع'\n\n"
    "Return ONLY the JSON object, no explanation."
)

# ── Test counters ─────────────────────────────────────────
_passed = 0
_failed = 0


def check(label: str, condition: bool) -> None:
    """Assert a test condition and track pass/fail counts.

    Args:
        label: Human-readable description of the test.
        condition: Whether the test passed.
    """
    global _passed, _failed
    if condition:
        _passed += 1
        logger.info("  ✅ %s", label)
    else:
        _failed += 1
        logger.error("  ❌ FAILED: %s", label)


async def test_gemini() -> None:
    """Test the Gemini client individually."""
    logger.info("═══ Test 1: Gemini Client ═══")

    from src.config import load_config
    config = load_config()

    if config.ai.gemini.api_key in ("", "test-gemini-key", "your-gemini-api-key-here"):
        logger.warning("  ⏭️  Skipping — no real GEMINI_API_KEY in .env")
        return

    from src.analyzer.gemini_client import GeminiClient

    start = time.monotonic()
    async with GeminiClient(config.ai.gemini) as client:
        result = await client.generate(TEST_PROMPT)
    elapsed = time.monotonic() - start

    if result is not None:
        check("Gemini returned a response", True)
        check("Has 'sentiment' key", "sentiment" in result)
        check("Has 'confidence' key", "confidence" in result)
        check("Provider is 'gemini'", result.get("_provider") == "gemini")
        check("Tokens counted", result.get("_tokens_used", 0) > 0)
        logger.info("  Response: %s", {k: v for k, v in result.items() if not k.startswith("_")})
        logger.info("  Tokens: %d | Time: %.1fs", result.get("_tokens_used", 0), elapsed)
    else:
        check("Gemini returned a response", False)


async def test_groq() -> None:
    """Test the Groq client individually."""
    logger.info("═══ Test 2: Groq Client ═══")

    from src.config import load_config
    config = load_config()

    if config.ai.groq.api_key in ("", "test-groq-key", "your-groq-api-key-here"):
        logger.warning("  ⏭️  Skipping — no real GROQ_API_KEY in .env")
        return

    from src.analyzer.groq_client import GroqClient

    start = time.monotonic()
    async with GroqClient(config.ai.groq) as client:
        result = await client.generate(TEST_PROMPT)
    elapsed = time.monotonic() - start

    if result is not None:
        check("Groq returned a response", True)
        check("Has 'sentiment' key", "sentiment" in result)
        check("Has 'confidence' key", "confidence" in result)
        check("Provider is 'groq'", result.get("_provider") == "groq")
        check("Tokens counted", result.get("_tokens_used", 0) > 0)
        logger.info("  Response: %s", {k: v for k, v in result.items() if not k.startswith("_")})
        logger.info("  Tokens: %d | Time: %.1fs", result.get("_tokens_used", 0), elapsed)
    else:
        check("Groq returned a response", False)


async def test_unified() -> None:
    """Test the unified AIClient with fallback."""
    logger.info("═══ Test 3: Unified AI Client (with fallback) ═══")

    from src.config import load_config
    config = load_config()

    has_gemini = config.ai.gemini.api_key not in ("", "test-gemini-key", "your-gemini-api-key-here")
    has_groq = config.ai.groq.api_key not in ("", "test-groq-key", "your-groq-api-key-here")

    if not has_gemini and not has_groq:
        logger.warning("  ⏭️  Skipping — no real API keys in .env")
        return

    from src.analyzer.ai_client import AIClient

    start = time.monotonic()
    async with AIClient(config.ai) as client:
        logger.info("  Primary: %s | Fallback: %s", client.primary.name, client.fallback.name)
        result = await client.analyze(TEST_PROMPT)
    elapsed = time.monotonic() - start

    if result is not None:
        check("Unified client returned a response", True)
        check("Has 'sentiment' key", "sentiment" in result)
        provider = result.get("_provider", "?")
        check(f"Provider identified ({provider})", provider in ("gemini", "groq"))
        logger.info("  Used provider: %s", provider)
        logger.info("  Response: %s", {k: v for k, v in result.items() if not k.startswith("_")})
        logger.info("  Tokens: %d | Time: %.1fs", result.get("_tokens_used", 0), elapsed)
    else:
        check("Unified client returned a response", False)


async def run_all_tests() -> None:
    """Run all AI client tests."""
    # Set fallback env vars if not present
    # Only set dummy values for non-AI config sections
    # AI keys should come from .env via load_dotenv()
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")

    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║  Mostaql Notifier — AI Client Tests                 ║")
    logger.info("╚══════════════════════════════════════════════════════╝")

    await test_gemini()
    await test_groq()
    await test_unified()

    logger.info("═══════════════════════════════════════════")
    logger.info("  Results: %d passed, %d failed", _passed, _failed)
    logger.info("═══════════════════════════════════════════")

    if _failed > 0:
        logger.error("Some tests failed!")
        sys.exit(1)
    else:
        logger.info("🎉 All AI client tests passed!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
