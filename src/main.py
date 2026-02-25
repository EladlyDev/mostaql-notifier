"""Mostaql Notifier — Main Orchestrator.

Ties all components together: config, database, scraper, analyzer,
scorer, and Telegram notifier. Runs on a schedule with APScheduler.

Usage:
    python -m src.main
    python scripts/run.py
"""

from __future__ import annotations

import asyncio
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import AppConfig, load_config
from src.database.db import Database
from src.database import queries
from src.analyzer.analyzer import JobAnalyzer
from src.scorer.scoring import ScoringEngine
from src.scraper.pipeline import ScraperPipeline
from src.notifier.telegram_bot import TelegramNotifier
from src.notifier.dispatcher import NotificationDispatcher
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MostaqlNotifier:
    """Main application orchestrator.

    Manages the complete pipeline: scrape → analyze → score → notify.
    Runs continuously with scheduled scan cycles, digest sends,
    and daily reports.

    Attributes:
        config: Full application configuration.
        db: Active database instance.
        scheduler: APScheduler AsyncIOScheduler.
    """

    def __init__(self) -> None:
        """Initialize with default state. Call start() to run."""
        self.config: Optional[AppConfig] = None
        self.db: Optional[Database] = None
        self._telegram: Optional[TelegramNotifier] = None
        self._dispatcher: Optional[NotificationDispatcher] = None
        self._scorer: Optional[ScoringEngine] = None
        self._scheduler: Optional[AsyncIOScheduler] = None

        # Internal state
        self._running = False
        self._paused = False
        self._cycle_count = 0
        self._errors_count = 0
        self._start_time: float = 0.0
        self._last_cycle_time: Optional[str] = None
        self._cycle_lock = asyncio.Lock()

    async def start(self) -> None:
        """Full application startup sequence.

        1. Load config
        2. Initialize database
        3. Initialize Telegram bot
        4. Setup APScheduler with three jobs
        5. Run first scan cycle immediately
        6. Enter keep-alive loop
        """
        self._start_time = time.monotonic()
        self._running = True

        try:
            # ── 1. Config ────────────────────────────────
            logger.info("═══ Loading configuration ═══")
            self.config = load_config()

            # ── 2. Database ──────────────────────────────
            logger.info("═══ Initializing database ═══")
            self.db = Database(self.config.database_path)
            await self.db.initialize()
            logger.info("Database ready: %s", self.config.database_path)

            # ── 3. Components ────────────────────────────
            logger.info("═══ Initializing components ═══")
            self._telegram = TelegramNotifier(self.config.telegram)
            connected = await self._telegram.initialize()
            if not connected:
                logger.error("Telegram bot connection failed! Continuing anyway...")

            self._dispatcher = NotificationDispatcher(
                self.config, self.db, self._telegram,
            )
            self._scorer = ScoringEngine(
                self.config.scoring,
                instant_threshold=self.config.telegram.instant_alert_threshold,
                digest_threshold=self.config.telegram.digest_threshold,
            )

            # ── 4. Startup message ───────────────────────
            await self._dispatcher.send_startup_message()

            # ── 5. Scheduler ────────────────────────────
            logger.info("═══ Setting up scheduler ═══")
            self._scheduler = AsyncIOScheduler()

            scan_interval = self.config.scraper.scan_interval_seconds
            self._scheduler.add_job(
                self.run_scan_cycle,
                IntervalTrigger(seconds=scan_interval),
                id="scan_cycle",
                max_instances=1,
                misfire_grace_time=60,
                name=f"Scan cycle (every {scan_interval}s)",
            )

            digest_minutes = self.config.telegram.digest_interval_minutes
            self._scheduler.add_job(
                self._run_digest,
                IntervalTrigger(minutes=digest_minutes),
                id="digest",
                max_instances=1,
                name=f"Digest (every {digest_minutes}m)",
            )

            report_hour = self.config.telegram.daily_report_hour
            report_minute = self.config.telegram.daily_report_minute
            self._scheduler.add_job(
                self._run_daily_report,
                CronTrigger(hour=report_hour, minute=report_minute),
                id="daily_report",
                max_instances=1,
                name=f"Daily report ({report_hour}:{report_minute:02d})",
            )

            self._scheduler.start()
            logger.info("Scheduler started with 3 jobs")

            # ── 6. First scan immediately ────────────────
            logger.info("═══ Running first scan cycle ═══")
            await self.run_scan_cycle()

            # ── 7. Keep alive ────────────────────────────
            logger.info("═══ Entering main loop ═══")
            while self._running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")
        except Exception as e:
            logger.error("Fatal error: %s", e)
            logger.error(traceback.format_exc())
            if self._dispatcher:
                try:
                    await self._dispatcher.send_error_alert(
                        f"خطأ قاتل: {str(e)[:200]}"
                    )
                except Exception:
                    pass
        finally:
            await self.shutdown()

    async def run_scan_cycle(self) -> None:
        """Run one complete scan-analyze-score-notify cycle.

        Idempotent: if it crashes partway, next cycle picks up
        from DB state. Protected by async lock to prevent overlap.
        """
        if self._paused:
            logger.info("Scan cycle skipped (paused)")
            return

        if self._cycle_lock.locked():
            logger.warning("Previous scan cycle still running, skipping")
            return

        async with self._cycle_lock:
            self._cycle_count += 1
            cycle_num = self._cycle_count
            cycle_start = time.monotonic()
            self._last_cycle_time = datetime.now().strftime("%H:%M:%S")

            logger.info(
                "╔══════════════════════════════════════════╗"
            )
            logger.info(
                "║  Scan Cycle #%d — %s  ║",
                cycle_num, self._last_cycle_time,
            )
            logger.info(
                "╚══════════════════════════════════════════╝"
            )

            stats = {
                "new_jobs": 0, "analyzed": 0, "alerts_sent": 0,
                "errors": 0, "skipped_analysis": 0,
            }

            try:
                # ── Step 1-4: Scraper pipeline ───────────
                pipeline = ScraperPipeline(self.config, self.db)
                scrape_stats = await pipeline.run_scrape_cycle()
                stats["new_jobs"] = scrape_stats.get("new_jobs", 0)
                stats["errors"] += scrape_stats.get("errors", 0)

                # ── Step 5-6: Analyze + Score ────────────
                jobs_to_analyze = await queries.get_jobs_needing_analysis(self.db)

                if jobs_to_analyze:
                    logger.info(
                        "═══ Analyzing %d jobs ═══", len(jobs_to_analyze),
                    )
                    consecutive_failures = 0

                    async with JobAnalyzer(self.config) as analyzer:
                        for i, job_data in enumerate(jobs_to_analyze, 1):
                            mid = job_data.get("mostaql_id", "?")
                            try:
                                logger.info(
                                    "  [%d/%d] Analyzing %s...",
                                    i, len(jobs_to_analyze), mid,
                                )

                                analysis = await analyzer.analyze_job(job_data)
                                if analysis is None:
                                    consecutive_failures += 1
                                    stats["errors"] += 1
                                    logger.error("Analysis returned None for %s", mid)
                                    continue

                                # Score it
                                scored = self._scorer.score(analysis, job_data)

                                # Update analysis with final score/recommendation
                                analysis.overall_score = scored.overall_score
                                analysis.recommendation = scored.recommendation
                                analysis.recommendation_reason = scored.recommendation_reason

                                # Persist
                                await queries.insert_analysis(self.db, analysis)
                                stats["analyzed"] += 1
                                consecutive_failures = 0

                            except Exception as e:
                                consecutive_failures += 1
                                stats["errors"] += 1
                                logger.error(
                                    "Error analyzing %s: %s", mid, e,
                                )

                            # Safety: if 5+ consecutive failures, alert and stop
                            if consecutive_failures >= 5:
                                logger.error(
                                    "5 consecutive analysis failures! Stopping analysis."
                                )
                                if self._dispatcher:
                                    await self._dispatcher.send_error_alert(
                                        "5 تحليلات فشلت متتالية — تم إيقاف تحليل هذه الدورة"
                                    )
                                break
                else:
                    logger.info("No jobs needing analysis")

                # ── Step 7: Send instant alerts ──────────
                if self._dispatcher:
                    alerts_sent = await self._dispatcher.process_instant_alerts()
                    stats["alerts_sent"] = alerts_sent

            except Exception as e:
                stats["errors"] += 1
                self._errors_count += 1
                logger.error("Scan cycle error: %s", e)
                logger.error(traceback.format_exc())

            # ── Log summary ──────────────────────────────
            elapsed = time.monotonic() - cycle_start
            self._errors_count += stats["errors"]

            logger.info("═══ Cycle #%d Complete ═══", cycle_num)
            logger.info(
                "  New: %d | Analyzed: %d | Alerts: %d | "
                "Errors: %d | Time: %.1fs",
                stats["new_jobs"], stats["analyzed"],
                stats["alerts_sent"], stats["errors"], elapsed,
            )

    async def _run_digest(self) -> None:
        """Send hourly digest of moderate-interest jobs."""
        try:
            if self._dispatcher:
                count = await self._dispatcher.process_digest()
                if count > 0:
                    logger.info("Digest sent with %d jobs", count)
        except Exception as e:
            logger.error("Digest error: %s", e)

    async def _run_daily_report(self) -> None:
        """Send daily report."""
        try:
            if self._dispatcher:
                success = await self._dispatcher.process_daily_report()
                if success:
                    logger.info("Daily report sent")
        except Exception as e:
            logger.error("Daily report error: %s", e)

    async def shutdown(self) -> None:
        """Graceful shutdown: stop scheduler, notify, close connections."""
        logger.info("═══ Shutting down ═══")
        self._running = False

        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

        if self._dispatcher:
            try:
                await self._dispatcher.send_shutdown_message()
            except Exception as e:
                logger.warning("Failed to send shutdown message: %s", e)

        if self.db:
            try:
                await self.db.close()
            except Exception:
                pass

        logger.info("Shutdown complete")

    # ── Public state accessors (for commands) ────────────

    @property
    def is_paused(self) -> bool:
        """Whether scanning is paused."""
        return self._paused

    @property
    def cycle_count(self) -> int:
        """Total scan cycles completed."""
        return self._cycle_count

    @property
    def errors_count(self) -> int:
        """Total errors across all cycles."""
        return self._errors_count

    @property
    def last_cycle_time(self) -> Optional[str]:
        """Time of last scan cycle."""
        return self._last_cycle_time

    @property
    def uptime(self) -> str:
        """Human-readable uptime string."""
        if not self._start_time:
            return "0m"
        s = time.monotonic() - self._start_time
        hours = int(s // 3600)
        mins = int((s % 3600) // 60)
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    def pause(self) -> None:
        """Pause scanning."""
        self._paused = True
        logger.info("Scanning PAUSED")

    def resume(self) -> None:
        """Resume scanning."""
        self._paused = False
        logger.info("Scanning RESUMED")


def main() -> None:
    """Application entry point."""
    # Ensure directories exist
    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    # Load .env
    from dotenv import load_dotenv
    load_dotenv()

    app = MostaqlNotifier()

    # Signal handlers
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal_handler(sig, frame):
        logger.info("Signal %s received, shutting down...", sig)
        app._running = False

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        loop.run_until_complete(app.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
