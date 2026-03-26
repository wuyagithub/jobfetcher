"""
LinkedIn scraper with company website fallback.

Flow:
1. Scrape LinkedIn jobs with JD
2. For jobs where JD is empty, fallback to company website via Google search
"""

import asyncio
import json
from typing import Optional

from jobfetcher.scrapers.company_careers import get_jd_fallback_chain


async def enrich_empty_jd_with_company_website(jobs: list) -> list:
    """For jobs with empty JD, try to get JD from company website.

    Args:
        jobs: List of job dicts with 'company', 'title', 'location', 'description'

    Returns:
        Updated jobs list with enriched JD where possible
    """
    enriched = 0
    empty_jd_count = 0

    for job in jobs:
        description = job.get("description", "") or ""

        # Check if JD is empty or very short
        if len(description.strip()) < 50:  # Consider empty if < 50 chars
            empty_jd_count += 1

            company = job.get("company", "")
            title = job.get("title", job.get("job_title", ""))
            location = job.get("location", "")

            # Try to get JD from company website
            result = await get_jd_fallback_chain(
                company_name=company,
                job_title=title,
                location=location,
            )

            if result and result.get("jd"):
                job["description"] = result["jd"]
                job["jd_source"] = "company_website"
                job["jd_source_method"] = result.get("method", "unknown")
                enriched += 1
                print(f"    ✓ Enriched JD for: {title} @ {company}")

    print(f"\n[JD Enrichment Summary]")
    print(f"  Jobs with empty JD: {empty_jd_count}")
    print(f"  Successfully enriched: {enriched}")
    print(f"  Still empty: {empty_jd_count - enriched}")

    return jobs


async def scrape_linkedin_with_fallback(keywords: str, location: str, max_pages: int = 5):
    """Scrape LinkedIn and enrich empty JDs with company website fallback.

    This is a placeholder - actual implementation would use the Playwright MCP
    or the scraper module to get LinkedIn jobs.

    For now, this demonstrates the fallback logic.
    """
    # In real implementation, this would call the actual LinkedIn scraper
    # For demonstration, we show the fallback logic

    print("LinkedIn scraping with company website fallback enabled")
    print("-" * 50)

    # Placeholder for scraped jobs
    # In production, this would come from scrape_all_jobs.py or Playwright MCP
    placeholder_jobs = []

    return placeholder_jobs


if __name__ == "__main__":
    # Test the fallback with a sample job
    async def test():
        sample_job = {
            "title": "Civil Engineering Intern",
            "company": "Bowman Consulting",
            "location": "Alpharetta, GA",
            "description": "",  # Empty JD - triggers fallback
            "url": "https://www.linkedin.com/jobs/view/123",
        }

        print("Testing JD enrichment for job with empty description...")
        print(f"Before: JD length = {len(sample_job.get('description', ''))}")

        result = await enrich_empty_jd_with_company_website([sample_job])

        print(f"\nAfter: JD length = {len(result[0].get('description', ''))}")
        if result[0].get("jd_source"):
            print(f"Source: {result[0].get('jd_source')}")

    asyncio.run(test())
