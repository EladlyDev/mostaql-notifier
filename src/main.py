"""Mostaql Notifier — Application Entry Point.

Main entry point for the Mostaql Notifier system. Initializes
configuration, database, and will orchestrate the scraping,
analysis, scoring, and notification pipeline.
"""

from __future__ import annotations

import asyncio
import sys

from src.config import load_config
from src.database.db import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def main() -> None:
    """Run the Mostaql Notifier application.

    Loads configuration, initializes the database with all tables,
    and will eventually start the continuous scraping, analysis,
    scoring, and notification pipeline.
    """
    logger.info("═══ Mostaql Notifier Starting ═══")

    try:
        # Load configuration
        config = load_config()
        logger.info("Configuration loaded (log_level=%s)", config.log_level)

        # Initialize database (creates tables via initialize())
        async with Database(config.database_path) as db:
            logger.info("Database ready at %s", db.db_path)

            # ── Pipeline stages (to be implemented) ──────
            # 1. Scraper: Fetch new job listings
            # 2. Analyzer: AI analysis of new jobs
            # 3. Scorer: Compute weighted scores
            # 4. Notifier: Send Telegram alerts

            logger.info("Pipeline placeholder — all modules will be integrated here")
            logger.info("═══ Mostaql Notifier Ready ═══")

    except FileNotFoundError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)
    except ValueError as e:
        logger.error("Validation error: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.critical("Unexpected error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
