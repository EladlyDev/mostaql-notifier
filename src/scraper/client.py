"""Mostaql Notifier — Async HTTP Client.

Provides a robust, rate-limited, retrying async HTTP client for
scraping mostaql.com. Built on httpx.AsyncClient with:
  - User-agent rotation from config
  - Exponential backoff retry (429, 5xx, timeout, connection errors)
  - Rate limiting via AsyncRateLimiter
  - Separate methods for XHR (listing) and HTML (detail) requests
  - Request counting for session telemetry
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

import httpx

from src.config import ScraperConfig
from src.utils.logger import get_logger
from src.utils.rate_limiter import AsyncRateLimiter

logger = get_logger(__name__)

# ── Browser-like headers common to all requests ──────────
_COMMON_HEADERS = {
    "Accept-Language": "ar,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


class MostaqlClient:
    """Async HTTP client for mostaql.com with retry and rate limiting.

    Integrates with ScraperConfig for all tunable parameters and
    AsyncRateLimiter for request throttling.

    Attributes:
        config: Scraper configuration from the YAML config.
        total_requests: Running count of successful requests this session.
    """

    def __init__(self, config: ScraperConfig) -> None:
        """Initialize the client from a ScraperConfig.

        Args:
            config: ScraperConfig instance loaded from settings.yaml.
        """
        self.config = config
        self.total_requests: int = 0
        self._rate_limiter = AsyncRateLimiter(
            max_calls=1,
            period_seconds=float(config.request_delay_seconds),
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the httpx.AsyncClient.

        Returns:
            The active async HTTP client.
        """
        if self._client is None:
            ua = random.choice(self.config.user_agents)
            self._client = httpx.AsyncClient(
                headers={
                    **_COMMON_HEADERS,
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                follow_redirects=True,
                timeout=httpx.Timeout(self.config.timeout_seconds),
            )
        return self._client

    def _rotate_ua(self) -> None:
        """Rotate the User-Agent header to a random one from config."""
        if self._client is not None:
            ua = random.choice(self.config.user_agents)
            self._client.headers["User-Agent"] = ua

    async def get_listing_page(
        self, page: int = 1, **filters: Any
    ) -> Optional[dict[str, Any]]:
        """Fetch a listing page via XHR and return parsed JSON.

        Calls the XHR endpoint with X-Requested-With header to get
        the JSON response containing {pager, collection}.

        Args:
            page: Page number (1-indexed, 25 projects per page).
            **filters: Optional query params (sort, category, keyword,
                       budget_min, budget_max).

        Returns:
            Parsed JSON dict with 'pager' and 'collection' keys,
            or None if the request failed after all retries.
        """
        params: dict[str, str] = {"page": str(page)}
        for key, value in filters.items():
            if value is not None:
                params[key] = str(value)
        if "sort" not in params:
            params["sort"] = "latest"

        extra_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        url = self.config.projects_url
        logger.info("Fetching listing page %d (%s)", page, url)

        response = await self._request(url, params=params, extra_headers=extra_headers)
        if response is None:
            return None

        try:
            data = response.json()
            collection = data.get("collection", [])
            logger.info(
                "Listing page %d: %d items in collection",
                page, len(collection),
            )
            return data
        except Exception as e:
            logger.error("Failed to parse listing JSON for page %d: %s", page, e)
            return None

    async def get_detail_page(self, url: str) -> Optional[str]:
        """Fetch a detail page and return raw HTML.

        Uses browser-like headers for a normal HTML page request.

        Args:
            url: Full URL to the project detail page.

        Returns:
            Raw HTML string, or None if the request failed after all retries.
        """
        logger.info("Fetching detail: %s", url)

        # Use the detail delay instead of the normal request delay
        await asyncio.sleep(
            max(0, self.config.detail_delay_seconds - self.config.request_delay_seconds)
        )

        response = await self._request(url)
        if response is None:
            return None

        return response.text

    async def _request(
        self,
        url: str,
        params: Optional[dict[str, str]] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> Optional[httpx.Response]:
        """Execute a request with rate limiting and retry logic.

        Retry strategy:
          - 429 Too Many Requests: wait 30s then retry
          - 5xx Server Error: wait 5s × attempt then retry
          - Timeout: wait 3s × attempt then retry
          - Connection Error: wait 10s then retry

        Args:
            url: Request URL.
            params: Optional query parameters.
            extra_headers: Optional additional headers (e.g., XHR).

        Returns:
            The httpx Response, or None if all retries exhausted.
        """
        client = await self._get_client()
        max_retries = self.config.max_retries

        for attempt in range(1, max_retries + 1):
            # Rate limit
            await self._rate_limiter.acquire()
            self._rotate_ua()

            try:
                headers = dict(extra_headers) if extra_headers else {}
                resp = await client.get(url, params=params, headers=headers)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 30))
                    logger.warning(
                        "Rate limited (429) on attempt %d/%d. Waiting %ds...",
                        attempt, max_retries, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status_code >= 500:
                    wait = 5 * attempt
                    logger.warning(
                        "Server error %d on attempt %d/%d. Waiting %ds...",
                        resp.status_code, attempt, max_retries, wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                resp.raise_for_status()
                self.total_requests += 1
                return resp

            except httpx.TimeoutException:
                wait = 3 * attempt
                logger.warning(
                    "Timeout on attempt %d/%d. Waiting %ds...",
                    attempt, max_retries, wait,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)

            except httpx.ConnectError:
                wait = 10
                logger.warning(
                    "Connection error on attempt %d/%d. Waiting %ds...",
                    attempt, max_retries, wait,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)

            except httpx.HTTPStatusError as e:
                logger.error("HTTP error %d for %s: %s", e.response.status_code, url, e)
                return None

            except httpx.HTTPError as e:
                logger.warning(
                    "HTTP error on attempt %d/%d: %s",
                    attempt, max_retries, e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(3 * attempt)

        logger.error("All %d attempts failed for %s", max_retries, url)
        return None

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("HTTP client closed (total requests: %d)", self.total_requests)

    async def __aenter__(self) -> "MostaqlClient":
        """Async context manager entry.

        Returns:
            The MostaqlClient instance.
        """
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit — closes the client.

        Args:
            *args: Exception info (unused).
        """
        await self.close()
