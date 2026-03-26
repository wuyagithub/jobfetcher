"""Company career page scraper - fallback when LinkedIn JD is empty."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
from typing import Optional

import httpx
from bs4 import BeautifulSoup

# Common career page URL patterns for major companies
CARIER_URL_PATTERNS = {
    # These will be populated dynamically
}


async def search_company_careers_via_google(
    company_name: str,
    job_title: str,
    location: str = "",
) -> Optional[str]:
    """Search for company career page using Google.

    Args:
        company_name: Name of the company
        job_title: Job title to search for
        location: Optional location filter

    Returns:
        URL to the specific job posting, or None if not found
    """
    search_query = f"site:{company_name.lower().replace(' ', '')}.com careers {job_title}"
    if location:
        search_query += f" {location}"

    encoded_query = urllib.parse.quote_plus(search_query)
    google_url = f"https://www.google.com/search?q={encoded_query}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(google_url, headers=headers)

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Find search results
            for result in soup.select(".g"):
                link = result.select_one("a[href^='/url?q=']")
                if not link:
                    continue

                href = link.get("href", "")
                if "/url?q=" in href:
                    # Extract actual URL from Google redirect
                    url_match = re.search(r"/url\?q=([^&]+)", href)
                    if url_match:
                        url = urllib.parse.unquote(url_match.group(1))

                        # Skip Google links
                        if "google.com" in url:
                            continue

                        # Check if this looks like a job posting
                        url_lower = url.lower()
                        job_indicators = ["job", "career", "position", "opening", "employment"]
                        if any(ind in url_lower for ind in job_indicators):
                            return url

            return None

    except Exception as e:
        print(f"Google search error: {e}")
        return None


async def scrape_job_description_from_careers(url: str) -> Optional[str]:
    """Scrape job description from a company careers page.

    Args:
        url: Direct URL to the job posting or careers page

    Returns:
        Job description text, or None if failed
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove script and style elements
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()

            # Try to find job description in common containers
            description = None

            # Method 1: JSON-LD structured data
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if data.get("@type") == "JobPosting":
                            description = data.get("description", "")
                            if description:
                                # Clean HTML tags if present
                                desc_soup = BeautifulSoup(description, "html.parser")
                                description = desc_soup.get_text(separator="\n", strip=True)
                                return description
                        elif data.get("@type") == "JobPosting":
                            for item in data.get("@graph", []):
                                if item.get("@type") == "JobPosting":
                                    description = item.get("description", "")
                                    if description:
                                        desc_soup = BeautifulSoup(description, "html.parser")
                                        return desc_soup.get_text(separator="\n", strip=True)
                except (json.JSONDecodeError, AttributeError):
                    continue

            # Method 2: Common job description classes
            job_desc_selectors = [
                "job-description",
                "jobDescription",
                "description",
                "job-details",
                "job-details-content",
                "jd-content",
                "job-posting-content",
                "position-summary",
                "role-description",
                "about-role",
            ]

            for selector in job_desc_selectors:
                elem = soup.find(class_=re.compile(selector, re.I))
                if elem:
                    description = elem.get_text(separator="\n", strip=True)
                    if len(description) > 100:
                        return description

            # Method 3: Look for the longest text block
            text_blocks = []
            for p in soup.find_all(["div", "section", "article"]):
                text = p.get_text(separator=" ", strip=True)
                if len(text) > 500:
                    text_blocks.append(text)

            if text_blocks:
                # Return the longest block
                return max(text_blocks, key=len)

            return None

    except Exception as e:
        print(f"Careers page scrape error: {e}")
        return None


async def get_jd_from_company_website(
    company_name: str, job_title: str, location: str = ""
) -> Optional[str]:
    """Get job description from company website via Google search.

    This is a fallback when LinkedIn returns empty JD.

    Args:
        company_name: Name of the company
        job_title: Job title
        location: Job location (optional)

    Returns:
        Job description text, or None if not found
    """
    print(f"  [Fallback] Searching for JD on {company_name} website...")

    # Step 1: Google search for the job
    job_url = await search_company_careers_via_google(company_name, job_title, location)

    if not job_url:
        print(f"  [Fallback] No career page found via Google for {company_name}")
        return None

    print(f"  [Fallback] Found: {job_url[:80]}...")

    # Step 2: Scrape JD from that URL
    description = await scrape_job_description_from_careers(job_url)

    if description:
        print(f"  [Fallback] Successfully scraped JD ({len(description)} chars)")
    else:
        print(f"  [Fallback] Failed to extract JD from {job_url[:80]}")

    return description


async def get_jd_fallback_chain(company_name: str, job_title: str, location: str = "") -> dict:
    """Try multiple strategies to get JD from company website.

    Returns a dict with results from each strategy tried.
    """
    results = {
        "company_name": company_name,
        "job_title": job_title,
        "jd": None,
        "source_url": None,
        "method": None,
    }

    # Strategy 1: Google search for company careers page
    jd = await get_jd_from_company_website(company_name, job_title, location)

    if jd:
        results["jd"] = jd
        results["method"] = "google_search"
        # We don't track the exact URL in this simplified version
        # Could be enhanced to return the specific URL found

    return results


if __name__ == "__main__":
    # Test with a known company
    async def test():
        # Test Google search
        url = await search_company_careers_via_google("WSP", "Civil Engineering Intern", "Tampa")
        print(f"Found URL: {url}")

        if url:
            jd = await scrape_job_description_from_careers(url)
            print(f"JD length: {len(jd) if jd else 0}")
            if jd:
                print(jd[:500])

    asyncio.run(test())
