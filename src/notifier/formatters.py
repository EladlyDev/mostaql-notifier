"""Mostaql Notifier — Telegram Message Formatters.

Produces beautiful Arabic Telegram notifications using HTML parse mode.
HTML is far more reliable than MarkdownV2 — only &, <, > need escaping.

Design principles:
  - ONE data point per line (no inline cramming)
  - Section dividers (━━━) between logical groups
  - Vertical-first layout for narrow mobile screens
  - Short lines that never wrap on phone screens
  - Clear visual hierarchy with bold headers
"""

from __future__ import annotations

from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Separator line for between sections ──────────────────
_SEP = "━━━━━━━━━━━━━━━━━━"


def _e(text: str) -> str:
    """Escape HTML special characters.

    Only &, <, > need escaping for Telegram HTML parse mode.
    This is vastly simpler than MarkdownV2 escaping.

    Args:
        text: Raw text to escape.

    Returns:
        HTML-safe text.
    """
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link(text: str, url: str) -> str:
    """Build an HTML link.

    Args:
        text: Display text (will be escaped).
        url: URL (ampersands escaped).

    Returns:
        HTML anchor tag.
    """
    safe_text = _e(text)
    safe_url = url.replace("&", "&amp;")
    return f'<a href="{safe_url}">{safe_text}</a>'


def _bold(text: str) -> str:
    """Wrap text in bold tags with escaping.

    Args:
        text: Text to bold.

    Returns:
        Bold HTML.
    """
    return f"<b>{_e(text)}</b>"


def _progress_bar(value: int, length: int = 10) -> str:
    """Create a text progress bar.

    Args:
        value: Score 0-100.
        length: Number of bar characters.

    Returns:
        String like '▰▰▰▰▰▰▰▰▱▱'.
    """
    value = max(0, min(100, value))
    filled = round(value / 100 * length)
    return "▰" * filled + "▱" * (length - filled)


def _format_budget(
    min_b: Optional[float], max_b: Optional[float]
) -> str:
    """Format a budget range nicely (HTML-escaped).

    Args:
        min_b: Minimum budget in USD.
        max_b: Maximum budget in USD.

    Returns:
        Formatted budget string.
    """
    if min_b is not None and max_b is not None and min_b > 0 and max_b > 0:
        if min_b == max_b:
            return f"${min_b:.0f}"
        return f"${min_b:.0f} - ${max_b:.0f}"
    if max_b is not None and max_b > 0:
        return f"${max_b:.0f}"
    if min_b is not None and min_b > 0:
        return f"${min_b:.0f}+"
    return "غير محدد"


def format_instant_alert(
    job: dict[str, Any],
    analysis: dict[str, Any],
    scoring: dict[str, Any],
) -> str:
    """Format a high-priority instant alert notification.

    Vertical layout: one piece of info per line, section dividers,
    no inline cramming. Optimized for narrow mobile screens.

    Args:
        job: Raw job data dict.
        analysis: AnalysisResult fields as dict.
        scoring: ScoredJob fields as dict.

    Returns:
        HTML formatted message string (max ~4000 chars).
    """
    title = job.get("title", "مشروع بدون عنوان")
    url = job.get("url", "")
    overall = scoring.get("overall_score", 0)

    # ── Header ───────────────────────────────────────────
    if overall >= 90:
        header = "🔥🔥🔥 فرصة استثنائية!"
    elif overall >= 80:
        header = "🔥🔥 فرصة مميزة — تقدم الآن!"
    elif overall >= 70:
        header = "🔥 فرصة جيدة"
    else:
        header = "📋 فرصة جديدة"

    lines = [f"<b>{_e(header)}</b>", ""]

    # ── Title ────────────────────────────────────────────
    if url:
        lines.append(f"📌 {_link(title, url)}")
    else:
        lines.append(f"📌 {_bold(title)}")

    # ── Job details (one per line) ───────────────────────
    budget = _format_budget(job.get("budget_min"), job.get("budget_max"))
    proposals = job.get("proposals_count", 0) or 0
    duration = job.get("duration", "")
    # Clean duration (may have newlines/extra spaces from HTML scraping)
    if duration:
        duration = " ".join(duration.split()).strip()
    skills = job.get("skills", [])
    if isinstance(skills, str):
        import json as _json
        try:
            skills = _json.loads(skills)
        except (ValueError, TypeError):
            skills = [s.strip() for s in skills.split(",") if s.strip()]
    category = job.get("category", "")
    time_posted = job.get("time_posted", "")
    publisher = job.get("publisher_name", "")

    lines.append(f"💰 {_e(budget)}")
    lines.append(f"📊 {_e(str(proposals))} عروض")
    if duration:
        lines.append(f"⏱ المدة: {_e(duration)}")
    if time_posted:
        # Show just the date/time, not the full timestamp
        time_str = str(time_posted)[:16]  # "2026-02-25 21:28"
        lines.append(f"🕐 نُشر: {_e(time_str)}")
    if skills:
        lines.append(f"🏷 {_e(' · '.join(skills[:5]))}")
    if category:
        lines.append(f"📁 {_e(str(category))}")
    if publisher:
        lines.append(f"👤 الناشر: {_e(publisher)}")

    # ── Scores ───────────────────────────────────────────
    lines.append("")
    lines.append(_SEP)
    lines.append("")

    bar = _progress_bar(overall, 15)
    lines.append(f"⚡ الدرجة الكلية: <b>{overall}/100</b>")
    lines.append(bar)
    lines.append("")

    fit = analysis.get("fit_score", 0)
    hiring = analysis.get("hiring_probability", 0)
    budget_fair = analysis.get("budget_fairness", 0)
    clarity = analysis.get("job_clarity", 0)
    competition = analysis.get("competition_level", 0)

    lines.append(f"🎯 التوافق: <b>{fit}%</b>")
    lines.append(f"📈 احتمال التوظيف: <b>{hiring}%</b>")
    lines.append(f"💰 عدالة السعر: <b>{budget_fair}%</b>")
    lines.append(f"📝 وضوح المشروع: <b>{clarity}%</b>")
    lines.append(f"🏆 المنافسة: <b>{competition}%</b>")

    # ── AI Analysis ──────────────────────────────────────
    summary = analysis.get("job_summary", "")
    skills_analysis = analysis.get("required_skills_analysis", "")
    proposal_angle = analysis.get("recommended_proposal_angle", "")
    green_flags = analysis.get("green_flags", [])
    red_flags = analysis.get("red_flags", [])

    if summary or skills_analysis:
        lines.append("")
        lines.append(_SEP)
        lines.append("")

    if summary:
        lines.append(f"📝 <b>الملخص:</b>")
        lines.append(_e(summary))
        lines.append("")

    if skills_analysis:
        lines.append(f"🎯 <b>المهارات:</b>")
        lines.append(_e(skills_analysis))
        lines.append("")

    # ── Flags ────────────────────────────────────────────
    if green_flags or red_flags:
        lines.append(_SEP)
        lines.append("")

    if green_flags:
        lines.append("✅ <b>إيجابيات:</b>")
        for flag in green_flags[:4]:
            lines.append(f"  • {_e(flag)}")
        lines.append("")

    if red_flags:
        lines.append("⚠️ <b>تحذيرات:</b>")
        for flag in red_flags[:4]:
            lines.append(f"  • {_e(flag)}")
        lines.append("")

    # ── Proposal angle ───────────────────────────────────
    if proposal_angle:
        lines.append(_SEP)
        lines.append("")
        lines.append(f"💡 <b>استراتيجية العرض:</b>")
        lines.append(_e(proposal_angle))
        lines.append("")

    # ── Score breakdown ──────────────────────────────────
    base = scoring.get("base_score", 0)
    bonuses = scoring.get("bonuses_applied", [])
    penalties = scoring.get("penalties_applied", [])
    total_bonus = sum(b[1] for b in bonuses) if bonuses else 0
    total_penalty = sum(p[1] for p in penalties) if penalties else 0

    if total_bonus or total_penalty:
        lines.append(
            f"📊 القاعدة: {base:.0f}"
            f" + مكافآت: {total_bonus}"
            f" - خصومات: {total_penalty}"
        )

    msg = "\n".join(lines)

    if len(msg) > 4000:
        msg = msg[:3950] + "\n..."
        logger.warning("Instant alert truncated to fit Telegram limit")

    return msg


def format_digest(jobs: list[dict[str, Any]]) -> str:
    """Format an hourly digest of moderate-interest jobs.

    Each job gets 3 clean lines: title, budget, score.

    Args:
        jobs: List of dicts with title, url, overall_score, budget, proposals.

    Returns:
        HTML formatted digest message.
    """
    if not jobs:
        return "<b>📋 لا توجد فرص جديدة في هذه الفترة</b>"

    sorted_jobs = sorted(
        jobs, key=lambda j: j.get("overall_score", 0), reverse=True,
    )
    sorted_jobs = sorted_jobs[:15]
    total = len(jobs)

    lines = [
        f"<b>📋 ملخص الفرص — {total} مشروع جديد</b>",
        "",
    ]

    for i, job in enumerate(sorted_jobs, 1):
        score = job.get("overall_score", 0)
        title = job.get("title", "بدون عنوان")[:45]
        url = job.get("url", "")
        budget = _format_budget(
            job.get("budget_min"), job.get("budget_max"),
        )
        proposals = job.get("proposals_count", 0) or 0
        indicator = "🟢" if score >= 70 else "🟡"

        if i > 1:
            lines.append("")

        if url:
            lines.append(f"{indicator} {_link(title, url)}")
        else:
            lines.append(f"{indicator} {_e(title)}")
        lines.append(f"   💰 {_e(budget)}  ·  📊 {proposals} عروض")
        lines.append(f"   🎯 الدرجة: <b>{score}%</b>")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3950] + "\n..."
    return msg


def format_daily_report(
    stats: dict[str, Any],
    top_jobs: list[dict[str, Any]],
    trends: Optional[dict[str, Any]] = None,
) -> str:
    """Format an end-of-day summary report.

    Vertical layout with section dividers.

    Args:
        stats: Dict with total, instant_count, digest_count, skipped, etc.
        top_jobs: Top 5 jobs of the day.
        trends: Optional trends dict.

    Returns:
        HTML formatted daily report.
    """
    date_str = stats.get("date", "اليوم")
    total = stats.get("total_jobs", 0)
    instant = stats.get("instant_count", 0)
    digest = stats.get("digest_count", 0)
    skipped = stats.get("skipped_count", 0)
    avg_fit = stats.get("avg_fit_score", 0)
    avg_hiring = stats.get("avg_hiring_probability", 0)

    lines = [
        f"<b>📊 التقرير اليومي — {_e(str(date_str))}</b>",
        "",
        f"📌 المشاريع المكتشفة: <b>{total}</b>",
        f"⚡ تنبيهات فورية: <b>{instant}</b>",
        f"📋 في الملخصات: <b>{digest}</b>",
        f"⏭️ تم تخطيها: <b>{skipped}</b>",
        "",
        _SEP,
        "",
        f"🎯 متوسط التوافق: <b>{avg_fit}%</b>",
        f"📈 متوسط التوظيف: <b>{avg_hiring}%</b>",
    ]

    # Top jobs
    if top_jobs:
        lines.extend(["", _SEP, ""])
        lines.append("<b>🏆 أفضل الفرص:</b>")
        for i, job in enumerate(top_jobs[:5], 1):
            title = job.get("title", "?")[:35]
            url = job.get("url", "")
            score = job.get("overall_score", 0)
            if url:
                lines.append(f"  {i}. {_link(title, url)} — <b>{score}%</b>")
            else:
                lines.append(f"  {i}. {_e(title)} — <b>{score}%</b>")

    # Trends
    if trends:
        trending = trends.get("trending_skills", [])
        health = trends.get("market_health", "")
        observations = trends.get("market_observations", [])

        lines.extend(["", _SEP, ""])

        if trending:
            lines.append(f"<b>📈 المهارات الرائجة:</b>")
            lines.append(_e(" · ".join(trending[:5])))
            lines.append("")

        if health:
            health_map = {
                "active": "🟢 نشط",
                "moderate": "🟡 معتدل",
                "slow": "🔴 بطيء",
            }
            lines.append(
                f"📈 حالة السوق: <b>{_e(health_map.get(health, health))}</b>"
            )
            lines.append("")

        if observations:
            lines.append("<b>📝 ملاحظات:</b>")
            for obs in observations[:3]:
                lines.append(f"  • {_e(obs)}")

    # System health
    errors = stats.get("errors", 0)
    requests_made = stats.get("requests_made", 0)
    tokens = stats.get("tokens_used", 0)

    lines.extend(["", _SEP, ""])
    lines.append("<b>🔧 صحة النظام:</b>")
    lines.append(f"  🔄 طلبات HTTP: {requests_made}")
    lines.append(f"  🤖 رموز AI: {tokens}")
    if errors > 0:
        lines.append(f"  ❌ أخطاء: {errors}")
    else:
        lines.append("  ✅ بدون أخطاء")

    return "\n".join(lines)


def format_system_status(status: dict[str, Any]) -> str:
    """Format a simple system status message for /status command.

    Args:
        status: Dict with uptime, last_scan, jobs_today, errors, etc.

    Returns:
        HTML formatted status message.
    """
    uptime = status.get("uptime", "غير معروف")
    last_scan = status.get("last_scan", "لم يتم بعد")
    jobs_today = status.get("jobs_today", 0)
    alerts_today = status.get("alerts_today", 0)
    errors = status.get("errors", 0)
    db_size = status.get("db_size", "غير معروف")

    lines = [
        "<b>🤖 حالة النظام</b>",
        "",
        f"⏱ وقت التشغيل: {_e(str(uptime))}",
        f"🔍 آخر فحص: {_e(str(last_scan))}",
        f"📌 مشاريع اليوم: <b>{jobs_today}</b>",
        f"⚡ تنبيهات اليوم: <b>{alerts_today}</b>",
        f"💾 قاعدة البيانات: {_e(str(db_size))}",
    ]

    if errors > 0:
        lines.append(f"❌ أخطاء: {errors}")
    else:
        lines.append("✅ لا توجد أخطاء")

    return "\n".join(lines)


# ── Backward compat: keep _escape_md as alias ────────────
_escape_md = _e
