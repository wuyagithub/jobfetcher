"""Data models for JobFetcher job scraping agent."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobSource(str, Enum):
    """Supported job search sources."""

    LINKEDIN = "linkedin"
    GLASSDOOR = "glassdoor"
    ZIPRECRUITER = "ziprecruiter"


class LocationType(str, Enum):
    """Type of job location."""

    ONSITE = "onsite"
    REMOTE = "remote"
    HYBRID = "hybrid"


class EmploymentType(str, Enum):
    """Type of employment."""

    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACTOR = "CONTRACTOR"
    INTERNSHIP = "INTERNSHIP"
    TEMPORARY = "TEMPORARY"


class SalaryInterval(str, Enum):
    """Salary payment interval."""

    YEAR = "YEAR"
    MONTH = "MONTH"
    HOUR = "HOUR"
    WEEK = "WEEK"


class Company(BaseModel):
    """Company information."""

    name: str
    url: Optional[str] = None
    logo: Optional[str] = None


class Location(BaseModel):
    """Location information."""

    type: Optional[LocationType] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "US"
    postal_code: Optional[str] = None

    def to_display_string(self) -> str:
        """Convert to human-readable string."""
        parts = []
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts) if parts else "Unknown"


class Salary(BaseModel):
    """Salary information."""

    currency: str = "USD"
    min: Optional[float] = None
    max: Optional[float] = None
    interval: Optional[SalaryInterval] = None

    def to_display_string(self) -> str:
        """Convert to human-readable string."""
        if self.min and self.max:
            return f"{self.currency} {self.min:,.0f} - {self.max:,.0f} / {self.interval.value.lower() if self.interval else 'year'}"
        elif self.min:
            return f"{self.currency} {self.min:,.0f}+ / {self.interval.value.lower() if self.interval else 'year'}"
        elif self.max:
            return f"Up to {self.currency} {self.max:,.0f} / {self.interval.value.lower() if self.interval else 'year'}"
        return "Not specified"


class Requirements(BaseModel):
    """Job requirements."""

    experience: Optional[str] = None
    education: Optional[str] = None
    skills: list[str] = Field(default_factory=list)


class JobDescription(BaseModel):
    """Job description content."""

    raw: str
    html: Optional[str] = None


class JobListing(BaseModel):
    """Complete job listing data model.

    Based on Schema.org JobPosting standard.
    """

    id: str
    source: JobSource
    source_url: str
    job_title: str
    company: Company
    location: Location
    employment_type: Optional[EmploymentType] = None
    salary: Optional[Salary] = None
    description: JobDescription
    requirements: Requirements = Field(default_factory=Requirements)
    posted_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    scraped_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return self.model_dump(mode="json")

    def to_json(self, **kwargs) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    def to_display_summary(self) -> str:
        """Get a short summary string."""
        salary_str = self.salary.to_display_string() if self.salary else "Salary not specified"
        return f"{self.job_title} at {self.company.name} ({self.location.to_display_string()}) - {salary_str}"


class SearchFilters(BaseModel):
    """Filters for job search."""

    source: Optional[JobSource] = None
    keyword: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    location_type: Optional[LocationType] = None
    posted_within_days: Optional[int] = None
    limit: int = 100


class ScraperConfig(BaseModel):
    """Configuration for scraper behavior."""

    requests_per_second: float = 1.0
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0
    max_results: int = 1000
    headless: bool = True
    user_agent: Optional[str] = None
    proxy: Optional[str] = None
    cookies_file: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True
