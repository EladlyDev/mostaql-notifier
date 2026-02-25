"""Mostaql Notifier — Analyzer End-to-End Test.

Tests the full analysis pipeline: prompt → AI → parse → AnalysisResult.
Uses two fake jobs to verify consistency and score variation.

Requires real API keys in .env.

Run: python scripts/test_analyzer.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")

from src.utils.logger import get_logger
from src.config import load_config
from src.analyzer.analyzer import JobAnalyzer
from src.analyzer.prompts import build_analysis_prompt

logger = get_logger(__name__)

# ── Fake job data for testing ─────────────────────────────
FAKE_JOB_GOOD = {
    "mostaql_id": "9999001",
    "title": "تطوير API بايثون لمتجر إلكتروني",
    "url": "https://mostaql.com/projects/9999001-api-python",
    "brief_description": "مطلوب مطور بايثون لبناء REST API لمتجر إلكتروني",
    "full_description": (
        "نبحث عن مطور بايثون محترف لبناء REST API لمتجر إلكتروني. "
        "المطلوب: بناء API للمنتجات والطلبات والمستخدمين باستخدام FastAPI أو Django REST. "
        "ربط النظام ببوابة دفع. توثيق API كامل. "
        "المشروع يحتاج خبرة في Python, PostgreSQL, Docker."
    ),
    "category": "برمجة، تطوير المواقع والتطبيقات",
    "budget_min": 200.0,
    "budget_max": 500.0,
    "budget_raw": "$200.00 - $500.00",
    "duration": "أسبوع إلى شهر",
    "skills": ["Python", "Django", "REST API", "PostgreSQL", "Docker"],
    "proposals_count": 3,
    "time_posted": "منذ ساعة",
    "status": "مفتوح",
    "publisher_name": "Ahmed S.",
    "publisher_role": "صاحب مشروع",
    "registration_date": "15 يناير 2024",
    "hire_rate_raw": "80%",
    "hire_rate": 80.0,
    "open_projects": 1,
    "identity_verified": True,
}

FAKE_JOB_BAD = {
    "mostaql_id": "9999002",
    "title": "ترجمة مقالات من الإنجليزية للعربية",
    "url": "https://mostaql.com/projects/9999002-translate",
    "brief_description": "مطلوب مترجم لترجمة 50 مقال",
    "full_description": "مطلوب مترجم لترجمة 50 مقال من الإنجليزية للعربية في مجال التقنية.",
    "category": "ترجمة ولغات",
    "budget_min": 10.0,
    "budget_max": 25.0,
    "budget_raw": "$10.00 - $25.00",
    "duration": "أقل من أسبوع",
    "skills": ["ترجمة", "كتابة المحتوى"],
    "proposals_count": 15,
    "time_posted": "منذ 3 أيام",
    "status": "مفتوح",
    "publisher_name": "User123",
    "publisher_role": "صاحب مشروع",
    "registration_date": "20 فبراير 2026",
    "hire_rate_raw": "0%",
    "hire_rate": 0.0,
    "open_projects": 3,
    "identity_verified": False,
}

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
        logger.info("  ✅ %s", label)
    else:
        _failed += 1
        logger.error("  ❌ FAILED: %s", label)


def print_result(result: object, label: str) -> None:
    """Pretty-print an AnalysisResult.

    Args:
        result: AnalysisResult instance.
        label: Display label.
    """
    logger.info("")
    logger.info("  ╔═══ %s ═══╗", label)

    score_fields = [
        ("Hiring Probability", "hiring_probability"),
        ("Fit Score", "fit_score"),
        ("Budget Fairness", "budget_fairness"),
        ("Job Clarity", "job_clarity"),
        ("Competition Level", "competition_level"),
        ("Urgency Score", "urgency_score"),
        ("Overall Score", "overall_score"),
    ]

    for display_name, attr in score_fields:
        val = getattr(result, attr, 0)
        bar = "█" * (val // 5) + "░" * (20 - val // 5)
        logger.info("  %s %s %d", f"{display_name + ':':<22s}", bar, val)

    logger.info("")
    logger.info("  Recommendation:  %s", result.recommendation)
    logger.info("  Reason:          %s", result.recommendation_reason)
    logger.info("  Est. Budget:     %s", result.estimated_real_budget)
    logger.info("  Provider:        %s (%s)", result.ai_provider, result.ai_model)
    logger.info("  Tokens:          %d", result.tokens_used)

    logger.info("")
    logger.info("  Summary: %s", result.job_summary)
    logger.info("  Skills:  %s", result.required_skills_analysis)

    if result.green_flags:
        logger.info("  🟢 Green flags:")
        for f in result.green_flags:
            logger.info("     + %s", f)

    if result.red_flags:
        logger.info("  🔴 Red flags:")
        for f in result.red_flags:
            logger.info("     - %s", f)

    if result.recommended_proposal_angle:
        logger.info("  📝 Proposal angle: %s", result.recommended_proposal_angle)


async def run_test() -> None:
    """Run the full analyzer test."""
    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║  Mostaql Notifier — Analyzer End-to-End Test        ║")
    logger.info("╚══════════════════════════════════════════════════════╝")

    config = load_config()

    # ── Save generated prompt to file ────────────────────
    logger.info("═══ Step 1: Prompt Generation ═══")

    profile_dict = {
        "expert_skills": config.profile.skills.get("expert", []),
        "intermediate_skills": config.profile.skills.get("intermediate", []),
        "experience_years": config.profile.experience_years,
        "preferred_budget_range": (
            f"${config.profile.preferences.get('min_budget_usd', 0)}"
            f"-${config.profile.preferences.get('max_budget_usd', 5000)}"
        ),
    }

    prompt = build_analysis_prompt(FAKE_JOB_GOOD, profile_dict)
    prompt_path = PROJECT_ROOT / "logs" / "test_prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    logger.info("  Prompt saved to %s (%d chars)", prompt_path, len(prompt))
    check("Prompt generated", len(prompt) > 200)

    # ── Analyze both jobs ────────────────────────────────
    logger.info("")
    logger.info("═══ Step 2: Analyzing Jobs ═══")

    async with JobAnalyzer(config) as analyzer:

        # Good job
        logger.info("  Analyzing Job 1 (good fit — Python API)...")
        t1 = time.monotonic()
        result_good = await analyzer.analyze_job(FAKE_JOB_GOOD)
        t1_elapsed = time.monotonic() - t1

        if result_good:
            print_result(result_good, "Job 1: Python API (Should Score HIGH)")
            check("Job 1 returned result", True)
            check("Job 1 overall > 50", result_good.overall_score > 50)
            check("Job 1 fit_score > 50", result_good.fit_score > 50)
            check("Job 1 has summary", bool(result_good.job_summary))
            check("Job 1 has recommendation", result_good.recommendation in ("instant_alert", "digest", "skip"))
            check(f"Job 1 time: {t1_elapsed:.1f}s", t1_elapsed < 30)
        else:
            check("Job 1 returned result", False)

        # Bad job
        logger.info("")
        logger.info("  Analyzing Job 2 (bad fit — translation)...")
        t2 = time.monotonic()
        result_bad = await analyzer.analyze_job(FAKE_JOB_BAD)
        t2_elapsed = time.monotonic() - t2

        if result_bad:
            print_result(result_bad, "Job 2: Translation (Should Score LOW)")
            check("Job 2 returned result", True)
            check("Job 2 overall < 50", result_bad.overall_score < 50)
            check("Job 2 fit_score <= 50", result_bad.fit_score <= 50)
            check("Job 2 has red flags", len(result_bad.red_flags) > 0)
            check(f"Job 2 time: {t2_elapsed:.1f}s", t2_elapsed < 30)
        else:
            check("Job 2 returned result", False)

        # Compare scores
        if result_good and result_bad:
            logger.info("")
            logger.info("═══ Step 3: Score Comparison ═══")
            check(
                "Good job scored higher than bad job",
                result_good.overall_score > result_bad.overall_score,
            )
            check(
                "Score difference > 15 points",
                (result_good.overall_score - result_bad.overall_score) > 15,
            )
            logger.info(
                "  Delta: %d points (%d vs %d)",
                result_good.overall_score - result_bad.overall_score,
                result_good.overall_score,
                result_bad.overall_score,
            )

            total_tokens = (result_good.tokens_used or 0) + (result_bad.tokens_used or 0)
            logger.info("  Total tokens: %d (for 2 analyses)", total_tokens)
            check("Tokens per analysis < 2000", total_tokens / 2 < 2000)

    # ── Summary ──────────────────────────────────────────
    logger.info("")
    logger.info("═══════════════════════════════════════════")
    logger.info("  Results: %d passed, %d failed", _passed, _failed)
    logger.info("═══════════════════════════════════════════")

    if _failed > 0:
        logger.error("Some tests failed!")
        sys.exit(1)
    else:
        logger.info("🎉 All analyzer tests passed!")


if __name__ == "__main__":
    asyncio.run(run_test())
