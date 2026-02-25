"""Mostaql Notifier — Detail Page Scraper.

Parses full project detail pages from mostaql.com HTML. Extracts
all available data including description, budget, skills, publisher
info, and visible proposals.

CSS selectors are adapted from the working investigation scraper and
use selectolax (HTMLParser) instead of BeautifulSoup.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from selectolax.parser import HTMLParser, Node

from src.database.models import JobDetail, ProposalInfo, PublisherInfo
from src.scraper.client import MostaqlClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════


def _text(node: Optional[Node]) -> str:
    """Safely extract stripped text from a selectolax node.

    Args:
        node: A selectolax Node, or None.

    Returns:
        Stripped text content, or empty string.
    """
    if node is None:
        return ""
    return node.text(strip=True)


def _attr(node: Optional[Node], name: str) -> str:
    """Safely extract an attribute from a selectolax node.

    Args:
        node: A selectolax Node, or None.
        name: Attribute name.

    Returns:
        Attribute value, or empty string.
    """
    if node is None:
        return ""
    val = node.attributes.get(name)
    return val if val else ""


def _extract_meta_value(sidebar: Node, label: str) -> str:
    """Extract a meta-value from the sidebar by its Arabic label text.

    Searches through .meta-row elements for a matching label.

    Args:
        sidebar: The sidebar HTMLParser node (#project-meta-panel).
        label: Arabic label text to match (e.g., "الميزانية").

    Returns:
        The corresponding value text, or empty string.
    """
    for row in sidebar.css(".meta-row"):
        label_el = row.css_first(".meta-label")
        if label_el and label in _text(label_el):
            value_el = row.css_first(".meta-value")
            if value_el:
                return _text(value_el)
    return ""


def _parse_budget(raw: str) -> tuple[Optional[float], Optional[float], str]:
    """Parse a budget string into min/max floats and the raw string.

    Handles patterns:
      "$25.00 - $50.00"  → (25.0, 50.0)
      "$50.00"           → (50.0, 50.0)
      "50 - 100"         → (50.0, 100.0)
      "قابل للتفاوض"     → (None, None)
      ""                 → (None, None)

    Args:
        raw: Raw budget text from the page.

    Returns:
        Tuple of (budget_min, budget_max, budget_raw).
    """
    if not raw:
        return None, None, raw

    # Extract all numbers (including decimals)
    numbers = re.findall(r"[\d,]+\.?\d*", raw.replace(",", ""))
    floats = []
    for n in numbers:
        try:
            floats.append(float(n))
        except ValueError:
            pass

    if len(floats) >= 2:
        return min(floats), max(floats), raw
    elif len(floats) == 1:
        return floats[0], floats[0], raw
    else:
        return None, None, raw


def _parse_hire_rate(raw: str) -> float:
    """Parse a hire rate string to a float percentage.

    Handles:
      "80%"          → 80.0
      "20.5%"        → 20.5
      "لم يحسب بعد"  → 0.0
      ""             → 0.0

    Args:
        raw: Raw hire rate text.

    Returns:
        Hire rate as a float, or 0.0 if not parseable.
    """
    if not raw:
        return 0.0
    match = re.search(r"([\d.]+)", raw.replace("%", ""))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


# ═══════════════════════════════════════════════════════════
# Publisher Extraction
# ═══════════════════════════════════════════════════════════


def _extract_publisher(widget: Node) -> PublisherInfo:
    """Extract publisher information from the employer_widget.

    Args:
        widget: The employer_widget Node from the detail page sidebar.

    Returns:
        A PublisherInfo dataclass with all available fields.
    """
    # Name
    name_el = (
        widget.css_first(".profile__name bdi")
        or widget.css_first(".profile__name")
    )
    display_name = _text(name_el)

    # Derive a publisher_id from the name or profile link
    profile_link = widget.css_first("a[href*='/u/']")
    profile_url = _attr(profile_link, "href") if profile_link else ""
    if profile_url:
        # Extract username slug from URL
        match = re.search(r"/u/([^/\?]+)", profile_url)
        publisher_id = match.group(1) if match else display_name.lower().replace(" ", "-")
    else:
        publisher_id = re.sub(r"[^\w]", "-", display_name.lower()).strip("-") or "unknown"

    # Role
    role_el = (
        widget.css_first("ul.meta_items li")
        or widget.css_first(".meta_items li")
    )
    role = _text(role_el)

    # Identity verification badge
    badge = widget.css_first(".profile-verification-badge, .verified-badge, .identity-verified")
    identity_verified = badge is not None

    # Table-based stats
    stats: dict[str, str] = {}
    table = widget.css_first("table.table-meta")
    if table:
        stats_map = {
            "تاريخ التسجيل": "registered",
            "معدل التوظيف": "hire_rate",
            "المشاريع المفتوحة": "open_projects",
            "مشاريع قيد التنفيذ": "in_progress",
            "التواصلات الجارية": "communications",
        }
        for row in table.css("tr"):
            cells = row.css("td")
            if len(cells) >= 2:
                label = _text(cells[0])
                value = _text(cells[1])
                for arabic_label, key in stats_map.items():
                    if arabic_label in label:
                        stats[key] = value
                        break

    hire_rate_raw = stats.get("hire_rate", "")
    open_projects_text = stats.get("open_projects", "0")
    open_projects_match = re.search(r"(\d+)", open_projects_text)

    return PublisherInfo(
        publisher_id=publisher_id,
        display_name=display_name,
        role=role,
        profile_url=profile_url,
        identity_verified=identity_verified,
        registration_date=stats.get("registered", ""),
        hire_rate_raw=hire_rate_raw,
        hire_rate=_parse_hire_rate(hire_rate_raw),
        open_projects=int(open_projects_match.group(1)) if open_projects_match else 0,
    )


# ═══════════════════════════════════════════════════════════
# Proposals Extraction
# ═══════════════════════════════════════════════════════════


def _extract_proposals(section: Node) -> list[ProposalInfo]:
    """Extract visible proposals from the #project-bids section.

    Args:
        section: The bids section Node.

    Returns:
        List of ProposalInfo dataclasses.
    """
    proposals: list[ProposalInfo] = []

    for bid_el in section.css(".bid[data-bid-item]"):
        try:
            # Name
            name_el = bid_el.css_first(".profile__name bdi")
            name = _text(name_el) if name_el else _text(bid_el.css_first(".profile__name"))

            # Rating
            rating = 0.0
            rating_el = bid_el.css_first("li.rating-stars")
            if rating_el:
                rating_text = _text(rating_el)
                match = re.search(r"([\d.]+)", rating_text)
                if match:
                    try:
                        rating = float(match.group(1))
                    except ValueError:
                        pass

            # Time
            time_el = bid_el.css_first("time[datetime]")
            proposed_at = _attr(time_el, "datetime") if time_el else ""

            # Verification badge
            badge = bid_el.css_first(".profile-verification-badge, .verified-badge")
            verified = badge is not None

            proposals.append(ProposalInfo(
                proposer_name=name,
                proposer_verified=verified,
                proposer_rating=rating,
                proposed_at=proposed_at,
            ))
        except Exception as e:
            logger.warning("Failed to parse proposal: %s", e)

    return proposals


# ═══════════════════════════════════════════════════════════
# Detail Page Scraper
# ═══════════════════════════════════════════════════════════


class DetailScraper:
    """Parses full project detail pages from HTML.

    Extracts all available data: description, budget, skills, duration,
    publisher info, and visible proposals. Every extraction is resilient —
    missing fields are logged as warnings but never cause crashes.
    """

    def parse_detail_page(
        self, html: str, mostaql_id: str
    ) -> Optional[JobDetail]:
        """Parse a raw HTML detail page into a JobDetail dataclass.

        Args:
            html: Complete HTML content of the detail page.
            mostaql_id: The job's Mostaql ID for linking.

        Returns:
            A JobDetail instance with all available fields, or None
            if the page could not be parsed at all.
        """
        try:
            tree = HTMLParser(html)
        except Exception as e:
            logger.error("Failed to parse HTML for %s: %s", mostaql_id, e)
            return None

        # ── Title ────────────────────────────────────────
        title_el = (
            tree.css_first("span[data-type='page-header-title']")
            or tree.css_first("h1")
        )
        title = _text(title_el)

        # ── Category from breadcrumbs ────────────────────
        breadcrumbs = tree.css("ol.breadcrumb li.breadcrumb-item")
        category = ""
        if len(breadcrumbs) >= 3:
            category = _text(breadcrumbs[2])
        elif len(breadcrumbs) >= 2:
            category = _text(breadcrumbs[1])

        # ── Sidebar meta panel ───────────────────────────
        sidebar = tree.css_first("#project-meta-panel")

        budget_min: Optional[float] = None
        budget_max: Optional[float] = None
        budget_raw = ""
        duration = ""
        experience_level = ""
        skills: list[str] = []
        status = ""

        if sidebar:
            # Status
            status_el = sidebar.css_first(
                ".label-prj-open, .label-prj-closed, .label-prj-inprogress"
            )
            if status_el:
                status = _text(status_el)
            else:
                status = _extract_meta_value(sidebar, "حالة المشروع")

            # Budget
            budget_el = sidebar.css_first(
                "[data-type='project-budget_range'], [data-type=project-budget_range]"
            )
            if budget_el:
                budget_raw = _text(budget_el)
            else:
                budget_raw = _extract_meta_value(sidebar, "الميزانية")

            budget_min, budget_max, budget_raw = _parse_budget(budget_raw)

            # Duration
            duration = _extract_meta_value(sidebar, "مدة التنفيذ")

            # Experience level
            experience_level = _extract_meta_value(sidebar, "مستوى الخبرة")

            # Skills
            skill_items = sidebar.css("li.skills__item bdi")
            skills = [_text(s) for s in skill_items if _text(s)]
            # Fallback: try without bdi
            if not skills:
                skill_items = sidebar.css("li.skills__item")
                skills = [_text(s) for s in skill_items if _text(s)]
        else:
            logger.warning("No sidebar found for %s", mostaql_id)

        # ── Full description ─────────────────────────────
        desc_el = (
            tree.css_first("#projectDetailsTab .carda__content")
            or tree.css_first(".carda__content")
            or tree.css_first(".project-description")
        )
        full_description = _text(desc_el)

        # ── Publisher info ───────────────────────────────
        publisher: Optional[PublisherInfo] = None
        pub_widget = tree.css_first(
            "#project-meta-panel [data-type='employer_widget'], "
            "[data-type=employer_widget]"
        )
        if pub_widget:
            try:
                publisher = _extract_publisher(pub_widget)
            except Exception as e:
                logger.warning("Failed to extract publisher for %s: %s", mostaql_id, e)

        # ── Proposals ────────────────────────────────────
        proposals: list[ProposalInfo] = []
        bids_section = tree.css_first("#project-bids")
        if bids_section:
            try:
                proposals = _extract_proposals(bids_section)
            except Exception as e:
                logger.warning("Failed to extract proposals for %s: %s", mostaql_id, e)

        # ── Attachments count ────────────────────────────
        attachments = tree.css(
            ".project-attachments .attachment, .attachments .attachment"
        )

        detail = JobDetail(
            mostaql_id=mostaql_id,
            full_description=full_description,
            duration=duration,
            experience_level=experience_level,
            budget_min=budget_min,
            budget_max=budget_max,
            budget_raw=budget_raw,
            skills=skills,
            attachments_count=len(attachments),
            publisher=publisher,
            proposals=proposals,
        )

        # Log extraction quality
        fields_present = sum([
            bool(full_description), bool(duration), bool(budget_raw),
            bool(skills), bool(publisher), bool(status),
        ])
        logger.info(
            "Parsed detail for %s: %s (%d/6 fields)",
            mostaql_id, title[:40], fields_present,
        )

        return detail

    async def scrape_detail(
        self,
        client: MostaqlClient,
        url: str,
        mostaql_id: str,
    ) -> Optional[JobDetail]:
        """Fetch and parse a project's detail page.

        Args:
            client: Active MostaqlClient instance.
            url: Full URL to the project page.
            mostaql_id: The job's Mostaql ID.

        Returns:
            A JobDetail instance, or None if fetch/parse failed.
        """
        html = await client.get_detail_page(url)
        if html is None:
            logger.warning("Failed to fetch detail page for %s", mostaql_id)
            return None

        return self.parse_detail_page(html, mostaql_id)
