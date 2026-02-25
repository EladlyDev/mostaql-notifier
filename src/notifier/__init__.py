"""Mostaql Notifier — Notifier Package.

Telegram notification system with formatted Arabic messages.
Components:
  - formatters: MarkdownV2 message builders (alert, digest, report, status)
  - telegram_bot: Async Telegram bot client with retry/fallback
  - dispatcher: DB-driven notification dispatch logic
"""

from src.notifier.formatters import (
    format_instant_alert,
    format_digest,
    format_daily_report,
    format_system_status,
)
from src.notifier.telegram_bot import TelegramNotifier
from src.notifier.dispatcher import NotificationDispatcher

__all__ = [
    "format_instant_alert",
    "format_digest",
    "format_daily_report",
    "format_system_status",
    "TelegramNotifier",
    "NotificationDispatcher",
]
