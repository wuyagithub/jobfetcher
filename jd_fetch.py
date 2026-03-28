"""
Batch JD extractor — fetches full job descriptions using XCrawl.

Workflow:
  1. Query SQLite database for jobs with missing JDs
  2. Use XCrawl Scrape API to fetch each LinkedIn job page
  3. Extract JD text from markdown output
  4. Update SQLite database with fetched JDs
  5. Rebuild FTS5 index to sync with updated JDs

Usage:
    python jd_fetch.py                    # Show pending JD count
    python jd_fetch.py --status            # Detailed status + missing list
    python jd_fetch.py --rebuild-fts      # Rebuild FTS5 index only
    python jd_fetch.py --credits           # Check XCrawl credits
    python jd_fetch.py --fetch            # Fetch missing JDs via XCrawl
    python jd_fetch.py --fetch --async   # Use async mode for faster throughput
"""

import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

# ── XCrawl client ──────────────────────────────────────────────────────────────
from xcrawl_client import (
    fetch_jd,
    get_credits,
    rebuild_fts_index,
)

# ── Constants ────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "jobs.db"


# ── Database Helpers ─────────────────────────────────────────────────────────


def get_db_connection():
    """Get SQLite database connection."""
    return sqlite3.connect(DB_PATH)


def get_jobs_with_missing_jd(conn: sqlite3.Connection) -> list[dict]:
    """Get all jobs that are missing JDs from the database."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, job_title, company_name, description_text
        FROM jobs
        WHERE description_text IS NULL OR description_text = ""
    """)
    jobs = []
    for row in cur.fetchall():
        job_id, title, company, desc = row
        numeric_id = extract_numeric_id(job_id)
        jobs.append(
            {
                "id": job_id,
                "numeric_id": numeric_id,
                "title": title,
                "company": company,
                "description_text": desc,
            }
        )
    return jobs


def extract_numeric_id(job_id: str) -> str:
    """Extract numeric ID from LinkedIn URL or return as-is."""
    if not job_id:
        return ""
    match = re.search(r"-(\d{7,})(?:\?|$)", job_id)
    if match:
        return match.group(1)
    return job_id if job_id.isdigit() else ""


def get_unique_missing_job_ids(conn) -> list[str]:
    """Get unique numeric job IDs that are missing JDs."""
    jobs = get_jobs_with_missing_jd(conn)
    unique_ids = list(set(j["numeric_id"] for j in jobs if j["numeric_id"]))
    return unique_ids


def update_jd_in_db(conn: sqlite3.Connection, job_id: str, jd_text: str) -> int:
    """Update JD for a job. Returns number of rows updated."""
    cur = conn.cursor()
    # Match by source_url (full URL) since id column contains full URL, not numeric ID
    cur.execute(
        """
        UPDATE jobs
        SET description_text = ?
        WHERE source_url LIKE ? OR source_url = ?
        """,
        (jd_text, f"%{job_id}%", f"%{job_id}%"),
    )
    conn.commit()
    return cur.rowcount


def get_database_stats(conn: sqlite3.Connection) -> dict:
    """Get database statistics."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM jobs")
    total = cur.fetchone()[0]
    cur.execute(
        'SELECT COUNT(*) FROM jobs WHERE description_text IS NOT NULL AND description_text != ""'
    )
    with_jd = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM jobs_fts")
    fts_count = cur.fetchone()[0]
    return {
        "total_jobs": total,
        "jobs_with_jd": with_jd,
        "jobs_missing_jd": total - with_jd,
        "fts_entries": fts_count,
    }


# ── XCrawl-based JD Fetching ────────────────────────────────────────────────


def fetch_missing_jds(async_mode: bool = False, delay: float = 3.0) -> dict:
    """
    Fetch JDs for all jobs missing them using XCrawl.

    Args:
        async_mode: If True, use async scrape + poll (faster for batch).
        delay: Seconds between requests (rate limiting).

    Returns:
        dict with keys: total, success, failed, skipped
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, source_url, job_title FROM jobs "
        'WHERE description_text IS NULL OR description_text = ""'
    )
    missing_jobs = cur.fetchall()
    conn.close()

    if not missing_jobs:
        print("[JD] No jobs missing JDs")
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    print(f"[JD] Fetching JDs for {len(missing_jobs)} jobs via XCrawl...")

    success = 0
    failed = 0
    skipped = 0

    for job_id, url, title in missing_jobs:
        if not url:
            skipped += 1
            continue

        print(f"  [{job_id}] {title[:50]}...")

        try:
            jd_text = fetch_jd(url)
            if jd_text and len(jd_text) > 100:
                conn2 = get_db_connection()
                rows = update_jd_in_db(conn2, job_id, jd_text)
                conn2.close()
                if rows > 0:
                    print(f"    OK: {len(jd_text)} chars")
                    success += 1
                else:
                    print(f"    WARN: No rows updated")
                    failed += 1
            else:
                print(f"    WARN: JD too short or empty")
                failed += 1
        except Exception as e:
            print(f"    ERR: {e}")
            failed += 1

        # Rate limit
        if delay > 0 and success + failed < len(missing_jobs):
            time.sleep(delay)

    # Rebuild FTS
    if success > 0:
        conn = get_db_connection()
        rebuild_fts_index(conn)
        conn.close()

    return {"total": len(missing_jobs), "success": success, "failed": failed, "skipped": skipped}


# ── Status / Display ─────────────────────────────────────────────────────────


def print_pending_jobs(conn: sqlite3.Connection):
    """Print list of jobs with missing JDs."""
    jobs = get_jobs_with_missing_jd(conn)
    if not jobs:
        print("[JD] All jobs have JDs!")
        return

    print(f"\n[JD] Jobs missing JDs: {len(jobs)}")
    print(f"     Unique LinkedIn IDs: {len(get_unique_missing_job_ids(conn))}")
    print("\n{:<6} {:<45} {:<30}".format("Num", "Title", "Company"))
    print("-" * 85)

    seen = set()
    for i, job in enumerate(jobs, 1):
        key = job["numeric_id"]
        if key in seen:
            continue
        seen.add(key)
        title = (job["title"] or "")[:42]
        company = (job["company"] or "")[:28]
        print(f"{i:<6} {title:<45} {company:<30}")


def print_database_status(conn: sqlite3.Connection):
    """Print detailed database status."""
    stats = get_database_stats(conn)
    print("\n[JD] Database Status")
    print("=" * 40)
    print(f"  Total jobs:           {stats['total_jobs']}")
    print(f"  Jobs with JD:         {stats['jobs_with_jd']}")
    print(f"  Jobs missing JD:      {stats['jobs_missing_jd']}")
    print(f"  FTS5 entries:         {stats['fts_entries']}")
    if stats["total_jobs"] > 0:
        pct = stats["jobs_with_jd"] / stats["total_jobs"] * 100
        print(f"  JD completion:        {pct:.1f}%")
    print()


def print_credits():
    """Print current XCrawl credits."""
    credits = get_credits()
    if credits is not None:
        print(f"\n[JD] XCrawl credits: {credits}")
    else:
        print("\n[JD] Could not fetch credits (check ~/.xcrawl/config.json)")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="JD Extractor via XCrawl")
    parser.add_argument("--status", action="store_true", help="Show database status")
    parser.add_argument("--rebuild-fts", action="store_true", help="Rebuild FTS5 index")
    parser.add_argument("--credits", action="store_true", help="Show XCrawl credits")
    parser.add_argument("--fetch", action="store_true", help="Fetch missing JDs via XCrawl")
    parser.add_argument(
        "--async",
        dest="async_mode",
        action="store_true",
        help="Use async scrape mode (faster for batch)",
    )
    parser.add_argument(
        "--delay", type=float, default=3.0, help="Seconds between requests (default: 3.0)"
    )
    args = parser.parse_args()

    # Default: show status
    if not any([args.status, args.rebuild_fts, args.credits, args.fetch]):
        conn = get_db_connection()
        print_database_status(conn)
        stats = get_database_stats(conn)
        if stats["jobs_missing_jd"] > 0:
            print_pending_jobs(conn)
            print("\n[JD] Run: python jd_fetch.py --fetch  to fill missing JDs")
        conn.close()
        return

    if args.status:
        conn = get_db_connection()
        print_database_status(conn)
        print_pending_jobs(conn)
        conn.close()

    if args.rebuild_fts:
        conn = get_db_connection()
        print("[JD] Rebuilding FTS5 index...")
        rebuild_fts_index(conn)
        conn.close()

    if args.credits:
        print_credits()

    if args.fetch:
        print("\n[JD] Starting XCrawl JD fetch...")
        result = fetch_missing_jds(async_mode=args.async_mode, delay=args.delay)
        print(
            f"\n[JD] Done: {result['success']}/{result['total']} fetched, "
            f"{result['failed']} failed, {result['skipped']} skipped"
        )


if __name__ == "__main__":
    main()
