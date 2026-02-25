"""Mostaql Notifier — Job Analyzer Orchestrator.

Ties together the AI client, prompt builder, and response parser
into a single interface for analyzing jobs.
"""

from __future__ import annotations

from typing import Any, Optional

from src.config import AppConfig
from src.analyzer.ai_client import AIClient
from src.analyzer.prompts import build_analysis_prompt
from src.analyzer.response_parser import ResponseParser
from src.database.models import AnalysisResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


class JobAnalyzer:
    """Main analysis orchestrator.

    Manages the AI client lifecycle and provides methods to analyze
    individual jobs or batches using the prompt+parse pipeline.

    Attributes:
        config: Full application configuration.
    """

    def __init__(self, config: AppConfig) -> None:
        """Initialize the analyzer.

        Args:
            config: Full AppConfig with AI and profile settings.
        """
        self.config = config
        self._ai_client = AIClient(config.ai)
        self._profile_dict = self._build_profile_dict()
        self._parser = ResponseParser()

    def _build_profile_dict(self) -> dict[str, Any]:
        """Convert the FreelancerProfile to a clean dict for the prompt.

        Returns:
            Dict with flattened profile fields ready for prompt building.
        """
        profile = self.config.profile
        prefs = profile.preferences

        return {
            "name": profile.name,
            "expert_skills": profile.skills.get("expert", []),
            "intermediate_skills": profile.skills.get("intermediate", []),
            "beginner_skills": profile.skills.get("beginner", []),
            "experience_years": profile.experience_years,
            "preferred_budget_range": (
                f"${prefs.get('min_budget_usd', 0)}-${prefs.get('max_budget_usd', 5000)}"
            ),
            "preferred_categories": prefs.get("preferred_categories", []),
            "positive_keywords": prefs.get("positive_keywords", []),
            "negative_keywords": prefs.get("negative_keywords", []),
            "bio": profile.bio,
        }

    async def __aenter__(self) -> "JobAnalyzer":
        """Enter the AI client context.

        Returns:
            The JobAnalyzer instance with an active AI client.
        """
        await self._ai_client.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the AI client context.

        Args:
            *args: Exception info (unused).
        """
        await self._ai_client.__aexit__(*args)

    async def analyze_job(
        self, job_data: dict[str, Any]
    ) -> Optional[AnalysisResult]:
        """Analyze a single job and return an AnalysisResult.

        Pipeline: build prompt → send to AI → parse response.

        Args:
            job_data: Dict with all available job fields.

        Returns:
            An AnalysisResult instance, or None if analysis failed.
        """
        mostaql_id = str(job_data.get("mostaql_id", "unknown"))
        title = job_data.get("title", "?")

        logger.info("Analyzing job %s: %s", mostaql_id, title[:50])

        # Build prompt
        prompt = build_analysis_prompt(job_data, self._profile_dict)

        # Send to AI (primary + fallback handled internally)
        raw = await self._ai_client.analyze(prompt)

        if raw is None:
            logger.error(
                "AI analysis failed for %s — both providers returned None",
                mostaql_id,
            )
            return None

        # Parse response
        result = self._parser.parse_analysis(raw, mostaql_id)

        if result is None:
            logger.error(
                "Failed to parse AI response for %s. Raw (first 500): %s",
                mostaql_id, str(raw)[:500],
            )
            return None

        # Validate
        warnings = self._parser.validate_scores(result)
        if warnings:
            for w in warnings:
                logger.warning("Validation: %s (%s)", w, mostaql_id)

        logger.info(
            "Analysis complete for %s: overall=%d, rec=%s, provider=%s, %d tokens",
            mostaql_id, result.overall_score, result.recommendation,
            result.ai_provider, result.tokens_used,
        )

        return result

    async def analyze_batch(
        self, jobs: list[dict[str, Any]]
    ) -> list[AnalysisResult]:
        """Analyze multiple jobs sequentially, respecting rate limits.

        Skips failures and continues with remaining jobs.

        Args:
            jobs: List of job data dicts to analyze.

        Returns:
            List of successfully parsed AnalysisResult instances.
        """
        results: list[AnalysisResult] = []
        total = len(jobs)

        for i, job_data in enumerate(jobs, 1):
            title = job_data.get("title", "?")[:40]
            logger.info("Analyzing job %d/%d: %s", i, total, title)

            result = await self.analyze_job(job_data)
            if result is not None:
                results.append(result)
            else:
                logger.warning("Skipped job %d/%d (analysis failed)", i, total)

        logger.info(
            "Batch analysis complete: %d/%d successful",
            len(results), total,
        )

        return results
