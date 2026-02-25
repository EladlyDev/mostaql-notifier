"""Mostaql Notifier — Data Models.

Dataclasses representing all entities in the system: jobs from listing
and detail pages, publisher info, proposals, AI analysis results,
scored jobs for notification, and daily aggregate statistics.

Each dataclass includes:
  - to_db_dict(): converts to a dict suitable for SQLite insertion
  - from_db_row(row): classmethod to reconstruct from a DB row dict
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════
# Scraper Models
# ═══════════════════════════════════════════════════════════


@dataclass
class JobListing:
    """A job as seen on the listing page (XHR response).

    Contains the minimal data available from the project listing
    before visiting the detail page.

    Attributes:
        mostaql_id: Unique project ID from Mostaql.
        title: Job title (Arabic text).
        url: Full URL to the job page.
        publisher_name: Name of the job publisher.
        time_posted: Relative time string (e.g., "منذ ساعة").
        brief_description: Truncated description from listing.
        category: Job category if available from listing.
        proposals_count: Number of proposals if visible.
        status: Job status, defaults to 'open'.
    """

    mostaql_id: str
    title: str
    url: str
    publisher_name: str = ""
    time_posted: str = ""
    brief_description: str = ""
    category: str = ""
    proposals_count: int = 0
    status: str = "open"

    def to_db_dict(self) -> dict[str, Any]:
        """Convert to a dictionary for SQLite insertion.

        Returns:
            Dict with column names as keys, values ready for SQL params.
        """
        return {
            "mostaql_id": self.mostaql_id,
            "title": self.title,
            "url": self.url,
            "publisher_name": self.publisher_name,
            "time_posted": self.time_posted,
            "brief_description": self.brief_description,
            "category": self.category,
            "proposals_count": self.proposals_count,
            "status": self.status,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "JobListing":
        """Construct a JobListing from a database row dictionary.

        Args:
            row: Dictionary with column names as keys.

        Returns:
            A JobListing instance.
        """
        return cls(
            mostaql_id=row["mostaql_id"],
            title=row["title"],
            url=row["url"],
            publisher_name=row.get("publisher_name", ""),
            time_posted=row.get("time_posted", ""),
            brief_description=row.get("brief_description", ""),
            category=row.get("category", ""),
            proposals_count=row.get("proposals_count", 0),
            status=row.get("status", "open"),
        )


@dataclass
class PublisherInfo:
    """Publisher information extracted from a job detail page.

    Attributes:
        publisher_id: Derived unique identifier (from name or profile URL).
        display_name: Publisher's display name.
        role: Role description (e.g., "صاحب مشروع", "مطور ويب").
        profile_url: URL to the publisher's Mostaql profile.
        identity_verified: Whether the publisher is identity-verified.
        registration_date: Registration date string (e.g., "25 فبراير 2026").
        total_projects_posted: Total projects ever posted.
        open_projects: Currently open projects.
        total_hired: Total freelancers ever hired.
        hire_rate_raw: Raw hire rate text (e.g., "80%" or "لم يحسب بعد").
        hire_rate: Parsed hire rate as a float (0.0 if unparseable).
        avg_rating: Average rating if available.
    """

    publisher_id: str
    display_name: str = ""
    role: str = ""
    profile_url: str = ""
    identity_verified: bool = False
    registration_date: str = ""
    total_projects_posted: int = 0
    open_projects: int = 0
    total_hired: int = 0
    hire_rate_raw: str = ""
    hire_rate: float = 0.0
    avg_rating: Optional[float] = None

    def to_db_dict(self) -> dict[str, Any]:
        """Convert to a dictionary for SQLite insertion.

        Returns:
            Dict with column names as keys, bools converted to int.
        """
        return {
            "publisher_id": self.publisher_id,
            "display_name": self.display_name,
            "role": self.role,
            "profile_url": self.profile_url,
            "identity_verified": int(self.identity_verified),
            "registration_date": self.registration_date,
            "total_projects_posted": self.total_projects_posted,
            "open_projects": self.open_projects,
            "total_hired": self.total_hired,
            "hire_rate_raw": self.hire_rate_raw,
            "hire_rate": self.hire_rate,
            "avg_rating": self.avg_rating,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "PublisherInfo":
        """Construct a PublisherInfo from a database row dictionary.

        Args:
            row: Dictionary with column names as keys.

        Returns:
            A PublisherInfo instance.
        """
        return cls(
            publisher_id=row["publisher_id"],
            display_name=row.get("display_name", ""),
            role=row.get("role", ""),
            profile_url=row.get("profile_url", ""),
            identity_verified=bool(row.get("identity_verified", 0)),
            registration_date=row.get("registration_date", ""),
            total_projects_posted=row.get("total_projects_posted", 0),
            open_projects=row.get("open_projects", 0),
            total_hired=row.get("total_hired", 0),
            hire_rate_raw=row.get("hire_rate_raw", ""),
            hire_rate=row.get("hire_rate", 0.0),
            avg_rating=row.get("avg_rating"),
        )


@dataclass
class ProposalInfo:
    """A visible proposal on a job detail page.

    Attributes:
        proposer_name: Name of the freelancer who proposed.
        proposer_verified: Whether the proposer is verified.
        proposer_rating: Rating of the proposer (0.0 if not rated).
        proposed_at: Date/time string of the proposal.
    """

    proposer_name: str
    proposer_verified: bool = False
    proposer_rating: float = 0.0
    proposed_at: str = ""

    def to_db_dict(self, mostaql_id: str) -> dict[str, Any]:
        """Convert to a dictionary for SQLite insertion.

        Args:
            mostaql_id: The job's Mostaql ID to link this proposal to.

        Returns:
            Dict with column names as keys, bools converted to int.
        """
        return {
            "mostaql_id": mostaql_id,
            "proposer_name": self.proposer_name,
            "proposer_verified": int(self.proposer_verified),
            "proposer_rating": self.proposer_rating,
            "proposed_at": self.proposed_at,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "ProposalInfo":
        """Construct a ProposalInfo from a database row dictionary.

        Args:
            row: Dictionary with column names as keys.

        Returns:
            A ProposalInfo instance.
        """
        return cls(
            proposer_name=row["proposer_name"],
            proposer_verified=bool(row.get("proposer_verified", 0)),
            proposer_rating=row.get("proposer_rating", 0.0),
            proposed_at=row.get("proposed_at", ""),
        )


@dataclass
class JobDetail:
    """Full detail data from a job's detail page.

    Extends listing data with the complete description, parsed budget,
    duration, skills, publisher info, and visible proposals.

    Attributes:
        mostaql_id: Unique project ID from Mostaql.
        full_description: Complete job description text.
        duration: Expected project duration string.
        experience_level: Required experience level if specified.
        budget_min: Parsed minimum budget in USD.
        budget_max: Parsed maximum budget in USD.
        budget_raw: Original budget string before parsing.
        skills: List of required skill strings.
        attachments_count: Number of attachments on the job.
        publisher: Publisher information dataclass.
        proposals: List of visible proposals.
    """

    mostaql_id: str
    full_description: str = ""
    duration: str = ""
    experience_level: str = ""
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    budget_raw: str = ""
    skills: list[str] = field(default_factory=list)
    attachments_count: int = 0
    publisher: Optional[PublisherInfo] = None
    proposals: list[ProposalInfo] = field(default_factory=list)

    def to_db_dict(self) -> dict[str, Any]:
        """Convert to a dictionary for SQLite insertion.

        Lists are serialized to JSON strings. Publisher and proposals
        are handled separately by their own insert operations.

        Returns:
            Dict with column names as keys for the job_details table.
        """
        return {
            "mostaql_id": self.mostaql_id,
            "full_description": self.full_description,
            "duration": self.duration,
            "experience_level": self.experience_level,
            "attachments_count": self.attachments_count,
            "publisher_id": self.publisher.publisher_id if self.publisher else None,
        }

    def get_budget_dict(self) -> dict[str, Any]:
        """Get budget fields for updating the jobs table.

        Returns:
            Dict with budget_min, budget_max, budget_raw, and skills as JSON.
        """
        return {
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "budget_raw": self.budget_raw,
            "skills": json.dumps(self.skills, ensure_ascii=False),
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "JobDetail":
        """Construct a JobDetail from a database row dictionary.

        Args:
            row: Dictionary with column names as keys.

        Returns:
            A JobDetail instance (without publisher/proposals — load separately).
        """
        return cls(
            mostaql_id=row["mostaql_id"],
            full_description=row.get("full_description", ""),
            duration=row.get("duration", ""),
            experience_level=row.get("experience_level", ""),
            budget_min=row.get("budget_min"),
            budget_max=row.get("budget_max"),
            budget_raw=row.get("budget_raw", ""),
            skills=json.loads(row["skills"]) if row.get("skills") else [],
            attachments_count=row.get("attachments_count", 0),
        )


# ═══════════════════════════════════════════════════════════
# Analysis & Scoring Models
# ═══════════════════════════════════════════════════════════


@dataclass
class AnalysisResult:
    """AI-generated analysis of a job listing.

    Produced by the Gemini or Groq AI provider after evaluating
    the job against the freelancer's profile.

    Attributes:
        mostaql_id: The analyzed job's Mostaql ID.
        hiring_probability: Estimated chance of being hired (0-100).
        fit_score: How well the job matches the profile (0-100).
        budget_fairness: Budget reasonableness assessment (0-100).
        job_clarity: Description clarity and detail level (0-100).
        competition_level: Competitiveness based on proposals (0-100).
        urgency_score: Perceived urgency of the project (0-100).
        overall_score: Weighted overall score (0-100).
        job_summary: Brief AI-generated summary (Arabic).
        required_skills_analysis: Skills match analysis (Arabic).
        red_flags: List of warning signs identified.
        green_flags: List of positive indicators identified.
        recommended_proposal_angle: Suggested proposal approach (Arabic).
        estimated_real_budget: AI estimate of true budget range.
        recommendation: Action recommendation ('instant_alert', 'digest', 'skip').
        recommendation_reason: Explanation for the recommendation.
        ai_provider: Provider used ('gemini' or 'groq').
        ai_model: Specific model name used.
        tokens_used: Total tokens consumed for this analysis.
    """

    mostaql_id: str
    hiring_probability: int = 0
    fit_score: int = 0
    budget_fairness: int = 0
    job_clarity: int = 0
    competition_level: int = 0
    urgency_score: int = 0
    overall_score: int = 0
    job_summary: str = ""
    required_skills_analysis: str = ""
    red_flags: list[str] = field(default_factory=list)
    green_flags: list[str] = field(default_factory=list)
    recommended_proposal_angle: str = ""
    estimated_real_budget: str = ""
    recommendation: str = "skip"
    recommendation_reason: str = ""
    ai_provider: str = ""
    ai_model: str = ""
    tokens_used: int = 0

    def to_db_dict(self) -> dict[str, Any]:
        """Convert to a dictionary for SQLite insertion.

        Lists are serialized to JSON strings.

        Returns:
            Dict with column names as keys for the analyses table.
        """
        return {
            "mostaql_id": self.mostaql_id,
            "hiring_probability": self.hiring_probability,
            "fit_score": self.fit_score,
            "budget_fairness": self.budget_fairness,
            "job_clarity": self.job_clarity,
            "competition_level": self.competition_level,
            "urgency_score": self.urgency_score,
            "overall_score": self.overall_score,
            "job_summary": self.job_summary,
            "required_skills_analysis": self.required_skills_analysis,
            "red_flags": json.dumps(self.red_flags, ensure_ascii=False),
            "green_flags": json.dumps(self.green_flags, ensure_ascii=False),
            "recommended_proposal_angle": self.recommended_proposal_angle,
            "estimated_real_budget": self.estimated_real_budget,
            "recommendation": self.recommendation,
            "recommendation_reason": self.recommendation_reason,
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model,
            "tokens_used": self.tokens_used,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "AnalysisResult":
        """Construct an AnalysisResult from a database row dictionary.

        Args:
            row: Dictionary with column names as keys.

        Returns:
            An AnalysisResult instance with JSON lists deserialized.
        """
        return cls(
            mostaql_id=row["mostaql_id"],
            hiring_probability=row.get("hiring_probability", 0),
            fit_score=row.get("fit_score", 0),
            budget_fairness=row.get("budget_fairness", 0),
            job_clarity=row.get("job_clarity", 0),
            competition_level=row.get("competition_level", 0),
            urgency_score=row.get("urgency_score", 0),
            overall_score=row.get("overall_score", 0),
            job_summary=row.get("job_summary", ""),
            required_skills_analysis=row.get("required_skills_analysis", ""),
            red_flags=json.loads(row["red_flags"]) if row.get("red_flags") else [],
            green_flags=json.loads(row["green_flags"]) if row.get("green_flags") else [],
            recommended_proposal_angle=row.get("recommended_proposal_angle", ""),
            estimated_real_budget=row.get("estimated_real_budget", ""),
            recommendation=row.get("recommendation", "skip"),
            recommendation_reason=row.get("recommendation_reason", ""),
            ai_provider=row.get("ai_provider", ""),
            ai_model=row.get("ai_model", ""),
            tokens_used=row.get("tokens_used", 0),
        )


# ═══════════════════════════════════════════════════════════
# Composite / View Models
# ═══════════════════════════════════════════════════════════


@dataclass
class ScoredJob:
    """Combined job + analysis + score data for notification rendering.

    This is a read-only view model assembled from joined query results.
    Not stored directly — constructed from multi-table joins.

    Attributes:
        mostaql_id: The job's Mostaql ID.
        title: Job title.
        url: Job URL.
        category: Job category.
        budget_min: Parsed minimum budget.
        budget_max: Parsed maximum budget.
        skills: List of required skills.
        proposals_count: Number of proposals.
        publisher_name: Publisher's display name.
        publisher_verified: Whether the publisher is verified.
        hire_rate: Publisher's parsed hire rate.
        overall_score: Final weighted score.
        job_summary: AI-generated summary.
        recommendation: AI recommendation action.
        recommendation_reason: Explanation for recommendation.
        red_flags: Warning signs identified.
        green_flags: Positive indicators identified.
        recommended_proposal_angle: Suggested proposal approach.
    """

    mostaql_id: str
    title: str = ""
    url: str = ""
    category: str = ""
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    skills: list[str] = field(default_factory=list)
    proposals_count: int = 0
    publisher_name: str = ""
    publisher_verified: bool = False
    hire_rate: float = 0.0
    overall_score: int = 0
    job_summary: str = ""
    recommendation: str = ""
    recommendation_reason: str = ""
    red_flags: list[str] = field(default_factory=list)
    green_flags: list[str] = field(default_factory=list)
    recommended_proposal_angle: str = ""

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "ScoredJob":
        """Construct a ScoredJob from a joined query row.

        Args:
            row: Dictionary from a multi-table join query.

        Returns:
            A ScoredJob instance.
        """
        return cls(
            mostaql_id=row["mostaql_id"],
            title=row.get("title", ""),
            url=row.get("url", ""),
            category=row.get("category", ""),
            budget_min=row.get("budget_min"),
            budget_max=row.get("budget_max"),
            skills=json.loads(row["skills"]) if row.get("skills") else [],
            proposals_count=row.get("proposals_count", 0),
            publisher_name=row.get("display_name", row.get("publisher_name", "")),
            publisher_verified=bool(row.get("identity_verified", 0)),
            hire_rate=row.get("hire_rate", 0.0),
            overall_score=row.get("overall_score", 0),
            job_summary=row.get("job_summary", ""),
            recommendation=row.get("recommendation", ""),
            recommendation_reason=row.get("recommendation_reason", ""),
            red_flags=json.loads(row["red_flags"]) if row.get("red_flags") else [],
            green_flags=json.loads(row["green_flags"]) if row.get("green_flags") else [],
            recommended_proposal_angle=row.get("recommended_proposal_angle", ""),
        )


@dataclass
class DailyStats:
    """Aggregated statistics for a daily report.

    Assembled from aggregate queries across multiple tables.

    Attributes:
        date: The date these stats cover (YYYY-MM-DD).
        jobs_discovered: Number of new jobs found today.
        jobs_analyzed: Number of jobs analyzed today.
        instant_alerts_sent: Number of instant alert notifications sent.
        digests_sent: Number of digest notifications sent.
        avg_overall_score: Average overall score of analyzed jobs.
        top_score: Highest score seen today.
        top_job_title: Title of the highest-scored job.
        top_job_url: URL of the highest-scored job.
    """

    date: str = ""
    jobs_discovered: int = 0
    jobs_analyzed: int = 0
    instant_alerts_sent: int = 0
    digests_sent: int = 0
    avg_overall_score: float = 0.0
    top_score: int = 0
    top_job_title: str = ""
    top_job_url: str = ""

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "DailyStats":
        """Construct DailyStats from an aggregate query result.

        Args:
            row: Dictionary from the stats aggregate query.

        Returns:
            A DailyStats instance.
        """
        return cls(
            date=row.get("date", ""),
            jobs_discovered=row.get("jobs_discovered", 0),
            jobs_analyzed=row.get("jobs_analyzed", 0),
            instant_alerts_sent=row.get("instant_alerts_sent", 0),
            digests_sent=row.get("digests_sent", 0),
            avg_overall_score=row.get("avg_overall_score", 0.0),
            top_score=row.get("top_score", 0),
            top_job_title=row.get("top_job_title", ""),
            top_job_url=row.get("top_job_url", ""),
        )
