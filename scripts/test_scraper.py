"""Mostaql Notifier — Scraper End-to-End Test.

Tests the integrated scraper pipeline against live mostaql.com:
  1. Loads real config
  2. Runs one scrape cycle: 1 page of listings + details for first 2 new jobs
  3. Prints all extracted data formatted nicely
  4. Prints database contents after the cycle
  5. Reports extraction success rate per field

Run: python scripts/test_scraper.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set dummy env vars for non-scraper config sections
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")

from src.utils.logger import get_logger
from src.config import load_config
from src.database.db import Database
from src.database import queries
from src.scraper.pipeline import ScraperPipeline

logger = get_logger(__name__)


def _print_separator(char: str = "═", width: int = 70) -> None:
    """Print a separator line.

    Args:
        char: Character to repeat.
        width: Width of the separator.
    """
    logger.info(char * width)


def _print_job(job: dict, index: int) -> None:
    """Pretty-print a job from the database.

    Args:
        job: Job dict from the database.
        index: Display index.
    """
    logger.info("  ── Job #%d ──────────────────────────────", index)
    logger.info("  ID:          %s", job.get("mostaql_id", "?"))
    logger.info("  Title:       %s", job.get("title", "?"))
    logger.info("  URL:         %s", job.get("url", "?"))
    logger.info("  Category:    %s", job.get("category", "—"))
    logger.info("  Budget:      %s", job.get("budget_raw", "—") or "—")

    budget_min = job.get("budget_min")
    budget_max = job.get("budget_max")
    if budget_min is not None:
        logger.info("  Budget parsed: $%.0f - $%.0f", budget_min, budget_max or budget_min)

    skills = job.get("skills", "[]")
    if isinstance(skills, str):
        try:
            skills = json.loads(skills)
        except (json.JSONDecodeError, TypeError):
            skills = []
    logger.info("  Skills:      %s", ", ".join(skills) if skills else "—")
    logger.info("  Proposals:   %d", job.get("proposals_count", 0))
    logger.info("  Status:      %s", job.get("status", "?"))

    desc = job.get("brief_description", "") or ""
    if desc:
        logger.info("  Description: %s%s", desc[:100], "..." if len(desc) > 100 else "")


def _print_detail(detail: dict, index: int) -> None:
    """Pretty-print a job detail record.

    Args:
        detail: Job detail dict from the database.
        index: Display index.
    """
    logger.info("  ── Detail #%d ─────────────────────────────", index)
    logger.info("  Mostaql ID:     %s", detail.get("mostaql_id", "?"))
    logger.info("  Duration:       %s", detail.get("duration", "—"))
    logger.info("  Exp Level:      %s", detail.get("experience_level", "—"))
    logger.info("  Attachments:    %d", detail.get("attachments_count", 0))
    logger.info("  Publisher ID:  %s", detail.get("publisher_id", "—"))

    desc = detail.get("full_description", "")
    if desc:
        logger.info("  Description:    %s%s", desc[:150], "..." if len(desc) > 150 else "")


def _print_publisher(pub: dict) -> None:
    """Pretty-print a publisher record.

    Args:
        pub: Publisher dict from the database.
    """
    logger.info("  ── Publisher ──────────────────────────────")
    logger.info("  Name:           %s", pub.get("display_name", "?"))
    logger.info("  Role:           %s", pub.get("role", "—"))
    logger.info("  Verified:       %s", "✅" if pub.get("identity_verified") else "❌")
    logger.info("  Hire Rate:      %s (%.0f%%)", pub.get("hire_rate_raw", "—"), pub.get("hire_rate", 0))
    logger.info("  Registered:     %s", pub.get("registration_date", "—"))
    logger.info("  Open Projects:  %d", pub.get("open_projects", 0))


async def run_test() -> None:
    """Run the end-to-end scraper test."""
    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║  Mostaql Notifier — Scraper End-to-End Test         ║")
    logger.info("╚══════════════════════════════════════════════════════╝")

    # Load config
    config = load_config()
    logger.info("Config loaded: base_url=%s", config.scraper.base_url)

    # Use a test database
    test_db_path = str(PROJECT_ROOT / "data" / "test_scraper.db")

    async with Database(test_db_path) as db:

        # ── Run scrape cycle ─────────────────────────────
        _print_separator()
        logger.info("  STEP 1: Running scrape cycle (1 page, max 2 details)")
        _print_separator()

        pipeline = ScraperPipeline(config, db)
        stats = await pipeline.run_scrape_cycle(max_pages=1, max_details=2)

        logger.info("")
        logger.info("  Cycle Stats:")
        for key, value in stats.items():
            logger.info("    %s: %s", key, value)

        # ── Print extracted jobs ─────────────────────────
        _print_separator()
        logger.info("  STEP 2: Database Contents — Jobs")
        _print_separator()

        conn = await db.get_connection()
        cursor = await conn.execute(
            "SELECT * FROM jobs ORDER BY first_seen_at DESC LIMIT 10"
        )
        jobs = [dict(row) for row in await cursor.fetchall()]
        logger.info("  Total jobs in DB: %d", len(jobs))

        for i, job in enumerate(jobs[:5], 1):
            _print_job(job, i)
            logger.info("")

        # ── Print details ────────────────────────────────
        _print_separator()
        logger.info("  STEP 3: Database Contents — Details")
        _print_separator()

        cursor = await conn.execute(
            "SELECT * FROM job_details ORDER BY scraped_at DESC LIMIT 5"
        )
        details = [dict(row) for row in await cursor.fetchall()]
        logger.info("  Total details in DB: %d", len(details))

        for i, detail in enumerate(details, 1):
            _print_detail(detail, i)

            # Print associated publisher
            if detail.get("publisher_id"):
                pub_row = await queries.get_publisher(db, detail["publisher_id"])
                if pub_row:
                    _print_publisher(pub_row)

            # Print proposals count
            cursor2 = await conn.execute(
                "SELECT COUNT(*) AS cnt FROM proposals WHERE mostaql_id = ?",
                (detail["mostaql_id"],),
            )
            prop_row = await cursor2.fetchone()
            logger.info("  Proposals in DB:  %d", dict(prop_row)["cnt"])
            logger.info("")

        # ── Extraction quality report ────────────────────
        _print_separator()
        logger.info("  STEP 4: Extraction Quality Report")
        _print_separator()

        # Job fields
        job_fields = [
            "mostaql_id", "title", "url", "brief_description",
            "category", "proposals_count", "time_posted",
        ]
        logger.info("  ── Listing Fields (%d jobs) ──", len(jobs))
        for field in job_fields:
            filled = sum(1 for j in jobs if j.get(field))
            pct = (filled / len(jobs) * 100) if jobs else 0
            status = "✅" if pct == 100 else "⚠️" if pct >= 50 else "❌"
            logger.info("  %s %-22s %d/%d (%.0f%%)", status, field, filled, len(jobs), pct)

        # Detail fields
        if details:
            detail_fields = [
                "full_description", "duration", "publisher_id",
            ]
            logger.info("")
            logger.info("  ── Detail Fields (%d details) ──", len(details))
            for field in detail_fields:
                filled = sum(1 for d in details if d.get(field))
                pct = (filled / len(details) * 100) if details else 0
                status = "✅" if pct == 100 else "⚠️" if pct >= 50 else "❌"
                logger.info("  %s %-22s %d/%d (%.0f%%)", status, field, filled, len(details), pct)

            # Budget fields from jobs that have details
            jobs_with_details = []
            for d in details:
                j = await queries.get_job(db, d["mostaql_id"])
                if j:
                    jobs_with_details.append(j)

            if jobs_with_details:
                logger.info("")
                logger.info("  ── Budget Parsing (%d jobs with details) ──", len(jobs_with_details))
                budget_filled = sum(1 for j in jobs_with_details if j.get("budget_min") is not None)
                skills_filled = sum(
                    1 for j in jobs_with_details
                    if j.get("skills") and j["skills"] != "[]"
                )
                logger.info(
                    "  %s %-22s %d/%d",
                    "✅" if budget_filled == len(jobs_with_details) else "⚠️",
                    "budget_parsed", budget_filled, len(jobs_with_details),
                )
                logger.info(
                    "  %s %-22s %d/%d",
                    "✅" if skills_filled == len(jobs_with_details) else "⚠️",
                    "skills_parsed", skills_filled, len(jobs_with_details),
                )

        # ── Pipeline queries test ────────────────────────
        _print_separator()
        logger.info("  STEP 5: Pipeline Query Verification")
        _print_separator()

        need_details = await queries.get_jobs_needing_details(db)
        need_analysis = await queries.get_jobs_needing_analysis(db)
        today_stats = await queries.get_today_stats(db)

        logger.info("  Jobs needing details:  %d", len(need_details))
        logger.info("  Jobs needing analysis: %d", len(need_analysis))
        logger.info("  Today stats: %s", today_stats)

    logger.info("")
    _print_separator()
    logger.info("  🎉 SCRAPER TEST COMPLETE")
    _print_separator()


if __name__ == "__main__":
    asyncio.run(run_test())
