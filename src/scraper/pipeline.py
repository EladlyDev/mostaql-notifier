"""Mostaql Notifier — Scraper Pipeline.

Orchestrates a complete scrape cycle: fetching listings from the XHR
endpoint, deduplicating against the database, applying a quick filter,
scraping detail pages for relevant jobs, and persisting to SQLite.
"""

from __future__ import annotations

import time
from typing import Any

from src.config import AppConfig
from src.database.db import Database
from src.database import queries
from src.database.models import JobListing
from src.scraper.client import MostaqlClient
from src.scraper.list_scraper import ListScraper
from src.scraper.detail_scraper import DetailScraper
from src.scraper.quick_filter import QuickFilter
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ScraperPipeline:
    """Database-integrated scraping pipeline.

    Runs a complete scrape cycle: list discovery → deduplication → quick filter →
    detail scraping → database persistence.

    Attributes:
        config: Full application configuration.
        db: Active database instance.
    """

    def __init__(self, config: AppConfig, db: Database) -> None:
        """Initialize the pipeline.

        Args:
            config: Full AppConfig instance.
            db: Active Database instance with initialized schema.
        """
        self.config = config
        self.db = db
        self._list_scraper = ListScraper(config.scraper)
        self._detail_scraper = DetailScraper()
        self._quick_filter = QuickFilter(config.profile)

    async def run_scrape_cycle(
        self,
        max_pages: int | None = None,
        max_details: int | None = None,
    ) -> dict[str, Any]:
        """Run a complete scrape cycle.

        Steps:
          1. Scrape listing pages (configurable number).
          2. For each job: check DB for duplicates, insert new jobs.
          3. Apply quick filter to jobs needing details.
          4. Scrape detail pages for relevant jobs only.
          5. Insert detail + publisher + proposals into DB.
          6. Return stats dict.

        Args:
            max_pages: Override max pages to scrape (default from config).
            max_details: Limit number of detail pages to scrape (None = all).

        Returns:
            Dict with cycle statistics:
              total_listed, new_jobs, passed_filter, filtered_out,
              details_scraped, errors, duration_seconds.
        """
        start_time = time.monotonic()
        pages = max_pages or self.config.scraper.max_pages_per_scan
        stats: dict[str, Any] = {
            "total_listed": 0,
            "new_jobs": 0,
            "passed_filter": 0,
            "filtered_out": 0,
            "details_scraped": 0,
            "errors": 0,
            "duration_seconds": 0.0,
        }

        logger.info("═══ Scrape Cycle Starting (%d pages) ═══", pages)

        async with MostaqlClient(self.config.scraper) as client:

            # ── Step 1: Scrape listings ──────────────────
            logger.info("Step 1: Scraping listing pages...")
            listings = await self._list_scraper.scrape_listings(
                client, pages=pages,
            )
            stats["total_listed"] = len(listings)
            logger.info("Found %d total listings", len(listings))

            # ── Step 2: Deduplicate and insert ───────────
            logger.info("Step 2: Deduplicating against database...")
            new_count = 0
            for job in listings:
                try:
                    exists = await queries.job_exists(self.db, job.mostaql_id)
                    if not exists:
                        await queries.insert_job(self.db, job)
                        new_count += 1
                except Exception as e:
                    logger.warning(
                        "Error inserting job %s: %s", job.mostaql_id, e,
                    )
                    stats["errors"] += 1

            stats["new_jobs"] = new_count
            logger.info(
                "Inserted %d new jobs (%d already in DB)",
                new_count, len(listings) - new_count,
            )

            # ── Step 3: Quick filter ─────────────────────
            logger.info("Step 3: Applying quick filter...")
            needing_details = await queries.get_jobs_needing_details(self.db)
            logger.info("%d jobs need detail scraping (pre-filter)", len(needing_details))

            # Convert DB rows back to JobListing for filtering
            filter_candidates = [
                JobListing.from_db_row(row) for row in needing_details
            ]
            relevant, filtered_out = self._quick_filter.filter_batch(filter_candidates)
            stats["passed_filter"] = len(relevant)
            stats["filtered_out"] = len(filtered_out)

            # Build lookup of relevant mostaql_ids → DB rows
            relevant_ids = {j.mostaql_id for j in relevant}
            needing_details = [r for r in needing_details if r["mostaql_id"] in relevant_ids]

            # Apply detail limit if specified
            if max_details is not None:
                needing_details = needing_details[:max_details]
                logger.info("Limiting to %d detail pages", max_details)

            # ── Step 4: Scrape details (filtered) ────────
            logger.info("Step 4: Scraping detail pages (%d relevant)...", len(needing_details))
            details_scraped = 0

            for i, job_row in enumerate(needing_details, 1):
                mostaql_id = job_row["mostaql_id"]
                url = job_row["url"]

                logger.info(
                    "  [%d/%d] Scraping detail for %s...",
                    i, len(needing_details), mostaql_id,
                )

                try:
                    detail = await self._detail_scraper.scrape_detail(
                        client, url, mostaql_id,
                    )

                    if detail is None:
                        logger.warning("Failed to parse detail for %s", mostaql_id)
                        stats["errors"] += 1
                        continue

                    # ── Step 5: Insert into DB ───────────
                    await queries.insert_job_detail(self.db, detail)
                    details_scraped += 1

                    logger.info(
                        "  ✅ %s — budget: %s, skills: %d, publisher: %s",
                        mostaql_id,
                        detail.budget_raw or "N/A",
                        len(detail.skills),
                        detail.publisher.display_name if detail.publisher else "N/A",
                    )

                except Exception as e:
                    logger.error(
                        "Error scraping detail for %s: %s", mostaql_id, e,
                    )
                    stats["errors"] += 1

            stats["details_scraped"] = details_scraped

        # ── Finalize ─────────────────────────────────────
        elapsed = time.monotonic() - start_time
        stats["duration_seconds"] = round(elapsed, 1)
        stats["requests_made"] = client.total_requests

        logger.info("═══ Scrape Cycle Complete ═══")
        logger.info(
            "  Listed: %d | New: %d | Filter: %d pass / %d skip | Details: %d | Errors: %d | Time: %.1fs",
            stats["total_listed"], stats["new_jobs"],
            stats["passed_filter"], stats["filtered_out"],
            stats["details_scraped"], stats["errors"], elapsed,
        )

        return stats
