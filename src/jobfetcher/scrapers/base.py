"""Base scraper implementation with rate limiting and anti-detection."""

from __future__ import annotations

import asyncio
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import httpx

from jobfetcher.models import (
    JobListing,
    JobSource,
    ScraperConfig,
)


class RateLimiter:
    """Rate limiter for controlling request frequency."""

    def __init__(self, requests_per_second: float = 1.0, burst_size: int = 5):
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.burst_size = burst_size
        self.tokens = burst_size
        self.last_refill = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Acquire a token, waiting if necessary."""
        async with self.lock:
            await self._refill_tokens()
            while self.tokens < 1:
                await self._refill_tokens()
                await asyncio.sleep(0.1)
            self.tokens -= 1

    async def _refill_tokens(self):
        """Refill tokens based on time elapsed."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst_size, self.tokens + elapsed / self.min_interval)
        self.last_refill = now

    async def wait(self):
        """Simple wait without token acquisition."""
        await asyncio.sleep(self.min_interval)


class AntiDetectionManager:
    """Manages anti-detection measures."""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config
        self.session_count = 0

    def get_random_user_agent(self) -> str:
        """Get a random user agent."""
        return random.choice(self.USER_AGENTS)

    def get_headers(self, source: JobSource) -> dict:
        """Get appropriate headers for target site."""
        headers = {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "DNT": "1",
        }

        return headers

    def get_proxy(self) -> Optional[dict]:
        """Get proxy configuration if set."""
        if self.config and self.config.proxy:
            return {
                "http://": self.config.proxy,
                "https://": self.config.proxy,
            }
        return None


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        self.rate_limiter = RateLimiter(
            requests_per_second=self.config.requests_per_second,
            burst_size=5,
        )
        self.anti_detection = AntiDetectionManager(self.config)
        self.session: Optional[httpx.AsyncClient] = None
        self._initialize_session()

    def _initialize_session(self):
        """Initialize HTTP session (sync version for compatibility)."""
        self.session = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout),
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        )

    async def _get_session(self) -> httpx.AsyncClient:
        """Get or create HTTP session."""
        if self.session is None:
            self._initialize_session()
        return self.session

    async def close(self):
        """Close HTTP session."""
        if self.session:
            await self.session.aclose()
            self.session = None

    @property
    @abstractmethod
    def source(self) -> JobSource:
        """Get the job source identifier."""
        pass

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Get the base URL for the job source."""
        pass

    @abstractmethod
    async def search(
        self,
        keywords: str,
        location: str,
        limit: int = 100,
        **kwargs,
    ) -> list[JobListing]:
        """Execute job search.

        Args:
            keywords: Job search keywords
            location: Location to search in
            limit: Maximum number of results
            **kwargs: Additional source-specific parameters

        Returns:
            List of job listings
        """
        pass

    @abstractmethod
    async def get_job_details(self, job_url: str) -> Optional[JobListing]:
        """Get detailed job information from job URL.

        Args:
            job_url: URL of the job listing

        Returns:
            Job listing with full details, or None if failed
        """
        pass

    async def _make_request(
        self,
        url: str,
        method: str = "GET",
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with rate limiting and anti-detection."""
        await self.rate_limiter.acquire()

        session = await self._get_session()
        headers = kwargs.pop("headers", {})
        headers.update(self.anti_detection.get_headers(self.source))

        proxy = self.anti_detection.get_proxy()
        if proxy:
            kwargs["proxies"] = proxy

        response = await session.request(method, url, headers=headers, **kwargs)
        return response

    async def _get_with_retry(
        self,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make a GET request with automatic retry."""
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = await self._make_request(url, **kwargs)
                if response.status_code == 200:
                    return response
                last_error = f"Status {response.status_code}"
            except Exception as e:
                last_error = str(e)

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        raise RuntimeError(f"Failed after {self.config.max_retries} attempts: {last_error}")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
