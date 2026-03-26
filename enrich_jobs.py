"""
Job Detail Enricher using Playwright MCP
Visits each job URL and extracts company, location, description, etc.
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path


async def extract_job_details(page, job_url):
    """Extract full details from a single job page."""
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1500)

        details = await page.evaluate(r"""
            () => {
                const text = document.body.innerText;
                const lines = text.split('\n').filter(l => l.trim());
                
                const result = {
                    title: '',
                    company: '',
                    location: '',
                    job_type: '',
                    posted_date: '',
                    description: '',
                    salary: ''
                };
                
                // Title - usually in h1 or the first large text
                const titleEl = document.querySelector('h1');
                if (titleEl) result.title = titleEl.innerText.trim();
                
                // Company - often follows title or is in subtitle
                const companyEl = document.querySelector('.job-details-jobs-unified-top-card__company-name') ||
                                  document.querySelector('[data-test-job-card-company-name]') ||
                                  document.querySelector('a[href*="/company/"]');
                if (companyEl) result.company = companyEl.innerText.trim();
                
                // Location - look for pattern like "City, ST" 
                const locationMatch = text.match(/([A-Z][a-zA-Z]+,?\s*[A-Z]{2}\s*\d*)/);
                if (locationMatch) result.location = locationMatch[1].trim();
                
                // Job type - look for employment type patterns
                const typeMatch = text.match(/(Full[\s-]?time|Part[\s-]?time|Internship|Contract|Temporary)/i);
                if (typeMatch) result.job_type = typeMatch[1].trim();
                
                // Posted date - look for relative time
                const postedMatch = text.match(/(1 day ago|2 days ago|3 days ago|4 days ago|5 days ago|6 days ago|1 week ago|2 weeks ago|3 weeks ago|4 weeks ago|1 month ago)/i);
                if (postedMatch) result.posted_date = postedMatch[1];
                
                // Salary - look for pay range patterns
                const salaryMatch = text.match(/US\$\d+[K,]?\s*[-–to]+\s*US\$\d+[K,]?|\$\d+[,.]?\d*\s*[/]\s*(hour|year|yr)/i);
                if (salaryMatch) result.salary = salaryMatch[0];
                
                // Description - extract from job content
                // Find the description section
                const descPatterns = [
                    /(?:Job\s*Summary|About\s*the\s*job|Job\s*Description)[\s\S]*?(?=Qualifications|Requirements|Benefits|About\s*the\s*company|Seniority|$)/i,
                    /(?:Key\s*Responsibilities|Duties)[\s\S]*?(?=Qualifications|Requirements|Benefits|$)/i
                ];
                
                let desc = '';
                for (const pattern of descPatterns) {
                    const match = text.match(pattern);
                    if (match && match[0].length > 100) {
                        desc = match[0];
                        break;
                    }
                }
                
                // If no pattern match, try getting text after location/company info
                if (!desc || desc.length < 100) {
                    // Find the section after posted date and before "Qualifications"
                    const qualIdx = text.toLowerCase().indexOf('qualifications');
                    const postedIdx = text.toLowerCase().indexOf('ago');
                    if (qualIdx > 0 && postedIdx > 0) {
                        desc = text.substring(postedIdx + 10, qualIdx + 2000);
                    }
                }
                
                // Truncate at common endpoints
                const stopPhrases = ['Seniority level', 'Similar jobs', 'Referrals', 'About the company', 'Show more', 'Skills:', 'Tools:'];
                for (const phrase of stopPhrases) {
                    const idx = desc.indexOf(phrase);
                    if (idx > 100) {
                        desc = desc.substring(0, idx);
                    }
                }
                
                result.description = desc.trim().substring(0, 5000);  // Limit length
                
                return result;
            }
        """)

        # Clean up description
        if details["description"]:
            # Remove excessive whitespace
            details["description"] = re.sub(r"\n{3,}", "\n\n", details["description"])

        return details

    except Exception as e:
        return {
            "title": "",
            "company": "",
            "location": "",
            "job_type": "",
            "posted_date": "",
            "description": f"Error extracting: {str(e)}",
            "salary": "",
        }


async def enrich_jobs(input_file, output_file, max_jobs=None):
    """Load jobs from JSON, visit each URL, extract details."""

    # Load existing jobs
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs", []) if isinstance(data, dict) else data

    if max_jobs:
        jobs = jobs[:max_jobs]

    print(f"Loaded {len(jobs)} jobs from {input_file}")
    print(f"Enriching up to {max_jobs or len(jobs)} jobs...")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        enriched_jobs = []

        for i, job in enumerate(jobs):
            url = job.get("url", "")
            if not url:
                continue

            print(f"[{i + 1}/{len(jobs)}] Processing: {job.get('title', 'Unknown')[:50]}...")

            details = await extract_job_details(page, url)

            # Merge original job data with enriched details
            enriched_job = {
                **job,
                "company": details.get("company", ""),
                "location": details.get("location", ""),
                "job_type": details.get("job_type", ""),
                "posted_date": details.get("posted_date", ""),
                "description": details.get("description", ""),
                "salary": details.get("salary", ""),
                "enriched_at": datetime.now().isoformat(),
            }

            enriched_jobs.append(enriched_job)

            # Small delay between requests
            if i < len(jobs) - 1:
                await page.wait_for_timeout(500)

        await browser.close()

    # Save enriched data
    enriched_data = {
        **data,
        "jobs" if isinstance(data, dict) else data: enriched_jobs,
        "enriched_at": datetime.now().isoformat(),
        "total_enriched": len(enriched_jobs),
    }

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched_data, f, indent=2, ensure_ascii=False)

    print(f"\n=== ENRICHMENT COMPLETE ===")
    print(f"Enriched jobs: {len(enriched_jobs)}")
    print(f"Saved to: {output_path}")

    # Show sample
    if enriched_jobs:
        print("\nSample enriched job:")
        sample = enriched_jobs[0]
        print(f"  Title: {sample.get('title', 'N/A')}")
        print(f"  Company: {sample.get('company', 'N/A')}")
        print(f"  Location: {sample.get('location', 'N/A')}")
        print(f"  Job Type: {sample.get('job_type', 'N/A')}")
        print(f"  Posted: {sample.get('posted_date', 'N/A')}")
        print(f"  Description: {sample.get('description', 'N/A')[:100]}...")

    return enriched_jobs


if __name__ == "__main__":
    import sys

    input_file = Path(__file__).parent / "data" / "linkedin_jobs_20260326_new.json"
    output_file = Path(__file__).parent / "data" / "linkedin_jobs_20260326_enriched.json"

    # Optional: limit number of jobs for testing
    max_jobs = None
    if len(sys.argv) > 1:
        max_jobs = int(sys.argv[1])

    asyncio.run(enrich_jobs(input_file, output_file, max_jobs))
