"""Mostaql Notifier — Listing Page Scraper.

Parses project listings from the XHR JSON response. Each item in the
'collection' array contains an integer 'id' and a 'rendered' HTML string.

CSS selectors are adapted from the working investigation scraper and
use selectolax (HTMLParser) instead of BeautifulSoup.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from selectolax.parser import HTMLParser, Node

from src.config import ScraperConfig
from src.database.models import JobListing
from src.scraper.client import MostaqlClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Debug dump directory for unparseable rows
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "debug"


def _parse_proposals_count(text: str) -> int:
    """Extract a numeric proposal count from Arabic proposal text.

    Handles common patterns:
      "أضف أول عرض"  → 0
      "عرض واحد"     → 1
      "عرضان"        → 2
      "3 عروض"       → 3

    Args:
        text: Raw Arabic proposals text.

    Returns:
        Integer proposal count.
    """
    if not text:
        return 0
    if "أضف" in text:
        return 0
    if "واحد" in text:
        return 1
    if "عرضان" in text or "عرضين" in text:
        return 2
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    return 0


def _text(node: Optional[Node]) -> str:
    """Safely extract stripped text from a selectolax node.

    Args:
        node: A selectolax Node, or None.

    Returns:
        Stripped text content, or empty string if node is None.
    """
    if node is None:
        return ""
    return node.text(strip=True)


def _attr(node: Optional[Node], name: str) -> str:
    """Safely extract an attribute from a selectolax node.

    Args:
        node: A selectolax Node, or None.
        name: Attribute name to extract.

    Returns:
        Attribute value, or empty string if node/attr is None.
    """
    if node is None:
        return ""
    val = node.attributes.get(name)
    return val if val else ""


class ListScraper:
    """Parses project listings from the XHR JSON endpoint.

    Uses selectolax to parse the 'rendered' HTML within each
    collection item. Applies multiple selector fallbacks for
    robustness against minor HTML changes.

    Attributes:
        config: Scraper configuration with base_url.
    """

    def __init__(self, config: ScraperConfig) -> None:
        """Initialize the list scraper.

        Args:
            config: ScraperConfig from the app configuration.
        """
        self.config = config

    def parse_listing_response(
        self, json_data: dict[str, Any]
    ) -> list[JobListing]:
        """Parse the full XHR JSON response into JobListing dataclasses.

        Iterates over the 'collection' array. Each item has an integer 'id'
        and a 'rendered' HTML string representing one project row.

        Args:
            json_data: Parsed JSON dict with 'collection' key.

        Returns:
            List of successfully parsed JobListing instances.
        """
        collection = json_data.get("collection", [])
        results: list[JobListing] = []

        for idx, item in enumerate(collection):
            try:
                listing = self._parse_card(item)
                if listing:
                    results.append(listing)
            except Exception as e:
                logger.warning("Failed to parse listing card %d: %s", idx, e)
                self._debug_dump_row(item.get("rendered", ""), idx)

        return results

    def _parse_card(self, item: dict[str, Any]) -> Optional[JobListing]:
        """Parse a single collection item into a JobListing.

        Args:
            item: Dict with 'id' (int) and 'rendered' (HTML string).

        Returns:
            A JobListing instance, or None if essential fields are missing.
        """
        mostaql_id = str(item.get("id", ""))
        rendered = item.get("rendered", "")
        if not mostaql_id or not rendered:
            return None

        tree = HTMLParser(rendered)

        # ── Title + URL ──────────────────────────────────
        title_el = (
            tree.css_first("h2.mrg--bt-reset > a")
            or tree.css_first("h2 > a")
            or tree.css_first("a[href*='/projects/']")
        )
        if title_el is None:
            logger.warning("No title found for listing %s", mostaql_id)
            self._debug_dump_row(rendered, -1)
            return None

        title = _text(title_el)
        href = _attr(title_el, "href")
        url = href if href.startswith("http") else self.config.base_url + href

        # ── Publisher name ───────────────────────────────
        pub_el = (
            tree.css_first("ul.project__meta bdi")
            or tree.css_first(".project__meta bdi")
            or tree.css_first("bdi")
        )
        publisher_name = _text(pub_el)

        # ── Posted timestamp ─────────────────────────────
        time_el = tree.css_first("time[datetime]")
        time_posted = _attr(time_el, "datetime") if time_el else ""
        if not time_posted:
            time_el2 = tree.css_first("time")
            time_posted = _text(time_el2)

        # ── Proposals count ──────────────────────────────
        proposals_count = 0
        for li in tree.css("ul.project__meta > li.text-muted"):
            text = _text(li)
            if "عرض" in text or "أضف" in text:
                proposals_count = _parse_proposals_count(text)
                break
        # Fallback: look for any element with proposals text
        if proposals_count == 0:
            for li in tree.css("li"):
                text = _text(li)
                if "عرض" in text or "أضف" in text:
                    proposals_count = _parse_proposals_count(text)
                    break

        # ── Brief description ────────────────────────────
        desc_el = (
            tree.css_first("p.project__brief a")
            or tree.css_first("p.project__brief")
            or tree.css_first(".project__brief")
        )
        brief_description = _text(desc_el)

        return JobListing(
            mostaql_id=mostaql_id,
            title=title,
            url=url,
            publisher_name=publisher_name,
            time_posted=time_posted,
            brief_description=brief_description,
            proposals_count=proposals_count,
        )

    def _debug_dump_row(self, html: str, index: int) -> None:
        """Save an unparseable HTML row to disk for manual inspection.

        Writes to logs/debug/row_{index}.html. Creates the debug
        directory if it doesn't exist.

        Args:
            html: Raw HTML string of the failing row.
            index: The index of the row in the collection.
        """
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            path = DEBUG_DIR / f"row_{index}.html"
            path.write_text(html, encoding="utf-8")
            logger.debug("Saved debug dump to %s", path)
        except Exception as e:
            logger.warning("Failed to save debug dump: %s", e)

    async def scrape_listings(
        self,
        client: MostaqlClient,
        pages: int = 3,
        **filters: Any,
    ) -> list[JobListing]:
        """Scrape multiple listing pages and return deduplicated jobs.

        Stops early if a page returns 0 projects (end of results).

        Args:
            client: Active MostaqlClient instance.
            pages: Number of pages to scrape.
            **filters: Optional query filters (category, keyword, etc.).

        Returns:
            List of JobListing instances, deduplicated by mostaql_id.
        """
        seen_ids: set[str] = set()
        all_jobs: list[JobListing] = []

        for page in range(1, pages + 1):
            json_data = await client.get_listing_page(page=page, **filters)
            if json_data is None:
                logger.warning("Failed to fetch listing page %d, stopping", page)
                break

            jobs = self.parse_listing_response(json_data)
            if not jobs:
                logger.info("No projects on page %d, stopping", page)
                break

            # Deduplicate
            new_count = 0
            for job in jobs:
                if job.mostaql_id not in seen_ids:
                    seen_ids.add(job.mostaql_id)
                    all_jobs.append(job)
                    new_count += 1

            logger.info(
                "Page %d: %d parsed, %d new (total: %d)",
                page, len(jobs), new_count, len(all_jobs),
            )

        logger.info("Listing scrape complete: %d unique jobs", len(all_jobs))
        return all_jobs
