"""Mostaql Notifier — Telegram Bot Client.

Async Telegram bot client using python-telegram-bot v22+.
Handles message sending with retry, rate limiting, message splitting,
and HTML fallback to plain text.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    RetryAfter,
    TimedOut,
    NetworkError,
)

from src.config import TelegramConfig
from src.utils.logger import get_logger
from src.utils.resilience import CircuitBreaker, CircuitOpenError

logger = get_logger(__name__)

_MAX_MESSAGE_LEN = 4096
_SAFE_LEN = 4000  # leave headroom


class TelegramNotifier:
    """Async Telegram bot for sending notifications.

    Handles message splitting, HTML/MarkdownV2 fallback to plain text,
    rate limiting, and retries with exponential backoff.

    Attributes:
        config: TelegramConfig with bot_token and chat_id.
    """

    def __init__(self, config: TelegramConfig) -> None:
        """Initialize the notifier.

        Args:
            config: TelegramConfig from the app configuration.
        """
        self.config = config
        self._bot = Bot(token=config.bot_token)

        # Circuit breaker for Telegram API
        self.circuit_breaker = CircuitBreaker(
            name="telegram",
            failure_threshold=5,
            cooldown_seconds=300,  # 5 minutes
        )

    async def initialize(self) -> bool:
        """Test the bot connection.

        Calls getMe to verify the token is valid.

        Returns:
            True if connected successfully, False otherwise.
        """
        try:
            me = await self._bot.get_me()
            logger.info("Telegram bot connected: @%s", me.username)
            return True
        except Exception as e:
            logger.error("Telegram bot connection failed: %s", e)
            return False

    async def send_message(
        self,
        text: str,
        parse_mode: str = ParseMode.HTML,
        disable_preview: bool = False,
    ) -> Optional[str]:
        """Send a message to the configured chat_id.

        Handles:
          - Long messages (>4096): splits at line boundaries
          - Parse errors: retries as plain text
          - Rate limiting (429): waits retry_after seconds
          - Network errors: retries up to 3 times

        Args:
            text: Message content.
            parse_mode: Telegram parse mode.
            disable_preview: Whether to disable link previews.

        Returns:
            Message ID string on success, None on failure.
        """
        if not text:
            return None

        chunks = self._split_message(text, _SAFE_LEN)
        last_msg_id: Optional[str] = None

        for i, chunk in enumerate(chunks):
            msg_id = await self._send_single(
                chunk, parse_mode, disable_preview,
            )
            if msg_id is not None:
                last_msg_id = msg_id

            # Delay between multi-part messages
            if i < len(chunks) - 1:
                await asyncio.sleep(0.5)

        return last_msg_id

    async def _send_single(
        self,
        text: str,
        parse_mode: str,
        disable_preview: bool,
    ) -> Optional[str]:
        """Send a single message chunk with retry logic.

        Args:
            text: Message text.
            parse_mode: Telegram parse mode.
            disable_preview: Whether to disable link previews.

        Returns:
            Message ID string on success, None on failure.
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                msg = await self._bot.send_message(
                    chat_id=self.config.chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_preview,
                )
                return str(msg.message_id)

            except BadRequest as e:
                error_msg = str(e)
                if "can't parse" in error_msg.lower() or "parse" in error_msg.lower():
                    # Parse error — fallback to plain text
                    logger.warning(
                        "Parse error, retrying as plain text: %s",
                        error_msg[:200],
                    )
                    plain = self._strip_formatting(text)
                    try:
                        msg = await self._bot.send_message(
                            chat_id=self.config.chat_id,
                            text=plain,
                            disable_web_page_preview=disable_preview,
                        )
                        return str(msg.message_id)
                    except Exception as e2:
                        logger.error("Plain text fallback also failed: %s", e2)
                        return None
                else:
                    logger.error("Telegram BadRequest: %s", error_msg)
                    return None

            except RetryAfter as e:
                wait = e.retry_after
                logger.warning(
                    "Telegram rate limited. Waiting %d seconds...", wait,
                )
                await asyncio.sleep(wait)
                # Continue to next attempt

            except TimedOut:
                logger.warning(
                    "Telegram timeout (attempt %d/%d)", attempt + 1, max_retries,
                )
                await asyncio.sleep(2 ** attempt)

            except NetworkError as e:
                logger.warning(
                    "Telegram network error (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                await asyncio.sleep(2 ** attempt)

            except Exception as e:
                logger.error("Telegram unexpected error: %s", e)
                return None

        logger.error("Failed to send message after %d attempts", max_retries)
        return None

    async def send_instant_alert(self, formatted_text: str) -> Optional[str]:
        """Send an instant alert with link preview enabled.

        Args:
            formatted_text: MarkdownV2 formatted alert text.

        Returns:
            Message ID string on success, None on failure.
        """
        return await self.send_message(
            formatted_text, disable_preview=False,
        )

    async def send_digest(self, formatted_text: str) -> Optional[str]:
        """Send a digest with link preview disabled.

        Args:
            formatted_text: MarkdownV2 formatted digest text.

        Returns:
            Message ID string on success, None on failure.
        """
        return await self.send_message(
            formatted_text, disable_preview=True,
        )

    async def send_daily_report(self, formatted_text: str) -> Optional[str]:
        """Send a daily report with link preview disabled.

        Args:
            formatted_text: MarkdownV2 formatted report text.

        Returns:
            Message ID string on success, None on failure.
        """
        return await self.send_message(
            formatted_text, disable_preview=True,
        )

    def _split_message(
        self, text: str, max_len: int = _SAFE_LEN
    ) -> list[str]:
        """Split long text at paragraph or line boundaries.

        Tries double newlines first, then single newlines.
        Each chunk will be at most max_len characters.

        Args:
            text: Full message text.
            max_len: Maximum characters per chunk.

        Returns:
            List of text chunks.
        """
        if len(text) <= max_len:
            return [text]

        chunks: list[str] = []
        remaining = text

        while len(remaining) > max_len:
            # Try to split at double newline
            cut_point = remaining.rfind("\n\n", 0, max_len)

            if cut_point <= 0:
                # Try single newline
                cut_point = remaining.rfind("\n", 0, max_len)

            if cut_point <= 0:
                # Force split at max_len
                cut_point = max_len

            chunks.append(remaining[:cut_point].rstrip())
            remaining = remaining[cut_point:].lstrip("\n")

        if remaining.strip():
            chunks.append(remaining.strip())

        return chunks

    @staticmethod
    def _strip_formatting(text: str) -> str:
        """Remove HTML/MarkdownV2 formatting for plain text fallback.

        Strips HTML tags, link syntax, and escape characters.

        Args:
            text: Formatted text (HTML or MarkdownV2).

        Returns:
            Plain text version.
        """
        # Convert HTML links <a href="url">text</a> → text (url)
        text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r'\2 (\1)', text)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Convert MarkdownV2 links [text](url) → text (url)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
        # Remove markdown markers
        text = text.replace("*", "").replace("_", "").replace("~", "")
        # Unescape HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        # Remove escape backslashes
        text = text.replace("\\", "")
        return text
