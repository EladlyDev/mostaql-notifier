"""Mostaql Notifier — Quick Filter.

Local, zero-API-call relevance filter applied between listing scrape
and detail scrape. Uses keyword/rule matching against the freelancer's
profile to skip obviously irrelevant jobs early.
"""

from __future__ import annotations

import re
from typing import Any

from src.config import FreelancerProfile
from src.database.models import JobListing
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Hardcoded irrelevant signals ─────────────────────────
# (Arabic term, English label, skill_exception — if user has this skill, skip the filter)
_IRRELEVANT_SIGNALS: list[tuple[str, str, str | None]] = [
    ("ترجمة", "translation", None),
    ("كتابة مقالات", "article writing", None),
    ("تفريغ صوتي", "transcription", None),
    ("فويس أوفر", "voice over", None),
    ("voice over", "voice over", None),
    ("تصميم شعار", "logo design", "design"),
    ("تصميم جرافيك", "graphic design", "design"),
    ("إدخال بيانات", "data entry", "data entry"),
    ("تسويق", "marketing", "marketing"),
    ("سيو", "SEO", "seo"),
    ("SEO", "SEO", "seo"),
]

# ── Common English skill aliases ─────────────────────────
_SKILL_ALIASES: dict[str, list[str]] = {
    "javascript": ["javascript", "js", "جافاسكربت", "جافا سكريبت"],
    "typescript": ["typescript", "ts", "تايبسكريبت"],
    "python": ["python", "بايثون", "بيثون"],
    "react": ["react", "reactjs", "react.js", "رياكت"],
    "vue": ["vue", "vuejs", "vue.js", "فيو"],
    "angular": ["angular", "angularjs", "أنجولار"],
    "node": ["node", "nodejs", "node.js", "نود"],
    "docker": ["docker", "دوكر"],
    "postgresql": ["postgresql", "postgres", "بوستجرس"],
    "mysql": ["mysql", "ماي إس كيو إل"],
    "mongodb": ["mongodb", "mongo", "مونجو"],
    "php": ["php", "بي إتش بي"],
    "laravel": ["laravel", "لارافيل"],
    "django": ["django", "جانغو"],
    "flask": ["flask", "فلاسك"],
    "web scraping": ["web scraping", "scraping", "سكرابنج", "سكرابينج", "استخراج بيانات"],
    "rest api": ["rest api", "api", "واجهة برمجية", "واجهات برمجية"],
    "machine learning": ["machine learning", "ml", "تعلم آلي", "تعلم الآلة"],
    "data science": ["data science", "علم البيانات"],
    "wordpress": ["wordpress", "ووردبريس", "وردبريس"],
}


def _normalize(text: str) -> str:
    """Normalize text for matching: lowercase, strip extra whitespace.

    Also strips the Arabic definite article 'ال' prefix from words
    for better matching (e.g., "البرمجة" → "برمجة").

    Args:
        text: Raw text to normalize.

    Returns:
        Lowercase, whitespace-collapsed text.
    """
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _strip_arabic_article(word: str) -> str:
    """Strip the Arabic definite article 'ال' from a word.

    Args:
        word: Arabic word.

    Returns:
        Word without leading 'ال'.
    """
    if word.startswith("ال") and len(word) > 2:
        return word[2:]
    return word


def _expand_skill(skill: str) -> list[str]:
    """Expand a skill name to include all known aliases.

    Args:
        skill: A skill string (e.g., "JavaScript").

    Returns:
        List of normalized aliases including the original.
    """
    key = _normalize(skill)
    if key in _SKILL_ALIASES:
        return _SKILL_ALIASES[key]
    return [key]


def _text_contains(haystack: str, needle: str) -> bool:
    """Check if normalized haystack contains the needle.

    Handles Arabic article stripping by checking both the
    original and article-stripped versions.

    Args:
        haystack: Normalized text to search in.
        needle: Normalized term to search for.

    Returns:
        True if needle is found in haystack.
    """
    if needle in haystack:
        return True
    # Try stripping Arabic article from both sides
    stripped_needle = _strip_arabic_article(needle)
    if stripped_needle != needle and stripped_needle in haystack:
        return True
    # Try matching against article-stripped words in haystack
    for word in haystack.split():
        stripped_word = _strip_arabic_article(word)
        if stripped_word == stripped_needle or stripped_word == needle:
            return True
    return False


class QuickFilter:
    """Local relevance filter using keyword and rule matching.

    Applies a cascade of checks against the freelancer's profile
    to quickly determine if a job is worth scraping in detail.

    Attributes:
        profile: The configured FreelancerProfile.
    """

    def __init__(self, profile: FreelancerProfile) -> None:
        """Initialize the quick filter.

        Pre-computes normalized skill sets and keyword lists for
        efficient matching.

        Args:
            profile: FreelancerProfile from the app config.
        """
        self.profile = profile

        # Pre-compute normalized negative keywords
        self._negative_keywords: list[str] = [
            _normalize(kw)
            for kw in profile.preferences.get("negative_keywords", [])
        ]

        # Pre-compute normalized positive keywords
        self._positive_keywords: list[str] = [
            _normalize(kw)
            for kw in profile.preferences.get("positive_keywords", [])
        ]

        # Pre-compute all user skills (expert + intermediate) with aliases
        all_skills: list[str] = []
        for level in ("expert", "intermediate"):
            raw = profile.skills.get(level, [])
            for skill in raw:
                all_skills.extend(_expand_skill(skill))
        self._all_skills = list(set(all_skills))

        # Pre-compute set of user skills for exception checking
        self._user_skill_set: set[str] = set()
        for level in ("expert", "intermediate", "beginner"):
            for skill in profile.skills.get(level, []):
                self._user_skill_set.add(_normalize(skill))

        logger.debug(
            "QuickFilter initialized: %d neg keywords, %d pos keywords, %d skills",
            len(self._negative_keywords),
            len(self._positive_keywords),
            len(self._all_skills),
        )

    def is_relevant(self, job: JobListing) -> tuple[bool, str]:
        """Quick relevance check for a single job.

        Applies rules in order:
          1. Negative keyword check
          2. Irrelevant category check
          3. Positive skill match
          4. Positive keyword match
          5. Default pass-through

        Args:
            job: A JobListing from the listing scraper.

        Returns:
            Tuple of (is_relevant, reason_string).
        """
        # Combine searchable text
        title_norm = _normalize(job.title)
        desc_norm = _normalize(job.brief_description)
        combined = f"{title_norm} {desc_norm}"

        # ── Rule 1: Negative keyword check ───────────────
        for kw in self._negative_keywords:
            if _text_contains(combined, kw):
                return False, f"Negative keyword: {kw}"

        # ── Rule 2: Irrelevant category check ────────────
        for signal, label, exception_skill in _IRRELEVANT_SIGNALS:
            signal_norm = _normalize(signal)
            if _text_contains(combined, signal_norm):
                # Check if user has the exception skill
                if exception_skill and _normalize(exception_skill) in self._user_skill_set:
                    continue
                return False, f"Irrelevant category: {label}"

        # ── Rule 3: Positive skill match ─────────────────
        for skill in self._all_skills:
            if _text_contains(combined, skill):
                return True, f"Skill match: {skill}"

        # ── Rule 4: Positive keyword match ───────────────
        for kw in self._positive_keywords:
            if _text_contains(combined, kw):
                return True, f"Keyword match: {kw}"

        # ── Rule 5: Default — no strong signal ───────────
        return True, "No negative signals — will analyze"

    def filter_batch(
        self, jobs: list[JobListing]
    ) -> tuple[list[JobListing], list[JobListing]]:
        """Filter a batch of jobs into relevant and filtered-out lists.

        Logs each decision at DEBUG level and a summary at INFO level.

        Args:
            jobs: List of JobListing instances to filter.

        Returns:
            Tuple of (relevant_jobs, filtered_out_jobs).
        """
        relevant: list[JobListing] = []
        filtered_out: list[JobListing] = []

        for job in jobs:
            is_rel, reason = self.is_relevant(job)
            if is_rel:
                relevant.append(job)
                logger.debug(
                    "  ✅ PASS %s — %s — %s",
                    job.mostaql_id, job.title[:40], reason,
                )
            else:
                filtered_out.append(job)
                logger.debug(
                    "  ❌ SKIP %s — %s — %s",
                    job.mostaql_id, job.title[:40], reason,
                )

        logger.info(
            "Quick filter: %d passed, %d filtered out (of %d total)",
            len(relevant), len(filtered_out), len(jobs),
        )

        return relevant, filtered_out
