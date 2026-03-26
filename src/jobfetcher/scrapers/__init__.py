"""Job scrapers for various platforms."""

from jobfetcher.scrapers.base import BaseScraper
from jobfetcher.scrapers.linkedin import LinkedInScraper

__all__ = [
    "BaseScraper",
    "LinkedInScraper",
]
