"""Mostaql Notifier — Scoring Engine Test.

Tests the ScoringEngine with 5 scenarios covering perfect jobs,
decent jobs, bad jobs, and edge cases (fit override, budget block).

Run: python scripts/test_scorer.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123")

from src.config import load_config
from src.database.models import AnalysisResult
from src.scorer.scoring import ScoringEngine, ScoredJob
from src.utils.logger import get_logger

logger = get_logger(__name__)

_passed = 0
_failed = 0


def check(label: str, condition: bool) -> None:
    """Track test pass/fail.

    Args:
        label: Test description.
        condition: Whether the test passed.
    """
    global _passed, _failed
    if condition:
        _passed += 1
        logger.info("    ✅ %s", label)
    else:
        _failed += 1
        logger.error("    ❌ FAILED: %s", label)


def print_scored(scored: ScoredJob, label: str) -> None:
    """Pretty-print a scored job.

    Args:
        scored: ScoredJob instance.
        label: Display label.
    """
    logger.info("")
    logger.info("  ╔═══ %s ═══╗", label)
    logger.info("  Base Score:    %.1f", scored.base_score)

    if scored.bonuses_applied:
        for name, val, expl in scored.bonuses_applied:
            logger.info("  + Bonus:       %s (+%d)", name, val)

    if scored.penalties_applied:
        for name, val, expl in scored.penalties_applied:
            logger.info("  - Penalty:     %s (-%d)", name, val)

    bar = "█" * (scored.overall_score // 5) + "░" * (20 - scored.overall_score // 5)
    logger.info("  Final Score:   %s %d/100", bar, scored.overall_score)
    logger.info("  Recommendation: %s", scored.recommendation)
    logger.info("")
    logger.info("  Reasoning:")
    for line in scored.recommendation_reason.split("\n"):
        logger.info("    %s", line)


def make_analysis(**kwargs: object) -> AnalysisResult:
    """Build an AnalysisResult with defaults.

    Args:
        **kwargs: Override fields.

    Returns:
        AnalysisResult with provided overrides.
    """
    defaults = {
        "mostaql_id": "test",
        "hiring_probability": 50,
        "fit_score": 50,
        "budget_fairness": 50,
        "job_clarity": 50,
        "competition_level": 50,
        "urgency_score": 50,
        "overall_score": 50,
        "job_summary": "ملخص اختباري",
        "red_flags": [],
        "green_flags": [],
        "recommendation": "digest",
        "ai_provider": "test",
    }
    defaults.update(kwargs)
    return AnalysisResult(**defaults)


def main() -> None:
    """Run all scoring test scenarios."""
    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║  Mostaql Notifier — Scoring Engine Tests            ║")
    logger.info("╚══════════════════════════════════════════════════════╝")

    config = load_config()
    engine = ScoringEngine(
        config.scoring,
        instant_threshold=config.telegram.instant_alert_threshold,
        digest_threshold=config.telegram.digest_threshold,
    )

    # ═══ Scenario 1: PERFECT JOB ═══
    logger.info("═══ Scenario 1: PERFECT JOB ═══")
    analysis1 = make_analysis(
        mostaql_id="S1",
        hiring_probability=90,
        fit_score=92,
        budget_fairness=88,
        job_clarity=85,
        competition_level=95,
        urgency_score=80,
    )
    job1 = {
        "identity_verified": True,
        "hire_rate": 85.0,
        "proposals_count": 3,
        "budget_max": 500.0,
        "budget_min": 200.0,
        "full_description": "وصف تفصيلي كامل للمشروع مع كل المتطلبات",
        "total_projects": 10,
    }
    scored1 = engine.score(analysis1, job1)
    print_scored(scored1, "Perfect Job")
    check("Score 85-100", 85 <= scored1.overall_score <= 100)
    check("Recommendation = instant_alert", scored1.recommendation == "instant_alert")
    check("Has bonuses", len(scored1.bonuses_applied) >= 3)

    # ═══ Scenario 2: DECENT JOB ═══
    logger.info("═══ Scenario 2: DECENT JOB ═══")
    analysis2 = make_analysis(
        mostaql_id="S2",
        hiring_probability=65,
        fit_score=60,
        budget_fairness=70,
        job_clarity=60,
        competition_level=55,
        urgency_score=50,
    )
    job2 = {
        "identity_verified": False,
        "hire_rate": 50.0,
        "proposals_count": 10,
        "budget_max": 100.0,
        "budget_min": 50.0,
        "full_description": "أحتاج مطور لبناء موقع متوسط الحجم مع لوحة تحكم وعدة صفحات",
        "total_projects": 5,
    }
    scored2 = engine.score(analysis2, job2)
    print_scored(scored2, "Decent Job")
    check("Score 55-75", 55 <= scored2.overall_score <= 75)
    check("Recommendation = digest", scored2.recommendation == "digest")

    # ═══ Scenario 3: BAD JOB ═══
    logger.info("═══ Scenario 3: BAD JOB ═══")
    analysis3 = make_analysis(
        mostaql_id="S3",
        hiring_probability=30,
        fit_score=35,
        budget_fairness=20,
        job_clarity=25,
        competition_level=15,
        urgency_score=20,
    )
    job3 = {
        "identity_verified": False,
        "hire_rate": 0.0,
        "proposals_count": 25,
        "budget_max": 15.0,
        "budget_min": 10.0,
        "full_description": "",  # empty = triggers no_description penalty
        "total_projects": 5,
    }
    scored3 = engine.score(analysis3, job3)
    print_scored(scored3, "Bad Job")
    check("Score 0-40", 0 <= scored3.overall_score <= 40)
    check("Recommendation = skip", scored3.recommendation == "skip")
    check("Has penalties", len(scored3.penalties_applied) >= 2)

    # ═══ Scenario 4: EDGE CASE — Fit override ═══
    logger.info("═══ Scenario 4: EDGE CASE — High Fit Override ═══")
    analysis4 = make_analysis(
        mostaql_id="S4",
        hiring_probability=65,
        fit_score=90,
        budget_fairness=70,
        job_clarity=60,
        competition_level=70,
        urgency_score=50,
    )
    job4 = {
        "identity_verified": True,
        "hire_rate": 60.0,
        "proposals_count": 8,
        "budget_max": 300.0,
        "budget_min": 100.0,
        "full_description": "مشروع يتطلب مهارات بايثون متقدمة",
        "total_projects": 8,
    }
    scored4 = engine.score(analysis4, job4)
    print_scored(scored4, "Fit Override (fit=90, hiring=65)")
    # Should be instant_alert even if overall < 80 due to fit_score >= 85 AND hiring >= 60
    check("Recommendation = instant_alert", scored4.recommendation == "instant_alert")
    check("Overall may be < 80", True)  # just documenting

    # ═══ Scenario 5: EDGE CASE — Budget override ═══
    logger.info("═══ Scenario 5: EDGE CASE — Budget Override ═══")
    analysis5 = make_analysis(
        mostaql_id="S5",
        hiring_probability=85,
        fit_score=88,
        budget_fairness=80,
        job_clarity=82,
        competition_level=90,
        urgency_score=75,
    )
    job5 = {
        "identity_verified": True,
        "hire_rate": 80.0,
        "proposals_count": 2,
        "budget_max": 10.0,
        "budget_min": 5.0,
        "full_description": "مشروع ذو ميزانية منخفضة جداً",
        "total_projects": 3,
    }
    scored5 = engine.score(analysis5, job5)
    print_scored(scored5, "Budget Override (overall high but budget=$10)")
    # Should be digest NOT instant — blocked by budget < $15 override
    check("Recommendation = digest (not instant)", scored5.recommendation == "digest")
    check("Overall still high (70+)", scored5.overall_score >= 70)

    # ═══ Summary ═══
    logger.info("")
    logger.info("═══════════════════════════════════════════")
    logger.info("  Results: %d passed, %d failed", _passed, _failed)
    logger.info("═══════════════════════════════════════════")

    if _failed > 0:
        logger.error("Some tests failed!")
        sys.exit(1)
    else:
        logger.info("🎉 All scoring tests passed!")


if __name__ == "__main__":
    main()
