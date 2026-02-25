"""Mostaql Notifier — Foundation Test Script.

Verifies the complete project foundation:
  1. Configuration loading and validation
  2. Database initialization and schema creation
  3. Full CRUD: jobs, details, publishers, proposals, analyses
  4. Pipeline queries: needing_details, needing_analysis, unsent alerts
  5. Stats and top-jobs queries
  6. Rate limiter functionality

Run: python scripts/test_foundation.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Test counters ─────────────────────────────────────────
_passed = 0
_failed = 0


def check(label: str, condition: bool) -> None:
    """Assert a test condition and track pass/fail counts.

    Args:
        label: Human-readable description of the test.
        condition: Whether the test passed.
    """
    global _passed, _failed
    if condition:
        _passed += 1
        logger.info("  ✅ %s", label)
    else:
        _failed += 1
        logger.error("  ❌ FAILED: %s", label)


async def test_config() -> None:
    """Test configuration loading and validation."""
    logger.info("═══ Test 1: Configuration System ═══")

    # Set dummy env vars so config validation doesn't fail
    os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
    os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "123456789")

    from src.config import load_config

    config = load_config()

    check("AppConfig loaded", config is not None)
    check("Scraper base_url", config.scraper.base_url == "https://mostaql.com")
    check("3 user agents", len(config.scraper.user_agents) == 3)
    check("AI primary=gemini", config.ai.primary_provider == "gemini")
    check("AI fallback=groq", config.ai.fallback_provider == "groq")
    check("Gemini model", config.ai.gemini.model == "gemini-1.5-flash")
    check("Groq model", config.ai.groq.model == "llama-3.1-8b-instant")
    check("Telegram threshold=80", config.telegram.instant_alert_threshold == 80)
    check("Digest threshold=55", config.telegram.digest_threshold == 55)

    weights_sum = sum(config.scoring.weights.values())
    check(f"Weights sum=1.0 (got {weights_sum:.2f})", 0.99 <= weights_sum <= 1.01)

    check("Profile name loaded", config.profile.name != "")
    check("Profile has expert skills", "expert" in config.profile.skills)
    check("Database path set", config.database_path != "")
    check("Log level valid", config.log_level in ("DEBUG", "INFO", "WARNING", "ERROR"))


async def test_database() -> None:
    """Test database schema, CRUD, pipeline queries, and stats."""
    logger.info("═══ Test 2: Database Operations ═══")

    from src.database.db import Database
    from src.database.models import (
        AnalysisResult,
        JobDetail,
        JobListing,
        ProposalInfo,
        PublisherInfo,
    )
    from src.database import queries

    test_db_path = str(PROJECT_ROOT / "data" / "test_foundation.db")

    async with Database(test_db_path) as db:
        check("Database connected", db._connection is not None)

        # ── Insert a job from listing ────────────────────
        job = JobListing(
            mostaql_id="proj-10001",
            title="تطوير نظام سكرابنج بايثون",
            url="https://mostaql.com/projects/10001",
            publisher_name="عبدالله م.",
            time_posted="منذ ساعة",
            brief_description="أحتاج مطور بايثون لبناء أداة سكرابنج متقدمة",
            category="programming",
            proposals_count=3,
        )
        await queries.insert_job(db, job)
        check("Job inserted", True)

        # ── Check existence ──────────────────────────────
        exists = await queries.job_exists(db, "proj-10001")
        check("job_exists → True", exists is True)

        not_exists = await queries.job_exists(db, "non-existent")
        check("job_exists(bad) → False", not_exists is False)

        # ── Retrieve job ─────────────────────────────────
        fetched = await queries.get_job(db, "proj-10001")
        check("get_job returns data", fetched is not None)
        check("Title matches (Arabic)", fetched["title"] == "تطوير نظام سكرابنج بايثون")
        check("Category correct", fetched["category"] == "programming")

        # ── Jobs needing details (before detail insert) ──
        needing_details = await queries.get_jobs_needing_details(db)
        check("1 job needs details", len(needing_details) == 1)
        check("Correct job needs details", needing_details[0]["mostaql_id"] == "proj-10001")

        # ── Insert detail with publisher & proposals ─────
        publisher = PublisherInfo(
            publisher_id="abdallah-m",
            display_name="عبدالله م.",
            role="صاحب مشروع",
            profile_url="https://mostaql.com/u/abdallah-m",
            identity_verified=True,
            registration_date="25 فبراير 2026",
            total_projects_posted=12,
            open_projects=2,
            total_hired=8,
            hire_rate_raw="80%",
            hire_rate=80.0,
            avg_rating=4.8,
        )

        proposals = [
            ProposalInfo(
                proposer_name="أحمد خ.",
                proposer_verified=True,
                proposer_rating=4.9,
                proposed_at="منذ 30 دقيقة",
            ),
            ProposalInfo(
                proposer_name="محمد ع.",
                proposer_verified=False,
                proposer_rating=3.5,
                proposed_at="منذ ساعة",
            ),
        ]

        detail = JobDetail(
            mostaql_id="proj-10001",
            full_description="أحتاج مطور بايثون متخصص لبناء أداة سكرابنج متقدمة\n"
                             "تقوم بجمع بيانات من عدة مواقع وتخزينها في قاعدة بيانات.\n"
                             "المطلوب:\n- سكرابنج متعدد الصفحات\n- معالجة البيانات\n- تقارير يومية",
            duration="أسبوع إلى شهر",
            experience_level="متوسط",
            budget_min=100.0,
            budget_max=300.0,
            budget_raw="$100.00 - $300.00",
            skills=["Python", "Web Scraping", "BeautifulSoup", "SQLite"],
            attachments_count=1,
            publisher=publisher,
            proposals=proposals,
        )
        await queries.insert_job_detail(db, detail)
        check("Detail inserted", True)

        # ── Verify detail stored correctly ───────────────
        has = await queries.has_detail(db, "proj-10001")
        check("has_detail → True", has is True)

        no_detail = await queries.has_detail(db, "non-existent")
        check("has_detail(bad) → False", no_detail is False)

        # ── Verify publisher upserted ────────────────────
        pub = await queries.get_publisher(db, "abdallah-m")
        check("Publisher found", pub is not None)
        check("Publisher name (Arabic)", pub["display_name"] == "عبدالله م.")
        check("Publisher verified", pub["identity_verified"] == 1)
        check("Publisher hire_rate", pub["hire_rate"] == 80.0)

        # ── Verify budget updated on jobs table ──────────
        job_updated = await queries.get_job(db, "proj-10001")
        check("Budget min updated", job_updated["budget_min"] == 100.0)
        check("Budget max updated", job_updated["budget_max"] == 300.0)
        check("Skills stored as JSON", "Python" in json.loads(job_updated["skills"]))

        # ── Jobs needing details (after detail insert) ───
        needing_details_now = await queries.get_jobs_needing_details(db)
        check("0 jobs need details now", len(needing_details_now) == 0)

        # ── Jobs needing analysis (before analysis) ──────
        needing_analysis = await queries.get_jobs_needing_analysis(db)
        check("1 job needs analysis", len(needing_analysis) == 1)
        enriched = needing_analysis[0]
        check("Enriched has full_description", len(enriched["full_description"]) > 0)
        check("Enriched has publisher name", enriched["display_name"] == "عبدالله م.")
        check("Enriched has hire_rate", enriched["hire_rate"] == 80.0)

        # ── Insert analysis ──────────────────────────────
        analysis = AnalysisResult(
            mostaql_id="proj-10001",
            hiring_probability=85,
            fit_score=90,
            budget_fairness=70,
            job_clarity=88,
            competition_level=60,
            urgency_score=45,
            overall_score=82,
            job_summary="مشروع سكرابنج ممتاز يناسب مهاراتك",
            required_skills_analysis="Python و Web Scraping — مهاراتك الأساسية",
            red_flags=["ميزانية متوسطة"],
            green_flags=["صاحب المشروع موثق", "نسبة توظيف عالية 80%"],
            recommended_proposal_angle="ركّز على خبرتك في سكرابنج مواقع مشابهة",
            estimated_real_budget="$150-250",
            recommendation="instant_alert",
            recommendation_reason="تطابق عالي مع مهاراتك ونسبة توظيف ممتازة",
            ai_provider="gemini",
            ai_model="gemini-1.5-flash",
            tokens_used=1250,
        )
        await queries.insert_analysis(db, analysis)
        check("Analysis inserted", True)

        analyzed = await queries.is_analyzed(db, "proj-10001")
        check("is_analyzed → True", analyzed is True)

        not_analyzed = await queries.is_analyzed(db, "non-existent")
        check("is_analyzed(bad) → False", not_analyzed is False)

        # ── Jobs needing analysis (after analysis) ───────
        needing_now = await queries.get_jobs_needing_analysis(db)
        check("0 jobs need analysis now", len(needing_now) == 0)

        # ── Unsent instant alerts ────────────────────────
        alerts = await queries.get_unsent_instant_alerts(db)
        check("1 unsent instant alert", len(alerts) == 1)
        check("Alert score=82", alerts[0]["overall_score"] == 82)
        check("Alert has publisher", alerts[0]["display_name"] == "عبدالله م.")

        # ── Mark as notified ─────────────────────────────
        await queries.mark_notified(db, "proj-10001", "instant", "msg-12345")
        check("Notification recorded", True)

        alerts_after = await queries.get_unsent_instant_alerts(db)
        check("0 unsent alerts after marking", len(alerts_after) == 0)

        # ── Insert a 2nd job for digest testing ──────────
        job2 = JobListing(
            mostaql_id="proj-10002",
            title="بناء بوت تليجرام للإشعارات",
            url="https://mostaql.com/projects/10002",
            publisher_name="سارة ك.",
            time_posted="منذ ساعتين",
            brief_description="أحتاج بوت تليجرام لإرسال إشعارات تلقائية",
            category="programming",
            proposals_count=7,
        )
        await queries.insert_job(db, job2)

        detail2 = JobDetail(
            mostaql_id="proj-10002",
            full_description="بوت تليجرام يرسل إشعارات يومية",
            duration="أقل من أسبوع",
            budget_min=50.0,
            budget_max=100.0,
            budget_raw="$50.00 - $100.00",
            skills=["Python", "Telegram Bot"],
            publisher=PublisherInfo(
                publisher_id="sara-k",
                display_name="سارة ك.",
                role="صاحبة مشروع",
            ),
        )
        await queries.insert_job_detail(db, detail2)

        analysis2 = AnalysisResult(
            mostaql_id="proj-10002",
            overall_score=65,
            recommendation="digest",
            recommendation_reason="مشروع صغير مناسب لكن الميزانية منخفضة",
            job_summary="بوت تليجرام بسيط",
            ai_provider="groq",
            ai_model="llama-3.1-8b-instant",
            tokens_used=800,
        )
        await queries.insert_analysis(db, analysis2)

        digests = await queries.get_unsent_digest_jobs(db)
        check("1 unsent digest job", len(digests) == 1)
        check("Digest job is proj-10002", digests[0]["mostaql_id"] == "proj-10002")

        # ── Status update ────────────────────────────────
        await queries.update_job_status(db, "proj-10001", "closed")
        updated = await queries.get_job(db, "proj-10001")
        check("Status updated to closed", updated["status"] == "closed")

        # ── Today stats ──────────────────────────────────
        stats = await queries.get_today_stats(db)
        check("Stats: 2 jobs discovered", stats["jobs_discovered"] == 2)
        check("Stats: 2 jobs analyzed", stats["jobs_analyzed"] == 2)
        check("Stats: avg score reasonable", 60 <= stats["avg_overall_score"] <= 90)
        check("Stats: top score=82", stats["top_score"] == 82)
        check("Stats: 1 instant sent", stats["instant_alerts_sent"] == 1)

        # ── Top jobs today ───────────────────────────────
        top = await queries.get_top_jobs_today(db, limit=5)
        check("Top jobs returned", len(top) >= 1)
        check("Top job score=82", top[0]["overall_score"] == 82)
        check("Top job title (Arabic)", "سكرابنج" in top[0]["title"])

    # Cleanup test database
    test_db = Path(test_db_path)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(test_db) + suffix)
        if p.exists():
            p.unlink()
    logger.info("  🗑️  Test database cleaned up")


async def test_rate_limiter() -> None:
    """Test the async rate limiter."""
    logger.info("═══ Test 3: Rate Limiter ═══")

    from src.utils.rate_limiter import AsyncRateLimiter

    limiter = AsyncRateLimiter(max_calls=3, period_seconds=1.0)

    check("Limiter repr", "max_calls=3" in repr(limiter))
    check("Initial slots=3", limiter.available_slots == 3)

    await limiter.acquire()
    check("After 1 acquire, slots=2", limiter.available_slots == 2)

    await limiter.acquire()
    check("After 2 acquires, slots=1", limiter.available_slots == 1)

    await limiter.acquire()
    check("After 3 acquires, slots=0", limiter.available_slots == 0)

    # Context manager
    limiter2 = AsyncRateLimiter(max_calls=5, period_seconds=10.0)
    async with limiter2:
        check("Context manager works", limiter2.available_slots == 4)


async def test_dataclass_conversions() -> None:
    """Test to_db_dict and from_db_row round-trips."""
    logger.info("═══ Test 4: Dataclass Conversions ═══")

    from src.database.models import (
        AnalysisResult,
        JobDetail,
        JobListing,
        ProposalInfo,
        PublisherInfo,
        ScoredJob,
    )

    # JobListing round-trip
    job = JobListing(mostaql_id="rt-1", title="عنوان", url="https://example.com")
    d = job.to_db_dict()
    restored = JobListing.from_db_row(d)
    check("JobListing round-trip", restored.mostaql_id == "rt-1" and restored.title == "عنوان")

    # PublisherInfo round-trip
    pub = PublisherInfo(publisher_id="pub-1", identity_verified=True, hire_rate=75.5)
    d = pub.to_db_dict()
    check("PublisherInfo bool→int", d["identity_verified"] == 1)
    restored_pub = PublisherInfo.from_db_row(d)
    check("PublisherInfo round-trip", restored_pub.identity_verified is True)
    check("PublisherInfo hire_rate preserved", restored_pub.hire_rate == 75.5)

    # AnalysisResult round-trip (lists → JSON)
    analysis = AnalysisResult(
        mostaql_id="rt-2",
        red_flags=["علم أحمر", "تحذير"],
        green_flags=["ممتاز"],
        overall_score=77,
    )
    d = analysis.to_db_dict()
    check("Flags serialized to JSON", isinstance(d["red_flags"], str))
    restored_a = AnalysisResult.from_db_row(d)
    check("AnalysisResult flags round-trip", len(restored_a.red_flags) == 2)
    check("AnalysisResult score preserved", restored_a.overall_score == 77)

    # JobDetail budget dict
    detail = JobDetail(
        mostaql_id="rt-3",
        budget_min=50.0,
        budget_max=200.0,
        budget_raw="$50 - $200",
        skills=["Python", "سكرابنج"],
    )
    bd = detail.get_budget_dict()
    check("Budget dict has skills as JSON", "Python" in bd["skills"])
    check("Budget min preserved", bd["budget_min"] == 50.0)


async def run_all_tests() -> None:
    """Run all foundation tests."""
    logger.info("╔══════════════════════════════════════════╗")
    logger.info("║  Mostaql Notifier — Foundation Tests     ║")
    logger.info("╚══════════════════════════════════════════╝")

    await test_config()
    await test_database()
    await test_rate_limiter()
    await test_dataclass_conversions()

    logger.info("═══════════════════════════════════════════")
    logger.info("  Results: %d passed, %d failed", _passed, _failed)
    logger.info("═══════════════════════════════════════════")

    if _failed > 0:
        logger.error("Some tests failed!")
        sys.exit(1)
    else:
        logger.info("🎉 All foundation tests passed!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
