"""
Job Extractor using Playwright MCP
Extracts job listings from LinkedIn using browser automation
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


# Job data model
class JobListing:
    def __init__(
        self,
        job_title: str,
        company: str,
        location: str,
        description: str = "",
        salary: str = "",
        source_url: str = "",
        source: str = "LinkedIn",
    ):
        self.job_title = job_title
        self.company = company
        self.location = location
        self.description = description
        self.salary = salary
        self.source_url = source_url
        self.source = source
        self.scraped_at = datetime.now().isoformat()

    def to_dict(self):
        return {
            "job_title": self.job_title,
            "company": self.company,
            "location": self.location,
            "description": self.description,
            "salary": self.salary,
            "source_url": self.source_url,
            "source": self.source,
            "scraped_at": self.scraped_at,
        }


# HTML parsing functions (using the browser content)
def parse_jobs_from_text(text: str) -> list[JobListing]:
    """Parse job listings from page text content."""
    jobs = []
    lines = text.split("\n")

    # Patterns to identify job entries
    company_pattern = re.compile(
        r"^(Stantec|Bowman Consulting|WSP|Carollo|Jacobs|AECOM)", re.IGNORECASE
    )
    location_pattern = re.compile(r"^[A-Z][a-z]+,?\s*[A-Z]{2}\s*\d{5}")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for job titles (typically followed by company name)
        if "intern" in line.lower() and any(
            kw in line.lower() for kw in ["civil", "environmental", "engineering"]
        ):
            job_title = line

            # Next non-empty line should be company
            company = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("Salary"):
                    company = next_line
                    break

            # Next should be location
            location = ""
            for j in range(i + 1, min(i + 8, len(lines))):
                next_line = lines[j].strip()
                if re.match(r"^[A-Z][a-z]+,?\s*[A-Z]{2}", next_line):
                    location = next_line
                    break

            # Check for salary
            salary = ""
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j].strip()
                if "Salary" in next_line or "$" in next_line:
                    salary = next_line
                    break

            if company and location:
                jobs.append(
                    JobListing(
                        job_title=job_title,
                        company=company,
                        location=location,
                        salary=salary,
                        description=f"Found via LinkedIn search: {job_title}",
                    )
                )

        i += 1

    return jobs


def save_to_json(jobs: list[JobListing], filepath: str):
    """Save jobs to JSON file."""
    data = {
        "search_keywords": "civil engineering and environmental engineering jobs in the United States",
        "search_location": "United States",
        "source": "LinkedIn",
        "scraped_at": datetime.now().isoformat(),
        "total_found": len(jobs),
        "jobs": [job.to_dict() for job in jobs],
    }

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return filepath


def display_jobs(jobs: list[JobListing]):
    """Display jobs in console."""
    print(f"\n{'=' * 60}")
    print(f"Found {len(jobs)} jobs")
    print(f"{'=' * 60}\n")

    for i, job in enumerate(jobs, 1):
        print(f"{i}. {job.job_title}")
        print(f"   Company: {job.company}")
        print(f"   Location: {job.location}")
        if job.salary:
            print(f"   Salary: {job.salary}")
        print()


# Main extraction logic - to be used with Playwright MCP
EXTRACTION_SCRIPT = """
async (page) => {
  // Wait for content to load
  await page.waitForTimeout(3000);
  
  // Scroll to load all content
  for (let i = 0; i < 5; i++) {
    await page.evaluate(() => window.scrollBy(0, 500));
    await page.waitForTimeout(500);
  }
  
  // Get all text content
  const text = await page.evaluate(() => document.body.innerText);
  
  // Also get job links for URLs
  const jobLinks = await page.evaluate(() => {
    const links = [];
    document.querySelectorAll('a[href*="/jobs/view"]').forEach(a => {
      if (a.href && a.href.includes('linkedin.com/jobs/view/')) {
        links.push(a.href);
      }
    });
    return links;
  });
  
  return JSON.stringify({
    text: text,
    links: jobLinks.slice(0, 20)
  });
}
"""


if __name__ == "__main__":
    print("Job Extractor using Playwright MCP (LinkedIn)")
    print("=" * 50)
    print("\nUsage:")
    print("1. Use browser_navigate to go to LinkedIn job search")
    print("2. Use browser_run_code with EXTRACTION_SCRIPT")
    print("3. Parse the result text with parse_jobs_from_text()")
    print("4. Save to JSON with save_to_json()")
    print("\nExample:")
    print(
        '  browser_navigate(url="https://www.linkedin.com/jobs/search/?keywords=civil+engineering+and+environmental+engineering+jobs+in+the+United+States&location=United+States")'
    )
    print("  browser_run_code(code=EXTRACTION_SCRIPT)")
    print('  python -c "parse_jobs_from_text(result_text)"')
