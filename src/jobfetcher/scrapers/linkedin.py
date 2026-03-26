"""LinkedIn job scraper implementation."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

from jobfetcher.models import (
    Company,
    EmploymentType,
    JobDescription,
    JobListing,
    JobSource,
    Location,
    LocationType,
    Requirements,
    Salary,
    SalaryInterval,
    ScraperConfig,
)
from jobfetcher.scrapers.base import BaseScraper


class LinkedInScraper(BaseScraper):
    """Scraper for LinkedIn job listings.

    Requires authentication via cookies or Playwright.
    For production use, consider using Apify's LinkedIn scraper.
    """

    BASE_URL = "https://www.linkedin.com"
    JOBS_URL = "https://www.linkedin.com/jobs"

    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config)
        self._playwright_browser = None
        self._playwright_context = None

    @property
    def source(self) -> JobSource:
        return JobSource.LINKEDIN

    @property
    def base_url(self) -> str:
        return self.BASE_URL

    async def search(
        self,
        keywords: str,
        location: str,
        limit: int = 100,
        **kwargs,
    ) -> list[JobListing]:
        """Search for jobs on LinkedIn.

        Note: LinkedIn requires authentication. You need to:
        1. Use cookies_file config to point to a saved session
        2. Or use Playwright-based approach for better success

        Args:
            keywords: Job search keywords
            location: Location to search in
            limit: Maximum number of results

        Returns:
            List of job listings
        """
        # Try API-based approach first
        jobs = await self._search_via_api(keywords, location, limit)

        # Fallback to HTML parsing if API fails
        if not jobs:
            jobs = await self._search_via_html(keywords, location, limit)

        return jobs

    async def _search_via_api(self, keywords: str, location: str, limit: int) -> list[JobListing]:
        """Search using LinkedIn's internal API."""
        jobs = []

        # Use LinkedIn's job search API
        url = f"{self.JOBS_URL}/search/"
        params = {
            "keywords": keywords,
            "location": location,
            "count": min(limit, 100),
        }

        try:
            response = await self._get_with_retry(url, params=params)
            data = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )

            if data.get("elements"):
                for item in data["elements"]:
                    job = self._parse_api_job(item)
                    if job:
                        jobs.append(job)
        except Exception:
            pass

        return jobs

    async def _search_via_html(self, keywords: str, location: str, limit: int) -> list[JobListing]:
        """Search using HTML page parsing."""
        jobs = []

        encoded_keywords = keywords.replace(" ", "%20")
        encoded_location = location.replace(" ", "%20")

        url = f"{self.JOBS_URL}/search/?keywords={encoded_keywords}&location={encoded_location}"

        try:
            response = await self._get_with_retry(url)
            soup = BeautifulSoup(response.text, "html.parser")

            # Try to extract data from page
            jobs = self._parse_html_search_results(soup)
        except Exception:
            pass

        return jobs

    def _parse_api_job(self, data: dict) -> Optional[JobListing]:
        """Parse job from API response."""
        try:
            job_id = data.get("jobPosting", {}).get("dashEntityUrn", "").split(":")[-1]
            if not job_id:
                job_id = str(uuid.uuid4())

            title = data.get("jobPosting", {}).get("title", "")
            company_name = (
                data.get("jobPosting", {}).get("companyDetails", {}).get("companyName", "")
            )
            company_url = data.get("jobPosting", {}).get("companyDetails", {}).get("companyUrn", "")

            # Location
            location_data = data.get("jobPosting", {}).get("jobLocation", {})
            location = Location(
                city=location_data.get("city"),
                state=location_data.get("geographicArea"),
                country=location_data.get("countryCode", "US"),
            )

            # Check for remote
            if data.get("jobPosting", {}).get("workType") == "remote":
                location.type = LocationType.REMOTE

            # Description
            description_raw = data.get("jobPosting", {}).get("description", {}).get("text", "")

            # Salary
            salary_data = data.get("jobPosting", {}).get("salary", {})
            salary = None
            if salary_data:
                salary = Salary(
                    currency=salary_data.get("currencyCode", "USD"),
                    min=salary_data.get("minimum"),
                    max=salary_data.get("maximum"),
                )

            return JobListing(
                id=job_id,
                source=self.source,
                source_url=f"{self.JOBS_URL}/view/{job_id}",
                job_title=title,
                company=Company(name=company_name, url=company_url),
                location=location,
                description=JobDescription(raw=description_raw),
                salary=salary,
                scraped_at=datetime.now(),
            )
        except Exception:
            return None

    def _parse_html_search_results(self, soup: BeautifulSoup) -> list[JobListing]:
        """Parse job listings from HTML search results."""
        jobs = []

        # Try to find job cards
        job_cards = soup.find_all("li", class_="job-card-list")

        for card in job_cards:
            try:
                job = self._parse_html_job_card(card)
                if job:
                    jobs.append(job)
            except Exception:
                continue

        # Alternative: look for JSON data in page
        if not jobs:
            jobs.extend(self._parse_json_data(soup))

        return jobs

    def _parse_html_job_card(self, card) -> Optional[JobListing]:
        """Parse a single job card from HTML."""
        try:
            # Find job link
            link = card.find("a", class_="job-card-list__link")
            if not link:
                return None

            job_id = link.get("data-job-id", "")
            if not job_id:
                job_id = str(uuid.uuid4())

            job_url = link.get("href", "")
            if job_url and not job_url.startswith("http"):
                job_url = f"{self.BASE_URL}{job_url}"

            # Title
            title_elem = card.find("h3", class_="job-card-list__title")
            title = title_elem.get_text(strip=True) if title_elem else "Unknown"

            # Company
            company_elem = card.find("h4", class_="job-card-container__company-name")
            company_name = company_elem.get_text(strip=True) if company_elem else "Unknown"

            # Location
            location_elem = card.find("div", class_="job-card-container__metadata-item")
            location_str = location_elem.get_text(strip=True) if location_elem else ""
            location = self._parse_location_string(location_str)

            return JobListing(
                id=job_id,
                source=self.source,
                source_url=job_url,
                job_title=title,
                company=Company(name=company_name),
                location=location,
                description=JobDescription(raw=""),
                scraped_at=datetime.now(),
            )
        except Exception:
            return None

    def _parse_json_data(self, soup: BeautifulSoup) -> list[JobListing]:
        """Parse job data from embedded JSON."""
        jobs = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "JobPosting":
                            job = self._convert_json_ld_to_job(item)
                            if job:
                                jobs.append(job)
                elif data.get("@type") == "JobPosting":
                    job = self._convert_json_ld_to_job(data)
                    if job:
                        jobs.append(job)
            except (json.JSONDecodeError, AttributeError):
                continue

        return jobs

    def _convert_json_ld_to_job(self, data: dict) -> Optional[JobListing]:
        """Convert JSON-LD to JobListing."""
        try:
            return JobListing(
                id=str(uuid.uuid4()),
                source=self.source,
                source_url=data.get("url", ""),
                job_title=data.get("title", ""),
                company=Company(
                    name=data.get("hiringOrganization", {}).get("name", ""),
                    url=data.get("hiringOrganization", {}).get("sameAs"),
                ),
                location=Location(
                    city=data.get("jobLocation", {}).get("address", {}).get("addressLocality"),
                    state=data.get("jobLocation", {}).get("address", {}).get("addressRegion"),
                    country=data.get("jobLocation", {})
                    .get("address", {})
                    .get("addressCountry", "US"),
                ),
                description=JobDescription(raw=data.get("description", "")),
                posted_date=self._parse_date(data.get("datePosted")),
                expiry_date=self._parse_date(data.get("validThrough")),
                scraped_at=datetime.now(),
            )
        except Exception:
            return None

    async def get_job_details(self, job_url: str) -> Optional[JobListing]:
        """Get detailed job information from job page."""
        try:
            response = await self._get_with_retry(job_url)
            return self._parse_job_detail(response.text, job_url)
        except Exception:
            return None

    def _parse_job_detail(self, html: str, source_url: str) -> Optional[JobListing]:
        """Parse job detail page."""
        soup = BeautifulSoup(html, "html.parser")

        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if data.get("@type") == "JobPosting":
                    job = self._convert_json_ld_to_job(data)
                    if job:
                        job.source_url = source_url
                        return job
            except (json.JSONDecodeError, AttributeError):
                continue

        # Fallback to HTML parsing
        return self._parse_job_detail_html(soup, source_url)

    def _parse_job_detail_html(self, soup: BeautifulSoup, source_url: str) -> Optional[JobListing]:
        """Parse job detail from HTML."""
        try:
            # Title
            title_elem = soup.find("h1", class_="job-card-list__header")
            title = title_elem.get_text(strip=True) if title_elem else "Unknown"

            # Company
            company_elem = soup.find("a", class_="job-card-container__company-name-link")
            company_name = company_elem.get_text(strip=True) if company_elem else "Unknown"
            company_url = None
            if company_elem:
                href = company_elem.get("href", "")
                if href:
                    company_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            # Description
            desc_elem = soup.find("div", class_="job-view-layout")
            description_raw = desc_elem.get_text(strip=True) if desc_elem else ""

            return JobListing(
                id=str(uuid.uuid4()),
                source=self.source,
                source_url=source_url,
                job_title=title,
                company=Company(name=company_name, url=company_url),
                location=Location(country="US"),
                description=JobDescription(raw=description_raw),
                scraped_at=datetime.now(),
            )
        except Exception:
            return None

    def _parse_location_string(self, text: str) -> Location:
        """Parse location string to Location object."""
        location = Location(country="US")

        if not text:
            return location

        text_lower = text.lower()

        # Check for remote
        if "remote" in text_lower:
            location.type = LocationType.REMOTE
        elif "hybrid" in text_lower:
            location.type = LocationType.HYBRID

        # Parse city, state
        parts = text.split(",")
        if len(parts) >= 1:
            location.city = parts[0].strip()
        if len(parts) >= 2:
            location.state = parts[1].strip()

        return location

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO date string."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    async def authenticate_with_cookies(self, cookies_file: str = "linkedin_cookies.json") -> bool:
        """Authenticate using saved cookies."""
        try:
            path = Path(cookies_file)
            if not path.exists():
                return False

            with open(path) as f:
                cookies = json.load(f)

            self.session.cookies.update(cookies)
            return True
        except Exception:
            return False

    async def close(self):
        """Close HTTP session and playwright."""
        await super().close()
        if self._playwright_context:
            await self._playwright_context.close()
        if self._playwright_browser:
            await self._playwright_browser.close()
