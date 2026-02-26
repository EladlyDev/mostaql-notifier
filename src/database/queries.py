"""Mostaql Notifier — Database Query Operations.

All async database read/write operations. Every function:
  - Uses parameterized queries (? placeholders, never f-strings for SQL)
  - Handles connection via the Database instance
  - Commits after writes
  - Returns clean dictionaries (converts Row objects)
  - Logs operations at DEBUG level
"""

from __future__ import annotations

from typing import Any, Optional

from src.database.db import Database
from src.database.models import (
    AnalysisResult,
    JobDetail,
    JobListing,
    ProposalInfo,
    PublisherInfo,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an aiosqlite Row to a plain dictionary.

    Args:
        row: An aiosqlite.Row object.

    Returns:
        A plain dictionary with column names as keys.
    """
    return dict(row)


# ═══════════════════════════════════════════════════════════
# Job Operations
# ═══════════════════════════════════════════════════════════


async def job_exists(db: Database, mostaql_id: str) -> bool:
    """Check if a job with the given Mostaql ID exists.

    Args:
        db: Active database instance.
        mostaql_id: The unique Mostaql project identifier.

    Returns:
        True if the job exists in the jobs table.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        "SELECT 1 FROM jobs WHERE mostaql_id = ? LIMIT 1",
        (mostaql_id,),
    )
    row = await cursor.fetchone()
    logger.debug("job_exists(%s) = %s", mostaql_id, row is not None)
    return row is not None


async def insert_job(db: Database, job: JobListing) -> None:
    """Insert a new job from the listing page.

    Uses INSERT OR IGNORE to safely handle duplicates on mostaql_id.

    Args:
        db: Active database instance.
        job: JobListing dataclass from the scraper.
    """
    conn = await db.get_connection()
    d = job.to_db_dict()
    await conn.execute(
        """
        INSERT OR IGNORE INTO jobs (
            mostaql_id, url, title, brief_description, category,
            proposals_count, time_posted, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            d["mostaql_id"], d["url"], d["title"], d["brief_description"],
            d["category"], d["proposals_count"], d["time_posted"], d["status"],
        ),
    )
    await conn.commit()
    logger.debug("Inserted job: %s — %s", job.mostaql_id, job.title[:40])


async def update_job_status(db: Database, mostaql_id: str, status: str) -> None:
    """Update the status of a job.

    Args:
        db: Active database instance.
        mostaql_id: The job's Mostaql ID.
        status: New status string (e.g., 'open', 'closed', 'scraped').
    """
    conn = await db.get_connection()
    await conn.execute(
        "UPDATE jobs SET status = ? WHERE mostaql_id = ?",
        (status, mostaql_id),
    )
    await conn.commit()
    logger.debug("Updated job %s status → %s", mostaql_id, status)


async def get_job(db: Database, mostaql_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a single job by its Mostaql ID.

    Args:
        db: Active database instance.
        mostaql_id: The job's Mostaql ID.

    Returns:
        A dictionary of job data, or None if not found.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        "SELECT * FROM jobs WHERE mostaql_id = ?",
        (mostaql_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        logger.debug("get_job(%s) → not found", mostaql_id)
        return None
    logger.debug("get_job(%s) → found", mostaql_id)
    return _row_to_dict(row)


# ═══════════════════════════════════════════════════════════
# Job Detail Operations
# ═══════════════════════════════════════════════════════════


async def has_detail(db: Database, mostaql_id: str) -> bool:
    """Check if job details have been scraped for a given job.

    Args:
        db: Active database instance.
        mostaql_id: The job's Mostaql ID.

    Returns:
        True if a job_details record exists.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        "SELECT 1 FROM job_details WHERE mostaql_id = ? LIMIT 1",
        (mostaql_id,),
    )
    row = await cursor.fetchone()
    logger.debug("has_detail(%s) = %s", mostaql_id, row is not None)
    return row is not None


async def insert_job_detail(db: Database, detail: JobDetail) -> None:
    """Insert job detail data and update budget/skills on the jobs table.

    Also inserts the publisher and proposals if present on the detail.

    Args:
        db: Active database instance.
        detail: JobDetail dataclass from the detail page scraper.
    """
    conn = await db.get_connection()

    # Insert detail record
    d = detail.to_db_dict()
    await conn.execute(
        """
        INSERT OR IGNORE INTO job_details (
            mostaql_id, full_description, duration, experience_level,
            attachments_count, publisher_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            d["mostaql_id"], d["full_description"], d["duration"],
            d["experience_level"], d["attachments_count"], d["publisher_id"],
        ),
    )

    # Update budget and skills on the jobs table
    budget = detail.get_budget_dict()
    await conn.execute(
        """
        UPDATE jobs SET
            budget_min = ?, budget_max = ?, budget_raw = ?, skills = ?
        WHERE mostaql_id = ?
        """,
        (
            budget["budget_min"], budget["budget_max"],
            budget["budget_raw"], budget["skills"],
            detail.mostaql_id,
        ),
    )

    # Insert publisher if present
    if detail.publisher:
        await _upsert_publisher_inner(conn, detail.publisher)

    # Insert proposals if present
    if detail.proposals:
        await _insert_proposals_inner(conn, detail.mostaql_id, detail.proposals)

    await conn.commit()
    logger.debug("Inserted detail for job %s", detail.mostaql_id)


# ═══════════════════════════════════════════════════════════
# Publisher Operations
# ═══════════════════════════════════════════════════════════


async def _upsert_publisher_inner(
    conn: Any, pub: PublisherInfo
) -> None:
    """Insert or update a publisher record (inner, no commit).

    Args:
        conn: Active aiosqlite connection.
        pub: PublisherInfo dataclass.
    """
    d = pub.to_db_dict()
    await conn.execute(
        """
        INSERT INTO publishers (
            publisher_id, display_name, role, profile_url,
            identity_verified, registration_date, total_projects_posted,
            open_projects, total_hired, hire_rate_raw, hire_rate, avg_rating
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(publisher_id) DO UPDATE SET
            display_name = excluded.display_name,
            role = excluded.role,
            profile_url = excluded.profile_url,
            identity_verified = excluded.identity_verified,
            registration_date = excluded.registration_date,
            total_projects_posted = excluded.total_projects_posted,
            open_projects = excluded.open_projects,
            total_hired = excluded.total_hired,
            hire_rate_raw = excluded.hire_rate_raw,
            hire_rate = excluded.hire_rate,
            avg_rating = excluded.avg_rating,
            last_scraped_at = CURRENT_TIMESTAMP
        """,
        (
            d["publisher_id"], d["display_name"], d["role"],
            d["profile_url"], d["identity_verified"],
            d["registration_date"], d["total_projects_posted"],
            d["open_projects"], d["total_hired"],
            d["hire_rate_raw"], d["hire_rate"], d["avg_rating"],
        ),
    )
    logger.debug("Upserted publisher: %s", pub.publisher_id)


async def upsert_publisher(db: Database, pub: PublisherInfo) -> None:
    """Insert or update a publisher record.

    If the publisher_id already exists, updates all fields and
    refreshes last_scraped_at.

    Args:
        db: Active database instance.
        pub: PublisherInfo dataclass.
    """
    conn = await db.get_connection()
    await _upsert_publisher_inner(conn, pub)
    await conn.commit()


async def get_publisher(db: Database, publisher_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a publisher by their unique ID.

    Args:
        db: Active database instance.
        publisher_id: The publisher's derived unique identifier.

    Returns:
        A dictionary of publisher data, or None if not found.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        "SELECT * FROM publishers WHERE publisher_id = ?",
        (publisher_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        logger.debug("get_publisher(%s) → not found", publisher_id)
        return None
    logger.debug("get_publisher(%s) → found", publisher_id)
    return _row_to_dict(row)


# ═══════════════════════════════════════════════════════════
# Proposal Operations
# ═══════════════════════════════════════════════════════════


async def _insert_proposals_inner(
    conn: Any, mostaql_id: str, proposals: list[ProposalInfo]
) -> None:
    """Insert multiple proposals for a job (inner, no commit).

    Args:
        conn: Active aiosqlite connection.
        mostaql_id: The job's Mostaql ID.
        proposals: List of ProposalInfo dataclasses.
    """
    for p in proposals:
        d = p.to_db_dict(mostaql_id)
        await conn.execute(
            """
            INSERT INTO proposals (
                mostaql_id, proposer_name, proposer_verified,
                proposer_rating, proposed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                d["mostaql_id"], d["proposer_name"],
                d["proposer_verified"], d["proposer_rating"],
                d["proposed_at"],
            ),
        )
    logger.debug("Inserted %d proposals for job %s", len(proposals), mostaql_id)


async def insert_proposals(
    db: Database, mostaql_id: str, proposals: list[ProposalInfo]
) -> None:
    """Insert multiple proposals for a job.

    Args:
        db: Active database instance.
        mostaql_id: The job's Mostaql ID.
        proposals: List of ProposalInfo dataclasses.
    """
    conn = await db.get_connection()
    await _insert_proposals_inner(conn, mostaql_id, proposals)
    await conn.commit()


# ═══════════════════════════════════════════════════════════
# Analysis Operations
# ═══════════════════════════════════════════════════════════


async def is_analyzed(db: Database, mostaql_id: str) -> bool:
    """Check if a job has been analyzed by the AI.

    Args:
        db: Active database instance.
        mostaql_id: The job's Mostaql ID.

    Returns:
        True if an analysis record exists.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        "SELECT 1 FROM analyses WHERE mostaql_id = ? LIMIT 1",
        (mostaql_id,),
    )
    row = await cursor.fetchone()
    logger.debug("is_analyzed(%s) = %s", mostaql_id, row is not None)
    return row is not None


async def insert_analysis(db: Database, analysis: AnalysisResult) -> None:
    """Insert an AI analysis result for a job.

    Uses INSERT OR IGNORE so re-analyses do not cause errors.

    Args:
        db: Active database instance.
        analysis: AnalysisResult dataclass from the AI analyzer.
    """
    conn = await db.get_connection()
    d = analysis.to_db_dict()
    await conn.execute(
        """
        INSERT OR IGNORE INTO analyses (
            mostaql_id, hiring_probability, fit_score, budget_fairness,
            job_clarity, competition_level, urgency_score, overall_score,
            job_summary, required_skills_analysis, red_flags, green_flags,
            recommended_proposal_angle, estimated_real_budget,
            recommendation, recommendation_reason,
            ai_provider, ai_model, tokens_used
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            d["mostaql_id"], d["hiring_probability"], d["fit_score"],
            d["budget_fairness"], d["job_clarity"], d["competition_level"],
            d["urgency_score"], d["overall_score"], d["job_summary"],
            d["required_skills_analysis"], d["red_flags"], d["green_flags"],
            d["recommended_proposal_angle"], d["estimated_real_budget"],
            d["recommendation"], d["recommendation_reason"],
            d["ai_provider"], d["ai_model"], d["tokens_used"],
        ),
    )
    await conn.commit()
    logger.debug(
        "Inserted analysis for %s: score=%d, rec=%s",
        analysis.mostaql_id, analysis.overall_score, analysis.recommendation,
    )


# ═══════════════════════════════════════════════════════════
# Pipeline Queries
# ═══════════════════════════════════════════════════════════


async def get_jobs_needing_details(db: Database) -> list[dict[str, Any]]:
    """Get jobs that exist in jobs table but have no job_details record.

    These are jobs discovered from the listing page that need their
    detail page scraped.

    Args:
        db: Active database instance.

    Returns:
        List of job dicts needing detail scraping.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        """
        SELECT j.*
        FROM jobs j
        LEFT JOIN job_details jd ON j.mostaql_id = jd.mostaql_id
        WHERE jd.id IS NULL
        ORDER BY j.first_seen_at DESC
        """
    )
    rows = await cursor.fetchall()
    result = [_row_to_dict(row) for row in rows]
    logger.debug("Jobs needing details: %d", len(result))
    return result


async def get_jobs_needing_analysis(db: Database) -> list[dict[str, Any]]:
    """Get jobs that have details but have not been analyzed yet.

    Joins jobs, job_details, and publishers to return all data the AI
    analysis pipeline needs in a single dictionary per job.

    Args:
        db: Active database instance.

    Returns:
        List of enriched job dicts ready for AI analysis.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        """
        SELECT
            j.mostaql_id, j.url, j.title, j.brief_description,
            j.category, j.budget_min, j.budget_max, j.budget_raw,
            j.skills, j.time_posted, j.status,
            CASE
                WHEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id) > 0
                THEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id)
                ELSE j.proposals_count
            END AS proposals_count,
            jd.full_description, jd.duration, jd.experience_level,
            jd.attachments_count,
            p.publisher_id, p.display_name, p.role AS publisher_role,
            p.identity_verified, p.registration_date,
            p.total_projects_posted, p.open_projects, p.total_hired,
            p.hire_rate_raw, p.hire_rate, p.avg_rating
        FROM jobs j
        INNER JOIN job_details jd ON j.mostaql_id = jd.mostaql_id
        LEFT JOIN publishers p ON jd.publisher_id = p.publisher_id
        LEFT JOIN analyses a ON j.mostaql_id = a.mostaql_id
        WHERE a.id IS NULL
        ORDER BY j.first_seen_at DESC
        """
    )
    rows = await cursor.fetchall()
    result = [_row_to_dict(row) for row in rows]
    logger.debug("Jobs needing analysis: %d", len(result))
    return result


async def get_unsent_instant_alerts(db: Database) -> list[dict[str, Any]]:
    """Get analyzed jobs with recommendation='instant_alert' not yet notified.

    Joins jobs, analyses, and publishers for full notification data.

    Args:
        db: Active database instance.

    Returns:
        List of dicts with job + analysis + publisher data for instant alerts.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        """
        SELECT
            j.mostaql_id, j.title, j.url, j.category,
            j.budget_min, j.budget_max, j.budget_raw,
            j.skills, j.time_posted,
            CASE
                WHEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id) > 0
                THEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id)
                ELSE j.proposals_count
            END AS proposals_count,
            jd.duration,
            a.overall_score, a.job_summary, a.recommendation,
            a.recommendation_reason, a.red_flags, a.green_flags,
            a.recommended_proposal_angle, a.required_skills_analysis,
            a.hiring_probability, a.fit_score, a.budget_fairness,
            a.job_clarity, a.competition_level, a.urgency_score,
            p.display_name AS publisher_name,
            p.identity_verified, p.hire_rate,
            p.total_projects_posted AS total_projects,
            p.open_projects, p.registration_date
        FROM analyses a
        INNER JOIN jobs j ON a.mostaql_id = j.mostaql_id
        LEFT JOIN job_details jd ON j.mostaql_id = jd.mostaql_id
        LEFT JOIN publishers p ON jd.publisher_id = p.publisher_id
        LEFT JOIN notifications n
            ON a.mostaql_id = n.mostaql_id AND n.notification_type = 'instant'
        WHERE a.recommendation = 'instant_alert' AND n.id IS NULL
        ORDER BY a.overall_score DESC
        """
    )
    rows = await cursor.fetchall()
    result = [_row_to_dict(row) for row in rows]
    logger.debug("Unsent instant alerts: %d", len(result))
    return result


async def get_unsent_digest_jobs(db: Database) -> list[dict[str, Any]]:
    """Get analyzed jobs with recommendation='digest' not yet notified.

    Args:
        db: Active database instance.

    Returns:
        List of dicts with job + analysis data for digest notifications.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        """
        SELECT
            j.mostaql_id, j.title, j.url, j.category,
            j.budget_min, j.budget_max, j.budget_raw,
            j.skills, j.time_posted,
            CASE
                WHEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id) > 0
                THEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id)
                ELSE j.proposals_count
            END AS proposals_count,
            jd.duration,
            a.overall_score, a.job_summary, a.recommendation,
            a.recommendation_reason, a.red_flags, a.green_flags,
            a.recommended_proposal_angle, a.required_skills_analysis,
            a.hiring_probability, a.fit_score, a.budget_fairness,
            a.job_clarity, a.competition_level,
            p.display_name AS publisher_name,
            p.identity_verified, p.hire_rate
        FROM analyses a
        INNER JOIN jobs j ON a.mostaql_id = j.mostaql_id
        LEFT JOIN job_details jd ON j.mostaql_id = jd.mostaql_id
        LEFT JOIN publishers p ON jd.publisher_id = p.publisher_id
        LEFT JOIN notifications n
            ON a.mostaql_id = n.mostaql_id AND n.notification_type = 'digest'
        WHERE a.recommendation = 'digest' AND n.id IS NULL
        ORDER BY a.overall_score DESC
        """
    )
    rows = await cursor.fetchall()
    result = [_row_to_dict(row) for row in rows]
    logger.debug("Unsent digest jobs: %d", len(result))
    return result


async def mark_notified(
    db: Database,
    mostaql_id: str,
    notif_type: str,
    msg_id: str,
) -> None:
    """Record that a notification was sent for a job.

    Args:
        db: Active database instance.
        mostaql_id: The job's Mostaql ID.
        notif_type: Type of notification ('instant', 'digest', 'daily_report').
        msg_id: Telegram message ID string.
    """
    conn = await db.get_connection()
    await conn.execute(
        """
        INSERT INTO notifications (mostaql_id, notification_type, telegram_message_id)
        VALUES (?, ?, ?)
        """,
        (mostaql_id, notif_type, msg_id),
    )
    await conn.commit()
    logger.debug("Marked %s as notified (%s), msg_id=%s", mostaql_id, notif_type, msg_id)


# ═══════════════════════════════════════════════════════════
# Statistics Queries
# ═══════════════════════════════════════════════════════════


async def get_today_stats(db: Database) -> dict[str, Any]:
    """Get aggregate statistics for today.

    Counts jobs discovered, analyzed, and notifications sent today.
    Also computes average and maximum scores.

    Args:
        db: Active database instance.

    Returns:
        Dictionary with today's aggregate statistics.
    """
    conn = await db.get_connection()

    stats: dict[str, Any] = {}

    # Jobs discovered today
    cursor = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM jobs WHERE DATE(first_seen_at) = DATE('now', 'localtime')"
    )
    row = await cursor.fetchone()
    stats["jobs_discovered"] = row["cnt"]

    # Jobs analyzed today
    cursor = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM analyses WHERE DATE(analyzed_at) = DATE('now', 'localtime')"
    )
    row = await cursor.fetchone()
    stats["jobs_analyzed"] = row["cnt"]

    # Average and max scores today
    cursor = await conn.execute(
        """
        SELECT
            COALESCE(AVG(overall_score), 0) AS avg_score,
            COALESCE(MAX(overall_score), 0) AS max_score
        FROM analyses
        WHERE DATE(analyzed_at) = DATE('now', 'localtime')
        """
    )
    row = await cursor.fetchone()
    stats["avg_overall_score"] = round(row["avg_score"], 1)
    stats["top_score"] = row["max_score"]

    # Instant alerts sent today
    cursor = await conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM notifications
        WHERE notification_type = 'instant' AND DATE(sent_at) = DATE('now', 'localtime')
        """
    )
    row = await cursor.fetchone()
    stats["instant_alerts_sent"] = row["cnt"]

    # Digest notifications sent today
    cursor = await conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM notifications
        WHERE notification_type = 'digest' AND DATE(sent_at) = DATE('now', 'localtime')
        """
    )
    row = await cursor.fetchone()
    stats["digests_sent"] = row["cnt"]

    logger.debug("Today stats: %s", stats)
    return stats


async def get_top_jobs_today(
    db: Database, limit: int = 5
) -> list[dict[str, Any]]:
    """Get the top-scored jobs analyzed today.

    Joins with jobs and publishers for display-ready data.

    Args:
        db: Active database instance.
        limit: Maximum number of results.

    Returns:
        List of dicts with job + analysis data, ordered by score descending.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        """
        SELECT
            j.mostaql_id, j.title, j.url, j.category,
            j.budget_min, j.budget_max,
            j.skills, j.time_posted,
            CASE
                WHEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id) > 0
                THEN (SELECT COUNT(*) FROM proposals pr WHERE pr.mostaql_id = j.mostaql_id)
                ELSE j.proposals_count
            END AS proposals_count,
            a.overall_score, a.job_summary, a.recommendation,
            a.hiring_probability, a.fit_score,
            p.display_name AS publisher_name,
            p.identity_verified, p.hire_rate
        FROM analyses a
        INNER JOIN jobs j ON a.mostaql_id = j.mostaql_id
        LEFT JOIN job_details jd ON j.mostaql_id = jd.mostaql_id
        LEFT JOIN publishers p ON jd.publisher_id = p.publisher_id
        WHERE DATE(a.analyzed_at) = DATE('now', 'localtime')
        ORDER BY a.overall_score DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    result = [_row_to_dict(row) for row in rows]
    logger.debug("Top %d jobs today: %d results", limit, len(result))
    return result


# ═══════════════════════════════════════════════════════════
# Message Queue Operations
# ═══════════════════════════════════════════════════════════


async def queue_message(
    db: Database, text: str, msg_type: str = "general"
) -> None:
    """Queue a message for later delivery when Telegram is available.

    Args:
        db: Active database instance.
        text: The HTML message text to send later.
        msg_type: Message type ('instant', 'digest', 'general').
    """
    conn = await db.get_connection()
    await conn.execute(
        "INSERT INTO message_queue (message, msg_type) VALUES (?, ?)",
        (text, msg_type),
    )
    await conn.commit()
    logger.debug("Message queued (type=%s, len=%d)", msg_type, len(text))


async def get_queued_messages(db: Database) -> list[dict[str, Any]]:
    """Retrieve all pending messages from the queue.

    Args:
        db: Active database instance.

    Returns:
        List of dicts with id, message, msg_type, created_at.
    """
    conn = await db.get_connection()
    cursor = await conn.execute(
        "SELECT * FROM message_queue ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()
    result = [_row_to_dict(row) for row in rows]
    logger.debug("Queued messages: %d", len(result))
    return result


async def delete_queued_message(db: Database, msg_id: int) -> None:
    """Remove a message from the queue after successful delivery.

    Args:
        db: Active database instance.
        msg_id: The message_queue row ID.
    """
    conn = await db.get_connection()
    await conn.execute("DELETE FROM message_queue WHERE id = ?", (msg_id,))
    await conn.commit()
    logger.debug("Dequeued message %d", msg_id)


# ═══════════════════════════════════════════════════════════
# Database Maintenance
# ═══════════════════════════════════════════════════════════


async def cleanup_old_data(db: Database, days: int = 30) -> int:
    """Delete jobs older than N days that were never alerted.

    Only deletes jobs with recommendation='skip' (never notified).
    Cascades to job_details, analyses, proposals via FK.

    Args:
        db: Active database instance.
        days: Age threshold in days.

    Returns:
        Number of jobs deleted.
    """
    conn = await db.get_connection()

    # Count before
    cursor = await conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM jobs j
        INNER JOIN analyses a ON j.mostaql_id = a.mostaql_id
        WHERE a.recommendation = 'skip'
          AND j.first_seen_at < datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    row = await cursor.fetchone()
    count = row["cnt"]

    if count == 0:
        logger.debug("No old data to clean up (threshold=%d days)", days)
        return 0

    # Delete analyses first (child)
    await conn.execute(
        """
        DELETE FROM analyses
        WHERE mostaql_id IN (
            SELECT j.mostaql_id FROM jobs j
            INNER JOIN analyses a ON j.mostaql_id = a.mostaql_id
            WHERE a.recommendation = 'skip'
              AND j.first_seen_at < datetime('now', ?)
        )
        """,
        (f"-{days} days",),
    )

    # Delete proposals
    await conn.execute(
        """
        DELETE FROM proposals
        WHERE mostaql_id IN (
            SELECT mostaql_id FROM jobs
            WHERE first_seen_at < datetime('now', ?)
              AND mostaql_id NOT IN (SELECT mostaql_id FROM analyses)
        )
        """,
        (f"-{days} days",),
    )

    # Delete job_details
    await conn.execute(
        """
        DELETE FROM job_details
        WHERE mostaql_id IN (
            SELECT mostaql_id FROM jobs
            WHERE first_seen_at < datetime('now', ?)
              AND mostaql_id NOT IN (SELECT mostaql_id FROM analyses)
        )
        """,
        (f"-{days} days",),
    )

    # Delete jobs (parent)
    await conn.execute(
        """
        DELETE FROM jobs
        WHERE first_seen_at < datetime('now', ?)
          AND mostaql_id NOT IN (SELECT mostaql_id FROM analyses)
        """,
        (f"-{days} days",),
    )

    await conn.commit()
    logger.info("Cleaned up %d old skipped jobs (threshold=%d days)", count, days)
    return count


async def vacuum_database(db: Database) -> None:
    """Run VACUUM to reclaim space after cleanup.

    VACUUM rebuilds the database file, reclaiming unused space.
    Must be called outside a transaction.

    Args:
        db: Active database instance.
    """
    conn = await db.get_connection()
    await conn.execute("VACUUM")
    logger.info("Database VACUUM complete")


async def get_database_size(db: Database) -> int:
    """Get the database file size in bytes.

    Args:
        db: Active database instance.

    Returns:
        File size in bytes, or 0 if file not found.
    """
    import os
    try:
        size = os.path.getsize(str(db.db_path))
        logger.debug("Database size: %d bytes (%.1f MB)", size, size / 1024 / 1024)
        return size
    except FileNotFoundError:
        return 0


async def get_total_counts(db: Database) -> dict[str, int]:
    """Get total counts for all main tables.

    Args:
        db: Active database instance.

    Returns:
        Dict with counts for jobs, details, analyses, notifications, proposals.
    """
    conn = await db.get_connection()
    counts = {}

    for table in ["jobs", "job_details", "analyses", "notifications", "proposals"]:
        cursor = await conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
        row = await cursor.fetchone()
        counts[table] = row["cnt"]

    logger.debug("Table counts: %s", counts)
    return counts
