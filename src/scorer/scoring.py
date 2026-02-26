"""Mostaql Notifier — Scoring Engine.

Combines AI analysis scores with rule-based bonuses and penalties
to produce a final score and recommendation decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import ScoringConfig
from src.database.models import AnalysisResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Default thresholds (overridable) ─────────────────────
_DEFAULT_INSTANT_THRESHOLD = 80
_DEFAULT_DIGEST_THRESHOLD = 55


@dataclass
class ScoredJob:
    """Final scored job with recommendation and reasoning.

    Extends the AnalysisResult with computed bonus/penalty
    breakdown and a final recommendation decision.

    Attributes:
        mostaql_id: Job's Mostaql ID.
        analysis: Original AI AnalysisResult.
        base_score: Weighted average before bonuses/penalties.
        bonuses_applied: List of (rule_name, value, explanation) tuples.
        penalties_applied: List of (rule_name, value, explanation) tuples.
        overall_score: Final clamped score (0-100).
        recommendation: One of 'instant_alert', 'digest', 'skip'.
        recommendation_reason: Arabic explanation string.
    """

    mostaql_id: str
    analysis: AnalysisResult
    base_score: float = 0.0
    bonuses_applied: list[tuple[str, int, str]] = field(default_factory=list)
    penalties_applied: list[tuple[str, int, str]] = field(default_factory=list)
    overall_score: int = 0
    recommendation: str = "skip"
    recommendation_reason: str = ""


class ScoringEngine:
    """Calculates final scores from AI analysis + rule-based adjustments.

    Pipeline: weighted base → bonuses → penalties → clamp → recommend.

    Attributes:
        config: ScoringConfig with weights, bonuses, penalties dicts.
    """

    def __init__(
        self,
        config: ScoringConfig,
        instant_threshold: int = _DEFAULT_INSTANT_THRESHOLD,
        digest_threshold: int = _DEFAULT_DIGEST_THRESHOLD,
    ) -> None:
        """Initialize the scoring engine.

        Args:
            config: ScoringConfig from the app configuration.
            instant_threshold: Minimum score for instant_alert.
            digest_threshold: Minimum score for digest.
        """
        self.config = config
        self.instant_threshold = instant_threshold
        self.digest_threshold = digest_threshold

    def score(
        self, analysis: AnalysisResult, job_data: dict[str, Any]
    ) -> ScoredJob:
        """Calculate overall score and recommendation.

        Pipeline:
          1. Weighted base score from 6 AI dimensions.
          2. Add bonuses for positive signals.
          3. Subtract penalties for red flags.
          4. Clamp to 0-100.
          5. Determine recommendation with override logic.
          6. Build Arabic reasoning string.

        Args:
            analysis: AI AnalysisResult for this job.
            job_data: Dict with raw job data for bonus/penalty checks.

        Returns:
            A ScoredJob with full score breakdown.
        """
        mostaql_id = analysis.mostaql_id

        # ── Step 1: Weighted base score ──────────────────
        weights = self.config.weights
        base = (
            analysis.hiring_probability * weights.get("hiring_probability", 0.3)
            + analysis.fit_score * weights.get("fit_score", 0.3)
            + analysis.budget_fairness * weights.get("budget_fairness", 0.15)
            + analysis.competition_level * weights.get("competition_level", 0.1)
            + analysis.job_clarity * weights.get("job_clarity", 0.1)
            + analysis.urgency_score * weights.get("urgency_score", 0.05)
        )

        # ── Step 2: Bonuses ──────────────────────────────
        bonuses = self._check_bonuses(job_data)
        total_bonus = sum(b[1] for b in bonuses)

        # ── Step 3: Penalties ────────────────────────────
        penalties = self._check_penalties(job_data, analysis)
        total_penalty = sum(p[1] for p in penalties)

        # ── Step 4: Final score ──────────────────────────
        final = base + total_bonus - total_penalty
        final_clamped = max(0, min(100, int(round(final))))

        # ── Step 5: Recommendation ───────────────────────
        recommendation = self._decide_recommendation(
            final_clamped, analysis, job_data,
        )

        # ── Step 6: Build reasoning ──────────────────────
        reasoning = self._build_reasoning(
            final_clamped, base, total_bonus, total_penalty,
            bonuses, penalties, recommendation,
        )

        scored = ScoredJob(
            mostaql_id=mostaql_id,
            analysis=analysis,
            base_score=round(base, 1),
            bonuses_applied=bonuses,
            penalties_applied=penalties,
            overall_score=final_clamped,
            recommendation=recommendation,
            recommendation_reason=reasoning,
        )

        logger.info(
            "Scored %s: base=%.1f + bonus=%d - penalty=%d = %d → %s",
            mostaql_id, base, total_bonus, total_penalty,
            final_clamped, recommendation,
        )

        return scored

    def _check_bonuses(
        self, job_data: dict[str, Any]
    ) -> list[tuple[str, int, str]]:
        """Check each bonus rule against job data.

        Args:
            job_data: Raw job data dict.

        Returns:
            List of (rule_name, bonus_value, arabic_explanation) tuples.
        """
        bonuses: list[tuple[str, int, str]] = []
        cfg = self.config.bonuses

        # Publisher verified
        if job_data.get("identity_verified", False):
            val = cfg.get("publisher_verified", 5)
            bonuses.append(("publisher_verified", val, f"الناشر موثق (+{val})"))

        # High hire rate
        hire_rate = job_data.get("hire_rate", 0)
        if isinstance(hire_rate, (int, float)) and hire_rate > 70:
            val = cfg.get("hire_rate_above_70", 10)
            bonuses.append((
                "hire_rate_above_70", val,
                f"معدل توظيف عالي {hire_rate:.0f}% (+{val})",
            ))

        # Few proposals
        proposals = job_data.get("proposals_count", 0) or 0
        if proposals < 5:
            val = cfg.get("less_than_5_proposals", 8)
            bonuses.append((
                "less_than_5_proposals", val,
                f"منافسة منخفضة — {proposals} عروض فقط (+{val})",
            ))

        # Budget above $200
        budget_max = job_data.get("budget_max", 0) or 0
        budget_min = job_data.get("budget_min", 0) or 0
        budget = budget_max if budget_max else budget_min
        if budget > 200:
            val = cfg.get("budget_above_200", 3)
            bonuses.append((
                "budget_above_200", val,
                f"ميزانية جيدة ${budget:.0f} (+{val})",
            ))

        return bonuses

    def _check_penalties(
        self,
        job_data: dict[str, Any],
        analysis: AnalysisResult,
    ) -> list[tuple[str, int, str]]:
        """Check each penalty rule against job data.

        Args:
            job_data: Raw job data dict.
            analysis: AI analysis result.

        Returns:
            List of (rule_name, penalty_value, arabic_explanation) tuples.
            Penalty values are positive (they will be subtracted).
        """
        penalties: list[tuple[str, int, str]] = []
        cfg = self.config.penalties

        # No description
        desc = job_data.get("full_description", "") or job_data.get("brief_description", "")
        if not desc or len(desc.strip()) < 20:
            val = abs(cfg.get("no_description", -20))
            penalties.append(("no_description", val, f"بدون وصف (-{val})"))

        # Too many proposals (>20)
        proposals = job_data.get("proposals_count", 0) or 0
        if proposals > 20:
            val = abs(cfg.get("too_many_proposals", -10))
            penalties.append((
                "too_many_proposals", val,
                f"منافسة عالية جداً — {proposals} عرض (-{val})",
            ))

        # Publisher never hired
        # hire_rate_raw: "لم يحسب بعد" = new, "0%" = posted but never hired
        hire_rate = job_data.get("hire_rate", 0)
        hire_rate_raw = str(job_data.get("hire_rate_raw", ""))
        never_hired = (
            hire_rate_raw == "لم يحسب بعد"
            or (isinstance(hire_rate, (int, float)) and hire_rate == 0)
        )
        if never_hired:
            val = abs(cfg.get("publisher_never_hired", -15))
            penalties.append((
                "publisher_never_hired", val,
                f"الناشر لم يوظف أحداً بعد (-{val})",
            ))

        # Budget below $100 (user's minimum preference)
        budget_max = job_data.get("budget_max", 0) or 0
        budget_min = job_data.get("budget_min", 0) or 0
        budget = budget_max if budget_max else budget_min
        if 0 < budget < 100:
            val = abs(cfg.get("budget_below_100", -10))
            penalties.append((
                "budget_below_100", val,
                f"ميزانية منخفضة ${budget:.0f} (-{val})",
            ))

        return penalties

    def _should_override_instant(
        self,
        job_data: dict[str, Any],
        analysis: AnalysisResult,
    ) -> bool:
        """Check if instant_alert should be blocked despite high score.

        Blocks instant alert for:
          - Budget < $15 (too cheap)
          - Proposals > 30 (too crowded)
          - Hiring probability < 30 (unlikely to hire)

        Args:
            job_data: Raw job data dict.
            analysis: AI analysis result.

        Returns:
            True if instant_alert should be blocked.
        """
        budget_max = job_data.get("budget_max", 0) or 0
        budget_min = job_data.get("budget_min", 0) or 0
        budget = budget_max if budget_max else budget_min
        if 0 < budget < 15:
            return True

        proposals = job_data.get("proposals_count", 0) or 0
        if proposals > 30:
            return True

        if analysis.hiring_probability < 30:
            return True

        return False

    def _decide_recommendation(
        self,
        final_score: int,
        analysis: AnalysisResult,
        job_data: dict[str, Any],
    ) -> str:
        """Determine the recommendation category.

        Rules (in order):
          a) final >= instant_threshold → instant_alert
          b) fit_score >= 85 AND hiring_prob >= 60 → instant_alert
          c) final >= digest_threshold → digest
          d) else → skip

        Override: if _should_override_instant, downgrade to digest.

        Args:
            final_score: Clamped final score.
            analysis: AI analysis result.
            job_data: Raw job data.

        Returns:
            One of 'instant_alert', 'digest', 'skip'.
        """
        is_instant = False

        # Rule a: High overall score
        if final_score >= self.instant_threshold:
            is_instant = True

        # Rule b: Great fit with decent hiring chance
        if analysis.fit_score >= 85 and analysis.hiring_probability >= 60:
            is_instant = True

        # Override check
        if is_instant and self._should_override_instant(job_data, analysis):
            logger.info(
                "Blocking instant_alert for %s (override triggered)",
                analysis.mostaql_id,
            )
            is_instant = False

        if is_instant:
            return "instant_alert"

        # Rule c: Digest threshold
        if final_score >= self.digest_threshold:
            return "digest"

        # Rule d: Skip
        return "skip"

    def _build_reasoning(
        self,
        final: int,
        base: float,
        total_bonus: int,
        total_penalty: int,
        bonuses: list[tuple[str, int, str]],
        penalties: list[tuple[str, int, str]],
        recommendation: str,
    ) -> str:
        """Build a human-readable Arabic reasoning string.

        Args:
            final: Final clamped score.
            base: Weighted base score.
            total_bonus: Sum of bonuses.
            total_penalty: Sum of penalties.
            bonuses: List of bonus tuples.
            penalties: List of penalty tuples.
            recommendation: The recommendation decision.

        Returns:
            Multi-line Arabic string explaining the score.
        """
        rec_ar = {
            "instant_alert": "⚡ تنبيه فوري",
            "digest": "📋 ملخص",
            "skip": "⏭️ تخطي",
        }.get(recommendation, recommendation)

        header = (
            f"الدرجة الكلية: {final}/100 | "
            f"القاعدة: {base:.0f} + مكافآت: {total_bonus} - خصومات: {total_penalty} | "
            f"القرار: {rec_ar}"
        )

        lines = [header]

        for _, _, explanation in bonuses:
            lines.append(f"✅ {explanation}")

        for _, _, explanation in penalties:
            lines.append(f"⚠️ {explanation}")

        return "\n".join(lines)
