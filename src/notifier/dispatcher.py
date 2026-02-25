"""Mostaql Notifier — Notification Dispatcher.

Decides what to send and when. Connects the analysis/scoring pipeline
to the Telegram bot by querying the database for unsent notifications
and dispatching them through the appropriate message formatter.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from src.config import AppConfig
from src.database.db import Database
from src.database import queries
from src.notifier.formatters import (
    format_instant_alert,
    format_digest,
    format_daily_report,
    format_system_status,
    _e,
)
from src.notifier.telegram_bot import TelegramNotifier
from src.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationDispatcher:
    """Dispatches formatted Telegram notifications based on DB state.

    Queries the database for pending alerts and digests, formats them,
    and sends them through the TelegramNotifier.

    Attributes:
        config: Full application configuration.
        db: Active database instance.
        telegram: Telegram bot client.
    """

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        telegram: TelegramNotifier,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            config: Full AppConfig.
            db: Active database instance.
            telegram: Connected TelegramNotifier.
        """
        self.config = config
        self.db = db
        self.telegram = telegram
        self._start_time = time.monotonic()

    async def process_instant_alerts(self) -> int:
        """Send unsent instant alert notifications.

        Queries for analyses with recommendation='instant_alert' not
        yet in the notifications table. Formats and sends each one.

        Returns:
            Number of alerts successfully sent.
        """
        rows = await queries.get_unsent_instant_alerts(self.db)
        if not rows:
            logger.debug("No unsent instant alerts")
            return 0

        sent = 0
        for row in rows:
            mostaql_id = row.get("mostaql_id", "?")
            title = row.get("title", "?")[:40]
            try:
                job_data = _build_job_dict(row)
                analysis_data = _build_analysis_dict(row)
                scoring_data = _build_scoring_dict(row)

                text = format_instant_alert(job_data, analysis_data, scoring_data)
                msg_id = await self.telegram.send_instant_alert(text)

                if msg_id:
                    await queries.mark_notified(
                        self.db, mostaql_id, "instant", msg_id,
                    )
                    sent += 1
                    logger.info(
                        "Sent instant alert for %s: %s (msg=%s)",
                        mostaql_id, title, msg_id,
                    )
                else:
                    logger.error(
                        "Failed to send instant alert for %s", mostaql_id,
                    )
            except Exception as e:
                logger.error(
                    "Error processing instant alert for %s: %s",
                    mostaql_id, e,
                )

        logger.info("Instant alerts: %d/%d sent", sent, len(rows))
        return sent

    async def process_digest(self) -> int:
        """Send unsent digest notifications as a batch.

        Collects up to 15 unsent digest jobs, formats as a single
        digest message, and sends it.

        Returns:
            Number of jobs included in the digest.
        """
        rows = await queries.get_unsent_digest_jobs(self.db)
        if not rows:
            logger.debug("No unsent digest jobs")
            return 0

        # Limit to 15, sorted by score desc
        sorted_rows = sorted(
            rows,
            key=lambda r: r.get("overall_score", 0),
            reverse=True,
        )[:15]

        jobs_for_digest = [_build_job_dict(r) | _build_scoring_dict(r) for r in sorted_rows]

        text = format_digest(jobs_for_digest)
        msg_id = await self.telegram.send_digest(text)

        if msg_id:
            for row in sorted_rows:
                mid = row.get("mostaql_id", "")
                if mid:
                    await queries.mark_notified(self.db, mid, "digest", msg_id)
            logger.info("Digest sent with %d jobs (msg=%s)", len(sorted_rows), msg_id)
        else:
            logger.error("Failed to send digest")

        return len(sorted_rows) if msg_id else 0

    async def process_daily_report(self) -> bool:
        """Generate and send the daily report.

        Queries today's stats and top jobs, formats as daily report.

        Returns:
            True if report was sent successfully.
        """
        stats = await queries.get_today_stats(self.db)
        top_jobs = await queries.get_top_jobs_today(self.db, limit=5)

        text = format_daily_report(stats, top_jobs)
        msg_id = await self.telegram.send_daily_report(text)

        if msg_id:
            logger.info("Daily report sent (msg=%s)", msg_id)
            return True
        else:
            logger.error("Failed to send daily report")
            return False

    async def send_startup_message(self) -> None:
        """Send a startup notification with config summary."""
        lines = [
            "🚀 <b>Mostaql Notifier — تم التشغيل</b>",
            "",
            f"⏱ الوقت: {_e(datetime.now().strftime('%Y-%m-%d %H:%M'))}",
            f"🤖 AI: {_e(self.config.ai.primary_provider)} (fallback: {_e(self.config.ai.fallback_provider)})",
            f"📊 فحص كل: {self.config.scraper.scan_interval_seconds} ثانية",
            f"⚡ تنبيه فوري: ≥ {self.config.telegram.instant_alert_threshold}",
            f"📋 ملخص: ≥ {self.config.telegram.digest_threshold}",
        ]
        await self.telegram.send_message("\n".join(lines), disable_preview=True)

    async def send_shutdown_message(self) -> None:
        """Send a shutdown notification."""
        uptime_s = time.monotonic() - self._start_time
        hours = int(uptime_s // 3600)
        mins = int((uptime_s % 3600) // 60)
        uptime_str = f"{hours}h {mins}m" if hours else f"{mins}m"

        lines = [
            "🔴 <b>Mostaql Notifier — تم الإيقاف</b>",
            "",
            f"⏱ مدة التشغيل: {_e(uptime_str)}",
        ]
        await self.telegram.send_message("\n".join(lines), disable_preview=True)

    async def send_error_alert(self, error_msg: str) -> None:
        """Send a critical error notification.

        Args:
            error_msg: Error description.
        """
        lines = [
            "❌ <b>Mostaql Notifier — خطأ</b>",
            "",
            f"⚠️ {_e(error_msg)}",
        ]
        await self.telegram.send_message("\n".join(lines), disable_preview=True)


# ── Helper: build formatted dicts from DB rows ──────────


def _build_job_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Extract job-related fields from a joined DB row.

    Args:
        row: Joined row from DB (jobs + details + publisher).

    Returns:
        Dict with job data fields for formatters.
    """
    import json as _json

    skills_raw = row.get("skills", "[]")
    if isinstance(skills_raw, str):
        try:
            skills = _json.loads(skills_raw)
        except (ValueError, TypeError):
            skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
    else:
        skills = skills_raw or []

    return {
        "mostaql_id": row.get("mostaql_id", ""),
        "title": row.get("title", ""),
        "url": row.get("url", ""),
        "brief_description": row.get("brief_description", ""),
        "full_description": row.get("full_description", ""),
        "category": row.get("category", ""),
        "budget_min": row.get("budget_min"),
        "budget_max": row.get("budget_max"),
        "budget_raw": row.get("budget_raw", ""),
        "duration": row.get("duration", ""),
        "skills": skills,
        "proposals_count": row.get("proposals_count", 0),
        "time_posted": row.get("time_posted", ""),
        "status": row.get("status", ""),
        "publisher_name": row.get("publisher_name", ""),
        "hire_rate": row.get("hire_rate", 0),
        "hire_rate_raw": row.get("hire_rate_raw", ""),
        "identity_verified": bool(row.get("identity_verified", False)),
        "total_projects": row.get("total_projects", 0),
        "open_projects": row.get("open_projects", 0),
        "registration_date": row.get("registration_date", ""),
    }


def _build_analysis_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Extract analysis fields from a joined DB row.

    Args:
        row: Joined row with analysis columns.

    Returns:
        Dict with analysis data fields.
    """
    import json as _json

    red_flags = row.get("red_flags", "[]")
    green_flags = row.get("green_flags", "[]")
    if isinstance(red_flags, str):
        try:
            red_flags = _json.loads(red_flags)
        except (ValueError, TypeError):
            red_flags = []
    if isinstance(green_flags, str):
        try:
            green_flags = _json.loads(green_flags)
        except (ValueError, TypeError):
            green_flags = []

    return {
        "hiring_probability": row.get("hiring_probability", 0),
        "fit_score": row.get("fit_score", 0),
        "budget_fairness": row.get("budget_fairness", 0),
        "job_clarity": row.get("job_clarity", 0),
        "competition_level": row.get("competition_level", 0),
        "urgency_score": row.get("urgency_score", 0),
        "job_summary": row.get("job_summary", ""),
        "required_skills_analysis": row.get("required_skills_analysis", ""),
        "red_flags": red_flags,
        "green_flags": green_flags,
        "recommended_proposal_angle": row.get("recommended_proposal_angle", ""),
        "estimated_real_budget": row.get("estimated_real_budget", ""),
    }


def _build_scoring_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Extract scoring fields from a DB row.

    Args:
        row: Row with scoring/analysis columns.

    Returns:
        Dict with scoring data for formatters.
    """
    return {
        "overall_score": row.get("overall_score", 0),
        "base_score": row.get("overall_score", 0),  # DB stores final score
        "recommendation": row.get("recommendation", "skip"),
        "recommendation_reason": row.get("recommendation_reason", ""),
        "bonuses_applied": [],
        "penalties_applied": [],
    }
