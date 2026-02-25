"""Mostaql Notifier — AI Response Parser.

Validates and normalizes raw AI response dicts into AnalysisResult
dataclass instances. Handles missing fields, type coercion, score
clamping, and structural issues gracefully.
"""

from __future__ import annotations

from typing import Any, Optional

from src.database.models import AnalysisResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Score field names and their defaults
_SCORE_FIELDS = [
    "hiring_probability",
    "fit_score",
    "budget_fairness",
    "job_clarity",
    "competition_level",
    "urgency_score",
    "overall_score",
]


def _to_int(value: Any, default: int = 50) -> int:
    """Coerce a value to int, returning default on failure.

    Handles: int, float, str("85"), str("85.5"), None.

    Args:
        value: The raw value to convert.
        default: Default if conversion fails.

    Returns:
        Integer value.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default
    return default


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    """Clamp an integer to [low, high].

    Args:
        value: The value to clamp.
        low: Minimum allowed value.
        high: Maximum allowed value.

    Returns:
        Clamped value.
    """
    return max(low, min(high, value))


def _to_list(value: Any) -> list[str]:
    """Coerce a value to a list of strings.

    Handles: list, str (wraps in list), None (empty list).

    Args:
        value: The raw value to convert.

    Returns:
        List of strings.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


class ResponseParser:
    """Validates and normalizes AI responses into AnalysisResult objects.

    All parsing is defensive — missing fields get defaults, wrong types
    are coerced, and scores are clamped to 0-100.
    """

    @staticmethod
    def parse_analysis(
        raw: dict[str, Any], mostaql_id: str
    ) -> Optional[AnalysisResult]:
        """Convert a raw AI response dict into an AnalysisResult dataclass.

        Handles missing fields with sensible defaults, coerces types,
        clamps scores to 0-100, and wraps string values in lists where
        list fields are expected.

        Args:
            raw: Raw dict from the AI client (with _provider etc. metadata).
            mostaql_id: The job's Mostaql ID for linking.

        Returns:
            An AnalysisResult instance, or None if the input is not a dict.
        """
        if not isinstance(raw, dict):
            logger.error("Response is not a dict: %s", type(raw))
            return None

        # Extract metadata (injected by AI client)
        provider = raw.get("_provider", "")
        model = raw.get("_model", "")
        tokens = _to_int(raw.get("_tokens_used", 0), default=0)

        # Parse scores with clamping
        hiring_probability = _clamp(_to_int(raw.get("hiring_probability"), 50))
        fit_score = _clamp(_to_int(raw.get("fit_score"), 50))
        budget_fairness = _clamp(_to_int(raw.get("budget_fairness"), 50))
        job_clarity = _clamp(_to_int(raw.get("job_clarity"), 50))
        competition_level = _clamp(_to_int(raw.get("competition_level"), 50))
        urgency_score = _clamp(_to_int(raw.get("urgency_score"), 50))
        overall_score = _clamp(_to_int(raw.get("overall_score"), 50))

        # Parse text fields
        job_summary = str(raw.get("job_summary", ""))
        required_skills_analysis = str(raw.get("required_skills_analysis", ""))
        recommended_proposal_angle = str(raw.get("recommended_proposal_angle", ""))
        estimated_real_budget = str(raw.get("estimated_real_budget", ""))
        recommendation = str(raw.get("recommendation", "skip"))
        recommendation_reason = str(raw.get("recommendation_reason", ""))

        # Validate recommendation value
        valid_recommendations = ("instant_alert", "digest", "skip")
        if recommendation not in valid_recommendations:
            logger.warning(
                "Invalid recommendation '%s', defaulting to 'skip'",
                recommendation,
            )
            recommendation = "skip"

        # Parse list fields (may come as string)
        red_flags = _to_list(raw.get("red_flags"))
        green_flags = _to_list(raw.get("green_flags"))

        result = AnalysisResult(
            mostaql_id=mostaql_id,
            hiring_probability=hiring_probability,
            fit_score=fit_score,
            budget_fairness=budget_fairness,
            job_clarity=job_clarity,
            competition_level=competition_level,
            urgency_score=urgency_score,
            overall_score=overall_score,
            job_summary=job_summary,
            required_skills_analysis=required_skills_analysis,
            red_flags=red_flags,
            green_flags=green_flags,
            recommended_proposal_angle=recommended_proposal_angle,
            estimated_real_budget=estimated_real_budget,
            recommendation=recommendation,
            recommendation_reason=recommendation_reason,
            ai_provider=provider,
            ai_model=model,
            tokens_used=tokens,
        )

        logger.debug(
            "Parsed analysis for %s: overall=%d, rec=%s",
            mostaql_id, overall_score, recommendation,
        )

        return result

    @staticmethod
    def validate_scores(result: AnalysisResult) -> list[str]:
        """Validate an AnalysisResult and return a list of warnings.

        Checks for suspicious score patterns and missing content.

        Args:
            result: A parsed AnalysisResult instance.

        Returns:
            List of warning strings (empty if all looks good).
        """
        warnings: list[str] = []

        # Check score ranges
        score_fields = {
            "hiring_probability": result.hiring_probability,
            "fit_score": result.fit_score,
            "budget_fairness": result.budget_fairness,
            "job_clarity": result.job_clarity,
            "competition_level": result.competition_level,
            "urgency_score": result.urgency_score,
            "overall_score": result.overall_score,
        }

        for name, score in score_fields.items():
            if score < 0 or score > 100:
                warnings.append(f"{name} out of range: {score}")
            if score == 0:
                warnings.append(f"{name} is exactly 0 (suspiciously low)")
            if score == 100:
                warnings.append(f"{name} is exactly 100 (suspiciously perfect)")

        # Check for text content
        if not result.job_summary:
            warnings.append("job_summary is empty")

        # Check flags
        if not result.red_flags and not result.green_flags:
            warnings.append("Both red_flags and green_flags are empty")

        return warnings
