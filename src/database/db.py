"""Mostaql Notifier — SQLite Connection Manager.

Provides async SQLite database connection management using aiosqlite.
Handles database initialization, schema creation with 6 tables,
indexes, and connection lifecycle.
"""

from __future__ import annotations

import aiosqlite
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Schema Definitions ────────────────────────────────────
SCHEMA_SQL = """
-- ═══ Jobs Table ═══
-- Core job data from the listing page.
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mostaql_id      TEXT    UNIQUE NOT NULL,
    url             TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    brief_description TEXT  DEFAULT '',
    category        TEXT    DEFAULT '',
    budget_min      REAL,
    budget_max      REAL,
    budget_raw      TEXT    DEFAULT '',
    skills          TEXT    DEFAULT '[]',
    proposals_count INTEGER DEFAULT 0,
    time_posted     TEXT    DEFAULT '',
    status          TEXT    DEFAULT 'open',
    first_seen_at   DATETIME DEFAULT (datetime('now', 'localtime'))
);

-- ═══ Job Details Table ═══
-- Extended data from the job detail page.
CREATE TABLE IF NOT EXISTS job_details (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    mostaql_id        TEXT    UNIQUE NOT NULL,
    full_description  TEXT    DEFAULT '',
    duration          TEXT    DEFAULT '',
    experience_level  TEXT    DEFAULT '',
    attachments_count INTEGER DEFAULT 0,
    publisher_id      TEXT,
    scraped_at        DATETIME DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (mostaql_id) REFERENCES jobs(mostaql_id) ON DELETE CASCADE
);

-- ═══ Publishers Table ═══
-- Publisher/client information extracted from job detail pages.
CREATE TABLE IF NOT EXISTS publishers (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_id          TEXT    UNIQUE NOT NULL,
    display_name          TEXT    DEFAULT '',
    role                  TEXT    DEFAULT '',
    profile_url           TEXT    DEFAULT '',
    identity_verified     INTEGER DEFAULT 0,
    registration_date     TEXT    DEFAULT '',
    total_projects_posted INTEGER DEFAULT 0,
    open_projects         INTEGER DEFAULT 0,
    total_hired           INTEGER DEFAULT 0,
    hire_rate_raw         TEXT    DEFAULT '',
    hire_rate             REAL    DEFAULT 0.0,
    avg_rating            REAL,
    last_scraped_at       DATETIME DEFAULT (datetime('now', 'localtime'))
);

-- ═══ Analyses Table ═══
-- AI-generated analysis results for each job.
CREATE TABLE IF NOT EXISTS analyses (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    mostaql_id                 TEXT    UNIQUE NOT NULL,
    hiring_probability         INTEGER DEFAULT 0,
    fit_score                  INTEGER DEFAULT 0,
    budget_fairness            INTEGER DEFAULT 0,
    job_clarity                INTEGER DEFAULT 0,
    competition_level          INTEGER DEFAULT 0,
    urgency_score              INTEGER DEFAULT 0,
    overall_score              INTEGER DEFAULT 0,
    job_summary                TEXT    DEFAULT '',
    required_skills_analysis   TEXT    DEFAULT '',
    red_flags                  TEXT    DEFAULT '[]',
    green_flags                TEXT    DEFAULT '[]',
    recommended_proposal_angle TEXT    DEFAULT '',
    estimated_real_budget      TEXT    DEFAULT '',
    recommendation             TEXT    DEFAULT 'skip',
    recommendation_reason      TEXT    DEFAULT '',
    ai_provider                TEXT    DEFAULT '',
    ai_model                   TEXT    DEFAULT '',
    tokens_used                INTEGER DEFAULT 0,
    analyzed_at                DATETIME DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (mostaql_id) REFERENCES jobs(mostaql_id) ON DELETE CASCADE
);

-- ═══ Notifications Table ═══
-- Records of sent Telegram notifications.
CREATE TABLE IF NOT EXISTS notifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    mostaql_id          TEXT    NOT NULL,
    notification_type   TEXT    NOT NULL,
    telegram_message_id TEXT,
    sent_at             DATETIME DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (mostaql_id) REFERENCES jobs(mostaql_id) ON DELETE CASCADE
);

-- ═══ Proposals Table ═══
-- Visible proposals on a job detail page.
CREATE TABLE IF NOT EXISTS proposals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    mostaql_id        TEXT    NOT NULL,
    proposer_name     TEXT    DEFAULT '',
    proposer_verified INTEGER DEFAULT 0,
    proposer_rating   REAL    DEFAULT 0.0,
    proposed_at       TEXT    DEFAULT '',
    FOREIGN KEY (mostaql_id) REFERENCES jobs(mostaql_id) ON DELETE CASCADE
);

-- ═══ Performance Indexes ═══
CREATE INDEX IF NOT EXISTS idx_jobs_mostaql_id       ON jobs(mostaql_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status            ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen        ON jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_category          ON jobs(category);
CREATE INDEX IF NOT EXISTS idx_details_mostaql_id     ON job_details(mostaql_id);
CREATE INDEX IF NOT EXISTS idx_details_publisher      ON job_details(publisher_id);
CREATE INDEX IF NOT EXISTS idx_publishers_id          ON publishers(publisher_id);
CREATE INDEX IF NOT EXISTS idx_analyses_mostaql_id    ON analyses(mostaql_id);
CREATE INDEX IF NOT EXISTS idx_analyses_recommendation ON analyses(recommendation);
CREATE INDEX IF NOT EXISTS idx_analyses_overall_score ON analyses(overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_analyzed_at   ON analyses(analyzed_at);
CREATE INDEX IF NOT EXISTS idx_notifications_mostaql  ON notifications(mostaql_id);
CREATE INDEX IF NOT EXISTS idx_notifications_type     ON notifications(notification_type);
CREATE INDEX IF NOT EXISTS idx_notifications_sent_at  ON notifications(sent_at);
CREATE INDEX IF NOT EXISTS idx_proposals_mostaql_id   ON proposals(mostaql_id);

-- ═══ Message Queue Table ═══
-- Queues Telegram messages when the API is unavailable.
CREATE TABLE IF NOT EXISTS message_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message     TEXT    NOT NULL,
    msg_type    TEXT    DEFAULT 'general',
    created_at  DATETIME DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_message_queue_created ON message_queue(created_at);
"""


class Database:
    """Async SQLite database connection manager.

    Manages the database lifecycle including initialization, schema creation,
    and a persistent connection with WAL mode and foreign keys enabled.

    Attributes:
        db_path: Resolved absolute path to the SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        """Initialize the database manager.

        Args:
            db_path: Relative or absolute path to the SQLite database file.
                     Parent directories will be created if they don't exist.
        """
        self.db_path = Path(db_path).resolve()
        self._connection: aiosqlite.Connection | None = None
        logger.debug("Database manager initialized with path: %s", self.db_path)

    async def initialize(self) -> None:
        """Create all tables with IF NOT EXISTS and set up pragmas.

        Opens the database connection, enables WAL mode and foreign keys,
        sets the row factory for dict-like access, and executes the full
        schema DDL.
        """
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Connecting to database: %s", self.db_path)
        self._connection = await aiosqlite.connect(str(self.db_path))

        # Enable WAL mode for concurrent reads
        await self._connection.execute("PRAGMA journal_mode=WAL")
        # Enable foreign key constraints
        await self._connection.execute("PRAGMA foreign_keys=ON")
        # Row factory for dict-like access
        self._connection.row_factory = aiosqlite.Row

        # Create schema
        await self._connection.executescript(SCHEMA_SQL)
        await self._connection.commit()

        logger.info("Database initialized — all tables ready")

    async def get_connection(self) -> aiosqlite.Connection:
        """Get the active database connection, initializing if necessary.

        Returns:
            The active aiosqlite connection.

        Raises:
            RuntimeError: If the database was closed and not re-initialized.
        """
        if self._connection is None:
            await self.initialize()
        return self._connection

    async def close(self) -> None:
        """Close the database connection gracefully.

        Safe to call even if the connection is already closed or was
        never opened.
        """
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    async def __aenter__(self) -> "Database":
        """Async context manager entry — initializes the database.

        Returns:
            The Database instance with an active connection.
        """
        await self.initialize()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit — closes the database connection.

        Args:
            *args: Exception info (unused).
        """
        await self.close()
