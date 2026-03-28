"""
LinkedIn job scraper using opencli for data collection.

Features:
- Uses opencli linkedin search for job listings
- Deduplication: skips already scraped jobs by URL
- Output: JSON file compatible with migrate_to_sqlite.py
- JD fetching handled separately by jd_fetch.py (via XCrawl)
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set


# ============================================================================
# CONSTANTS
# ============================================================================

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

# Default search parameters
DEFAULT_KEYWORDS = "civil engineer OR environmental engineer"
DEFAULT_LOCATION = "United States"


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
# OPENCLI LINKEDIN SCRAPER
# ============================================================================


def call_opencli_linkedin_search(
    keywords: str,
    location: str,
    max_results: int = 100,
    date_posted: str = "week",
) -> List[Dict]:
    """
    Call opencli linkedin search and return job listings.

    Args:
        keywords: Job search keywords
        location: Location to search
        max_results: Maximum number of results to return (max 100 per call)
        date_posted: Filter by date posted (any, 24h, week, month)

    Returns:
        List of job dictionaries in migrate-compatible format
    """
    import platform

    cmd = [
        "opencli",
        "linkedin",
        "search",
        keywords,
        "--location",
        location,
        "--limit",
        str(max_results),
        "--date-posted",
        date_posted,
        "-f",
        "json",
    ]

    print(f"  Running: {' '.join(cmd)}")

    # On Windows, subprocess needs shell=True or .cmd extension
    use_shell = platform.system() == "Windows"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
            shell=use_shell,
        )

        if result.returncode != 0:
            print(f"  opencli error: {result.stderr[:300]}")
            return []

        # Parse JSON output
        output = result.stdout.strip()
        if not output:
            print("  opencli returned empty output")
            return []

        try:
            jobs = json.loads(output)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error: {e}, output: {output[:200]}")
            return []

        if not isinstance(jobs, list):
            print(f"  Expected list, got {type(jobs)}")
            return []

        # Transform opencli format to migrate-compatible format
        transformed = []
        for job in jobs:
            transformed_job = {
                "url": job.get("url", ""),
                "title": job.get("title", "").strip(),
                "company": job.get("company", "").strip(),
                "location": job.get("location", ""),
                "job_type": "Full-time",  # opencli doesn't provide this
                "posted_date": job.get("listed", ""),  # 'listed' -> 'posted_date'
                "description": "",  # JDs fetched separately via XCrawl
            }
            transformed.append(transformed_job)

        print(f"  Retrieved {len(transformed)} jobs from opencli")
        return transformed

    except subprocess.TimeoutExpired:
        print("  opencli timed out")
        return []
    except Exception as e:
        print(f"  Error calling opencli: {e}")
        return []


def scrape_linkedin_all(
    keywords: str,
    location: str,
    max_results: int = 100,
    scraped_urls: Optional[Set[str]] = None,
) -> List[Dict]:
    """
    Scrape LinkedIn jobs using opencli.

    Args:
        keywords: Job search keywords
        location: Location to search
        max_results: Maximum number of results to return
        scraped_urls: Set of already scraped URLs for deduplication.

    Returns:
        List of new job listings (deduplicated)
    """
    if scraped_urls is None:
        scraped_urls = load_scraped_urls()

    print(f"\n### SCRAPING LINKEDIN VIA OPENCLI ###")
    print(f"Keywords: {keywords}")
    print(f"Location: {location}")
    print(f"Max results: {max_results}")

    # Call opencli to get job listings
    all_jobs = call_opencli_linkedin_search(
        keywords=keywords,
        location=location,
        max_results=max_results,
        date_posted="week",  # Past week for fresh data
    )

    if not all_jobs:
        print("  No jobs retrieved from opencli")
        return []

    # Filter out already scraped jobs
    new_jobs = filter_out_scraped_jobs(all_jobs, scraped_urls)
    print(f"  Found {len(all_jobs)} jobs, {len(new_jobs)} new")

    if not new_jobs:
        print("  All jobs already scraped")
        return []

    # Mark as source=linkedin and add to scraped set
    for job in new_jobs:
        job["source"] = "linkedin"
        normalized = normalize_url(job.get("url", ""))
        scraped_urls.add(normalized)

    return new_jobs


# ============================================================================
# MAIN
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="LinkedIn Job Scraper via opencli")
    parser.add_argument("--keywords", type=str, default=DEFAULT_KEYWORDS, help="Search keywords")
    parser.add_argument("--location", type=str, default=DEFAULT_LOCATION, help="Search location")
    parser.add_argument(
        "--max-results", type=int, default=100, help="Max results per search (default: 100)"
    )
    parser.add_argument(
        "--pages", type=int, default=1, help="Number of search iterations (default: 1)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LinkedIn Job Scraper (opencli-based)")
    print("Civil & Environmental Engineering Jobs")
    print("=" * 60)
    print(f"Keywords: {args.keywords}")
    print(f"Location: {args.location}")
    print(f"Max results: {args.max_results}")
    print(f"Iterations: {args.pages}")
    print("=" * 60)

    print("\n[Init] Loading existing scraped URLs...")
    scraped_urls = load_scraped_urls()

    all_linkedin_jobs = []
    for page in range(args.pages):
        if args.pages > 1:
            print(f"\n--- Iteration {page + 1}/{args.pages} ---")

        jobs = scrape_linkedin_all(
            keywords=args.keywords,
            location=args.location,
            max_results=args.max_results,
            scraped_urls=scraped_urls,
        )
        all_linkedin_jobs.extend(jobs)

        # Delay between iterations
        if page < args.pages - 1 and jobs:
            delay = 5.0
            print(f"  [Delay] Waiting {delay}s before next iteration...")
            time.sleep(delay)

    print(f"\n### SUMMARY ###")
    print(f"Total NEW LinkedIn jobs: {len(all_linkedin_jobs)}")
    print(f"Total URLs tracked: {len(scraped_urls)}")

    # Save to JSON
    if all_linkedin_jobs:
        existing_linkedin = []
        if OUTPUT_FILE.exists():
            try:
                with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                    existing_linkedin = json.load(f)
            except json.JSONDecodeError:
                existing_linkedin = []

        # Deduplicate by job ID
        existing_ids = {normalize_url(j.get("url", "")) for j in existing_linkedin}
        truly_new = [
            j for j in all_linkedin_jobs if normalize_url(j.get("url", "")) not in existing_ids
        ]
        combined_linkedin = existing_linkedin + truly_new

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(combined_linkedin, f, indent=2, ensure_ascii=False)
        print(
            f"  Saved {len(truly_new)} truly new jobs to {OUTPUT_FILE.name} "
            f"(total: {len(combined_linkedin)}, dupes filtered: {len(all_linkedin_jobs) - len(truly_new)})"
        )

        # ── Auto-migrate to SQLite ──────────────────────────────────────────
        if _auto_migrate():
            print("\n[SQLite] Migration complete.")

    print("\nData saved to data/ directory")
    print("\nNext steps:")
    print("  python jd_fetch.py --status   # Check JD status")
    print("  python jd_fetch.py --fetch    # Fetch missing JDs via XCrawl")


def _auto_migrate() -> bool:
    """Run migrate_to_sqlite.py as a subprocess. Returns True on success."""
    import subprocess as _subprocess

    migrate_script = Path(__file__).parent / "migrate_to_sqlite.py"
    if not migrate_script.exists():
        print(f"  [SQLite] migrate_to_sqlite.py not found, skipping auto-migrate")
        return False
    try:
        print(f"\n[SQLite] Running auto-migration...")
        result = _subprocess.run(
            [sys.executable, str(migrate_script)],
            capture_output=True,
            text=True,
            timeout=60,
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
    main()
