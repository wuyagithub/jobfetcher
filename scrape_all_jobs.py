"""
LinkedIn job scraper for Civil & Environmental Engineering internships.

Features:
- Date filter: past month (f_TPR=r2592000)
- Deduplication: skips already scraped jobs by URL
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from uuid import uuid4

from playwright.async_api import async_playwright


# ============================================================================
# CONSTANTS
# ============================================================================

# Date filter: "past month" = 30 days in seconds
# LinkedIn uses f_TPR parameter: r604800 (week), r2592000 (month), r7776000 (3 months)
DATE_FILTER_MONTH = "r2592000"

# Data directory
DATA_DIR = Path("data")

# Active JSON output — the canonical source file for this pipeline
# (also used by jd_fetch.py and migrate_to_sqlite.py)
OUTPUT_FILE = DATA_DIR / "linkedin_jobs_20260325_new.json"

# Fallback dedup files (if SQLite DB doesn't exist yet)
FALLBACK_DEDUP_FILES = [
    "linkedin_jobs_full.json",
    "linkedin_jobs_page1.json",
]


# ============================================================================
# DEDUPLICATION
# ============================================================================


def load_scraped_urls() -> Set[str]:
    """Load all previously scraped job URLs from all known sources.

    Checks:
      1. SQLite DB (primary, if exists)
      2. Active JSON output file (OUTPUT_FILE)
      3. Legacy fallback files

    Returns:
        Set of URLs that have already been scraped
    """
    scraped_urls: Set[str] = set()

    # 1. SQLite DB
    db_path = DATA_DIR / "jobs.db"
    if db_path.exists():
        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT source_url FROM jobs").fetchall()
            conn.close()
            for (url,) in rows:
                if url:
                    scraped_urls.add(normalize_url(url))
        except Exception as e:
            print(f"  Warning: Could not read SQLite DB: {e}")

    # 2. Active JSON output file
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            for job in jobs:
                url = job.get("url", "")
                if url:
                    scraped_urls.add(normalize_url(url))
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not read {OUTPUT_FILE}: {e}")

    # 3. Legacy fallback files
    for filename in FALLBACK_DEDUP_FILES:
        filepath = DATA_DIR / filename
        if not filepath.exists():
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            for job in jobs:
                url = job.get("url", "")
                if url:
                    scraped_urls.add(normalize_url(url))
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not read {filename}: {e}")

    print(f"[Deduplication] Loaded {len(scraped_urls)} previously scraped URLs")
    return scraped_urls


def normalize_url(url: str) -> str:
    """Normalize URL for deduplication — extracts job ID as the canonical key.

    Both LinkedIn URL formats resolve to the same job ID:
      - Old: /jobs/view/4384037771
      - New: /jobs/view/intern-civil-site-engineering-at-gft-4380391939?position=1&...
    Using job ID eliminates false duplicates from tracking parameters.
    """
    import re

    if not url:
        return ""
    # Extract job ID: handles both URL formats
    m = re.search(r"/jobs/view/[a-zA-Z0-9_-]+-(\d+)(?:\?|$)", url)
    if m:
        return m.group(1)
    # Fallback: strip query string
    return url.split("?")[0] if "?" in url else url


def is_job_already_scraped(job: Dict, scraped_urls: Set[str]) -> bool:
    """Check if a job has already been scraped."""
    url = job.get("url", "")
    if not url:
        return False
    normalized = normalize_url(url)
    return normalized in scraped_urls


def filter_out_scraped_jobs(jobs: List[Dict], scraped_urls: Set[str]) -> List[Dict]:
    """Filter out jobs that have already been scraped."""
    new_jobs = []
    skipped = 0

    for job in jobs:
        if is_job_already_scraped(job, scraped_urls):
            skipped += 1
        else:
            new_jobs.append(job)

    if skipped > 0:
        print(f"  [Deduplication] Skipped {skipped} already scraped jobs")

    return new_jobs


# ============================================================================
# LINKEDIN SCRAPER
# ============================================================================


async def scrape_linkedin_page(page, url: str) -> List[Dict]:
    """Scrape a single LinkedIn page for job listings."""
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    title = await page.title()
    print(f"  Page: {title[:50]}...")

    job_data = await page.evaluate("""() => {
        const results = [];
        const jobCards = document.querySelectorAll('.base-card');

        jobCards.forEach(card => {
            const titleEl = card.querySelector('h3.base-search-card__title');
            const companyEl = card.querySelector('h4.base-search-card__subtitle');
            const metaEl = card.querySelector('.base-search-card__metadata');
            const linkEl = card.querySelector('a.base-card__full-link');

            const title = titleEl ? titleEl.innerText.trim() : '';
            const company = companyEl ? companyEl.innerText.trim() : '';
            const location = metaEl ? metaEl.innerText.trim() : '';
            const href = linkEl ? linkEl.href : '';

            if (title && company) {
                results.push({ title, company, location, url: href });
            }
        });

        return results;
    }""")

    return job_data


async def get_linkedin_job_details(page, job_url: str) -> dict:
    """Get full job description AND real posting date from LinkedIn job detail page.

    Returns:
        dict with keys: description (str), posted_date (str ISO or '')
    """
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        result = await page.evaluate("""() => {
            // Extract description
            const article = document.querySelector('article');
            const description = article ? article.innerText : '';

            // Extract datePosted from JSON-LD
            let postedDate = '';
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const script of scripts) {
                try {
                    const data = JSON.parse(script.textContent);
                    if (data['@type'] === 'JobPosting' && data.datePosted) {
                        postedDate = data.datePosted;
                        break;
                    }
                    if (data['@graph']) {
                        for (const item of data['@graph']) {
                            if (item['@type'] === 'JobPosting' && item.datePosted) {
                                postedDate = item.datePosted;
                                break;
                            }
                        }
                    }
                } catch (e) {}
            }

            // Fallback: parse "X days ago" from DOM
            if (!postedDate) {
                const dateEl = document.querySelector('.jobs-unified-top-card__posted-date');
                if (dateEl) {
                    postedDate = 'RELATIVE:' + dateEl.textContent.trim();
                }
            }

            return {
                description: description.slice(0, 8000),
                postedDate
            };
        }""")

        return {
            "description": result.get("description", "") or "",
            "posted_date": _parse_posted_date_result(result.get("postedDate", "")),
        }
    except Exception as e:
        print(f"    Error getting job details: {e}")
        return {"description": "", "posted_date": ""}


def _parse_posted_date_result(posted_str: str) -> str:
    """Convert LinkedIn date result to ISO date string or ''."""
    if not posted_str:
        return ""
    if posted_str.startswith("RELATIVE:"):
        # Parse "6 days ago" → ISO
        import re
        from datetime import datetime, timedelta

        m = re.search(r"(\d+)?\s*(hour|day|week|month)s?\s*ago", posted_str, re.IGNORECASE)
        if not m:
            return ""
        count_str, unit = m.group(1), m.group(2).lower()
        count = int(count_str) if count_str else 1
        today = datetime.now().replace(hour=0, minute=0, second=0)
        delta_map = {"hour": 0, "day": count, "week": count * 7, "month": count * 30}
        delta = delta_map.get(unit, 0)
        return (today - timedelta(days=delta)).isoformat()
    # Already ISO
    if "T" in posted_str:
        return posted_str[:19] + "00"
    if re.match(r"\d{4}-\d{2}-\d{2}", posted_str):
        return posted_str[:10] + "T00:00:00"
    return ""


async def scrape_linkedin_all(
    keywords: str,
    location: str,
    max_pages: int = 10,
    scraped_urls: Optional[Set[str]] = None,
) -> List[Dict]:
    """Scrape multiple LinkedIn pages.

    Args:
        keywords: Job search keywords
        location: Location to search
        max_pages: Maximum number of pages to scrape
        scraped_urls: Set of already scraped URLs for deduplication.

    Returns:
        List of new job listings (deduplicated)
    """
    all_jobs = []

    if scraped_urls is None:
        scraped_urls = load_scraped_urls()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        encoded_keywords = keywords.replace(" ", "%20")
        encoded_location = location.replace(" ", "%20")
        base_url = (
            f"https://www.linkedin.com/jobs/search/?keywords={encoded_keywords}"
            f"&location={encoded_location}"
            f"&f_TPR={DATE_FILTER_MONTH}"
        )

        for page_num in range(max_pages):
            start = page_num * 25
            url = f"{base_url}&start={start}" if start > 0 else base_url

            print(f"\nScraping LinkedIn page {page_num + 1} (past month)...")
            jobs = await scrape_linkedin_page(page, url)

            if not jobs:
                print(f"  No more jobs found on page {page_num + 1}")
                break

            new_jobs = filter_out_scraped_jobs(jobs, scraped_urls)
            print(f"  Found {len(jobs)} jobs, {len(new_jobs)} new")

            if not new_jobs:
                print(f"  All jobs on this page already scraped, stopping.")
                break

            for job in new_jobs:
                job["source"] = "linkedin"
                job["job_type"] = "Internship"
                normalized = normalize_url(job.get("url", ""))
                scraped_urls.add(normalized)

            all_jobs.extend(new_jobs)

            if page_num == 0 and new_jobs:
                print(f"  Getting full JD and posting date for first job...")
                first_job_url = new_jobs[0].get("url", "")
                if first_job_url:
                    details = await get_linkedin_job_details(page, first_job_url)
                    new_jobs[0]["description"] = details.get("description", "")
                    new_jobs[0]["posted_date"] = details.get("posted_date", "")
                    print(f"  JD length: {len(details.get('description', ''))} chars")
                    print(f"  Posted date: {details.get('posted_date', 'N/A')}")

        await browser.close()

    return all_jobs


# ============================================================================
# MAIN
# ============================================================================


async def main():
    print("=" * 60)
    print("LinkedIn Job Scraper")
    print("Civil & Environmental Engineering Jobs & Internships")
    print("=" * 60)
    print("Date Filter: Past Month (f_TPR=r2592000)")
    print("Deduplication: Enabled")
    print("=" * 60)

    keywords = "civil engineering and environmental engineering jobs in the United States"
    location = "United States"

    print("\n[Init] Loading existing scraped URLs...")
    scraped_urls = load_scraped_urls()

    print("\n### SCRAPING LINKEDIN ###")
    linkedin_jobs = await scrape_linkedin_all(
        keywords, location, max_pages=5, scraped_urls=scraped_urls
    )
    print(f"\nTotal NEW LinkedIn jobs scraped: {len(linkedin_jobs)}")

    if linkedin_jobs:
        existing_linkedin = []
        if OUTPUT_FILE.exists():
            try:
                with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                    existing_linkedin = json.load(f)
            except json.JSONDecodeError:
                existing_linkedin = []

        # Deduplicate by job ID (normalize_url now returns job ID)
        existing_ids = {normalize_url(j.get("url", "")) for j in existing_linkedin}
        truly_new = [
            j for j in linkedin_jobs if normalize_url(j.get("url", "")) not in existing_ids
        ]
        combined_linkedin = existing_linkedin + truly_new

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(combined_linkedin, f, indent=2, ensure_ascii=False)
        print(
            f"  Saved {len(truly_new)} truly new jobs to {OUTPUT_FILE.name} "
            f"(total: {len(combined_linkedin)}, dupes filtered: {len(linkedin_jobs) - len(truly_new)})"
        )

    print(f"\n### SUMMARY ###")
    print(f"Total NEW LinkedIn jobs: {len(linkedin_jobs)}")
    print(f"Total URLs tracked: {len(scraped_urls)}")

    # ── Auto-migrate to SQLite ──────────────────────────────────────────
    if linkedin_jobs and _auto_migrate():
        print("\n[SQLite] Migration complete.")

    print("\nData saved to data/ directory")


def _auto_migrate() -> bool:
    """Run migrate_to_sqlite.py as a subprocess. Returns True on success."""
    import subprocess, sys

    migrate_script = Path(__file__).parent / "migrate_to_sqlite.py"
    if not migrate_script.exists():
        print(f"  [SQLite] migrate_to_sqlite.py not found, skipping auto-migrate")
        return False
    try:
        print(f"\n[SQLite] Running auto-migration...")
        result = subprocess.run(
            [sys.executable, str(migrate_script)], capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            # Print summary lines from migration
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if any(k in line for k in ["Migrated:", "Verification:", "Total jobs", "DB size"]):
                    print(f"  {line}")
            return True
        else:
            print(f"  [SQLite] Migration failed: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"  [SQLite] Migration error: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(main())
