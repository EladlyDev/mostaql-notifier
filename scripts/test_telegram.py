"""Mostaql Notifier — Telegram Integration Test.

Sends real test messages to Telegram to verify formatting,
escaping, splitting, and delivery.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.

Run: python scripts/test_telegram.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

from src.config import load_config
from src.notifier.telegram_bot import TelegramNotifier
from src.notifier.formatters import (
    format_instant_alert,
    format_digest,
    format_daily_report,
    format_system_status,
    _e,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_passed = 0
_failed = 0


def check(label: str, condition: bool) -> None:
    """Track test pass/fail."""
    global _passed, _failed
    if condition:
        _passed += 1
        logger.info("  ✅ %s", label)
    else:
        _failed += 1
        logger.error("  ❌ FAILED: %s", label)


async def run_test() -> None:
    """Run all Telegram integration tests."""
    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║  Mostaql Notifier — Telegram Integration Test       ║")
    logger.info("╚══════════════════════════════════════════════════════╝")

    config = load_config()
    bot = TelegramNotifier(config.telegram)

    # ═══ Test 1: Bot Connection ═══
    logger.info("═══ Test 1: Bot Connection ═══")
    connected = await bot.initialize()
    check("Bot connected", connected)
    if not connected:
        logger.error("Cannot proceed without bot connection.")
        sys.exit(1)

    # ═══ Test 2: Simple Message ═══
    logger.info("═══ Test 2: Simple Message ═══")
    msg_id = await bot.send_message(
        "🤖 <b>اختبار النظام</b>\n\nهذه رسالة اختبارية من Mostaql Notifier.",
        disable_preview=True,
    )
    check("Simple message sent", msg_id is not None)
    await asyncio.sleep(1)

    # ═══ Test 3: Instant Alert ═══
    logger.info("═══ Test 3: Instant Alert ═══")
    alert_text = format_instant_alert(
        job={
            "title": "تطوير REST API لمتجر إلكتروني باستخدام FastAPI",
            "url": "https://mostaql.com/projects/1234567",
            "budget_min": 200.0,
            "budget_max": 500.0,
            "proposals_count": 3,
            "duration": "أسبوع إلى شهر",
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "REST API"],
            "category": "برمجة، تطوير المواقع والتطبيقات",
        },
        analysis={
            "fit_score": 88,
            "hiring_probability": 85,
            "budget_fairness": 72,
            "job_clarity": 80,
            "competition_level": 90,
            "job_summary": (
                "العميل يبحث عن مطور بايثون محترف لبناء REST API لمتجر إلكتروني "
                "باستخدام FastAPI مع قاعدة بيانات PostgreSQL. المشروع يتضمن "
                "بوابات دفع وتوثيق API كامل."
            ),
            "required_skills_analysis": (
                "مهاراتك في Python و FastAPI و PostgreSQL تتوافق بشكل ممتاز "
                "مع متطلبات المشروع. خبرتك في Docker ستكون إضافة قوية."
            ),
            "recommended_proposal_angle": (
                "ابدأ بذكر خبرتك المحددة في FastAPI وبناء REST APIs. "
                "أرفق رابط لمشروع سابق مشابه. اذكر معرفتك ببوابات الدفع."
            ),
            "green_flags": [
                "الناشر موثق ومعدل توظيفه 85%",
                "عدد العروض قليل (3 فقط)",
                "الميزانية مناسبة لحجم العمل",
            ],
            "red_flags": [
                "المدة مفتوحة (أسبوع إلى شهر) — يجب تحديدها في العرض",
            ],
        },
        scoring={
            "overall_score": 87,
            "base_score": 82,
            "bonuses_applied": [
                ("publisher_verified", 5, "الناشر موثق"),
                ("hire_rate_above_70", 10, "معدل توظيف عالي"),
                ("less_than_5_proposals", 8, "منافسة منخفضة"),
            ],
            "penalties_applied": [],
        },
    )
    msg_id = await bot.send_instant_alert(alert_text)
    check("Instant alert sent", msg_id is not None)
    await asyncio.sleep(1)

    # ═══ Test 4: Digest ═══
    logger.info("═══ Test 4: Digest ═══")
    digest_text = format_digest([
        {
            "title": "تطوير تطبيق موبايل للتجارة الإلكترونية",
            "url": "https://mostaql.com/projects/1111111",
            "overall_score": 75,
            "budget_min": 300.0,
            "budget_max": 800.0,
            "proposals_count": 5,
        },
        {
            "title": "بناء لوحة تحكم إدارية بـ React",
            "url": "https://mostaql.com/projects/2222222",
            "overall_score": 68,
            "budget_min": 150.0,
            "budget_max": 300.0,
            "proposals_count": 7,
        },
        {
            "title": "تصميم قاعدة بيانات لنظام إدارة مخزون",
            "url": "https://mostaql.com/projects/3333333",
            "overall_score": 62,
            "budget_min": 100.0,
            "budget_max": 200.0,
            "proposals_count": 12,
        },
    ])
    msg_id = await bot.send_digest(digest_text)
    check("Digest sent", msg_id is not None)
    await asyncio.sleep(1)

    # ═══ Test 5: Daily Report ═══
    logger.info("═══ Test 5: Daily Report ═══")
    report_text = format_daily_report(
        stats={
            "date": "2026-02-25",
            "total_jobs": 45,
            "instant_count": 3,
            "digest_count": 18,
            "skipped_count": 24,
            "avg_fit_score": 52,
            "avg_hiring_probability": 58,
            "requests_made": 120,
            "tokens_used": 8500,
            "errors": 0,
        },
        top_jobs=[
            {"title": "تطوير REST API بايثون", "url": "https://mostaql.com/projects/1", "overall_score": 92},
            {"title": "بناء نظام CRM متكامل", "url": "https://mostaql.com/projects/2", "overall_score": 85},
            {"title": "تطوير بوت تلجرام", "url": "https://mostaql.com/projects/3", "overall_score": 78},
            {"title": "تصميم API لتطبيق جوال", "url": "https://mostaql.com/projects/4", "overall_score": 73},
            {"title": "أتمتة عمليات بايثون", "url": "https://mostaql.com/projects/5", "overall_score": 70},
        ],
        trends={
            "trending_skills": ["Python", "React", "Node.js", "Docker", "PostgreSQL"],
            "market_health": "active",
            "market_observations": [
                "زيادة الطلب على مطوري بايثون هذا الأسبوع",
                "ميزانيات المشاريع التقنية في تحسن",
                "عدد المشاريع المفتوحة أعلى من المعدل",
            ],
        },
    )
    msg_id = await bot.send_daily_report(report_text)
    check("Daily report sent", msg_id is not None)
    await asyncio.sleep(1)

    # ═══ Test 6: Long Message Splitting ═══
    logger.info("═══ Test 6: Long Message Splitting ═══")
    long_lines = []
    for i in range(100):
        long_lines.append(
            f"سطر {i+1}: هذا نص طويل لاختبار تقسيم الرسائل الطويلة في تلجرام"
        )
    long_text = "\n".join(long_lines)
    logger.info("  Long message: %d chars", len(long_text))
    check("Message > 4096 chars", len(long_text) > 4096)

    msg_id = await bot.send_message(long_text, disable_preview=True)
    check("Long message sent (split)", msg_id is not None)
    await asyncio.sleep(1)

    # ═══ Test 7: Tricky Characters ═══
    logger.info("═══ Test 7: Tricky HTML Characters ═══")
    tricky = (
        f"🧪 <b>اختبار الأحرف الخاصة</b>\n\n"
        f"💰 السعر: {_e('$100 - $200')}\n"
        f"📝 الوصف: {_e('تطوير (backend) + التكامل مع API')}\n"
        f"🔗 رابط: {_e('example.com/path?q=1&r=2')}\n"
        f"📊 النسبة: {_e('50% - 80%')}\n"
        f"🏷 المهارات: {_e('C++ · C# · Node.js · React.js')}\n"
    )
    msg_id = await bot.send_message(tricky, disable_preview=True)
    check("Tricky chars message sent", msg_id is not None)

    # ═══ Summary ═══
    logger.info("")
    logger.info("═══════════════════════════════════════════")
    logger.info("  Results: %d passed, %d failed", _passed, _failed)
    logger.info("═══════════════════════════════════════════")

    if _failed > 0:
        logger.error("Some tests failed!")
        sys.exit(1)
    else:
        logger.info("🎉 All Telegram tests passed!")
        logger.info("Check your Telegram chat for the test messages!")


if __name__ == "__main__":
    asyncio.run(run_test())
