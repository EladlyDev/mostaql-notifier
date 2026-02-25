"""Mostaql Notifier — Logging Setup.

Provides a centralized logging configuration with colored console output
and rotating file handler. All modules should use get_logger() to obtain
a named logger instance.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Constants ─────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "mostaql_notifier.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5

# ── ANSI Color Codes ─────────────────────────────────────
COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[41m",  # Red background
}
RESET = "\033[0m"

# Track whether logging has been initialized
_initialized = False


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds ANSI colors to console log output.

    Colors are applied to the log level name and timestamp for better
    readability in terminal output.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with colored level name and timestamp.

        Args:
            record: The log record to format.

        Returns:
            Formatted log string with ANSI color codes.
        """
        color = COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname:<8}{RESET}"
        record.asctime = f"{color}{self.formatTime(record, self.datefmt)}{RESET}"
        return super().format(record)


def _setup_logging() -> None:
    """Initialize the global logging configuration.

    Sets up two handlers on the root logger:
    - Console handler: INFO level with colored timestamps.
    - Rotating file handler: DEBUG level, 10MB max, 5 backups.

    This function is idempotent — calling it multiple times has no effect
    after the first initialization.
    """
    global _initialized
    if _initialized:
        return

    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # ── Console Handler (INFO) ───────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = ColoredFormatter(
        fmt="%(asctime)s │ %(levelname)s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # ── Rotating File Handler (DEBUG) ────────────────────
    file_handler = RotatingFileHandler(
        filename=str(LOG_FILE),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance with the global configuration applied.

    Ensures logging is initialized before returning the logger.
    All application modules should use this function instead of
    calling logging.getLogger() directly.

    Args:
        name: The logger name, typically __name__ of the calling module.

    Returns:
        A configured logging.Logger instance.
    """
    _setup_logging()
    return logging.getLogger(name)
