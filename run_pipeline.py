"""
run_pipeline.py — Master orchestrator for the full LinkedIn job scraping pipeline.

Runs in sequence:
  1. scrape_all_jobs  → extracts job listings from LinkedIn (Playwright MCP)
  2. jd_fetch         → fills job descriptions via MCP webfetch (manual step)
  3. migrate_to_sqlite → converts JSON → SQLite with FTS index

Usage:
  python run_pipeline.py              # Full pipeline (steps 1 + 3)
  python run_pipeline.py --scrape     # Step 1 only (Playwright MCP required)
  python run_pipeline.py --migrate    # Step 3 only (JSON → SQLite)
  python run_pipeline.py --all        # Full pipeline including JD fetch guidance
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"

TODAY = datetime.now().strftime("%Y-%m-%d")


def run_step(name: str, script: Path, *args) -> bool:
    """Run a Python script as a subprocess. Returns True on success."""
    print(f"\n{'=' * 60}")
    print(f"  STEP: {name}")
    print(f"{'=' * 60}")
    try:
        result = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=str(SCRIPT_DIR),
            capture_output=False,
            timeout=300,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  ERROR: {name} timed out")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def check_data_files():
    """Verify the JSON output file exists and has content."""
    output = DATA_DIR / "linkedin_jobs_20260325_new.json"
    if not output.exists():
        print(f"WARNING: {output} not found.")
        return False
    try:
        import json

        with open(output, encoding="utf-8") as f:
            jobs = json.load(f)
        print(f"JSON file: {output}")
        print(f"  Jobs: {len(jobs)}")
        pending = sum(
            1
            for j in jobs
            if "not yet extracted" in j.get("description", "").lower()
            or "jd pending" in j.get("description", "").lower()
        )
        print(f"  JDs pending: {pending}")
        print(f"  JDs filled:  {len(jobs) - pending}")
        return True
    except Exception as e:
        print(f"ERROR reading JSON: {e}")
        return False


def print_migration_summary():
    """Print SQLite DB summary."""
    db_path = DATA_DIR / "jobs.db"
    if not db_path.exists():
        print("SQLite DB not found.")
        return
    import sqlite3

    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    iso = conn.execute("SELECT COUNT(*) FROM jobs WHERE posted_date LIKE '%T%'").fetchone()[0]
    range_row = conn.execute(
        "SELECT MIN(posted_date), MAX(posted_date) FROM jobs WHERE posted_date LIKE '%T%'"
    ).fetchone()
    size_kb = db_path.stat().st_size / 1024
    print(f"\n{'=' * 60}")
    print(f"  SQLite DB Summary")
    print(f"{'=' * 60}")
    print(f"  DB file:       {db_path}")
    print(f"  Total jobs:   {total}")
    print(f"  ISO dates:    {iso}/{total}")
    print(
        f"  Date range:   {range_row[0][:10] if range_row[0] else 'N/A'} → {range_row[1][:10] if range_row[1] else 'N/A'}"
    )
    print(f"  DB size:      {size_kb:.0f} KB")

    print(f"\n  Top companies:")
    for row in conn.execute(
        "SELECT company_name, COUNT(*) FROM jobs GROUP BY company_name ORDER BY COUNT(*) DESC LIMIT 5"
    ):
        print(f"    {row[0]}: {row[1]}")

    print(f"\n  Top states:")
    for row in conn.execute(
        "SELECT state, COUNT(*) FROM jobs WHERE state != '' GROUP BY state ORDER BY COUNT(*) DESC LIMIT 5"
    ):
        print(f"    {row[0]}: {row[1]}")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="LinkedIn Job Scraper Pipeline")
    parser.add_argument(
        "--step",
        choices=["scrape", "migrate", "all"],
        default="all",
        help="Which step to run (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without executing",
    )
    args = parser.parse_args()

    print(f"""
{"=" * 60}
  LinkedIn Job Scraper Pipeline
  Date: {TODAY}
  Mode: {args.step}
{"=" * 60}
""")

    if args.step in ("scrape", "all"):
        ok = check_data_files()
        if not ok:
            print("\nProceeding to scrape new jobs...")

        scrape_ok = run_step(
            "Scrape LinkedIn Job Listings",
            SCRIPT_DIR / "scrape_all_jobs.py",
        )

        if not scrape_ok:
            print("\nScrape step failed. Check Playwright MCP connection.")
            sys.exit(1)

        # After scrape, migration runs automatically inside scrape_all_jobs.py
        # Re-check data
        check_data_files()

    if args.step == "migrate" or (args.step == "all"):
        # Migration is also called inside scrape_all_jobs.py and jd_fetch.py
        # This is for manual trigger or re-run
        ok = check_data_files()
        if not ok:
            print("\nNo JSON data found. Run --step scrape first.")
            sys.exit(1)

        migrate_ok = run_step(
            "Migrate JSON → SQLite",
            SCRIPT_DIR / "migrate_to_sqlite.py",
        )

        if migrate_ok:
            print_migration_summary()
        else:
            print("\nMigration failed.")
            sys.exit(1)

    if args.step == "all":
        # Check for pending JDs
        print(f"\n{'=' * 60}")
        print(f"  Post-Scrape Checklist")
        print(f"{'=' * 60}")
        output = DATA_DIR / "linkedin_jobs_20260325_new.json"
        if output.exists():
            import json

            with open(output, encoding="utf-8") as f:
                jobs = json.load(f)
            pending = [
                (j["url"].split("/")[-1], j.get("title", "")[:50])
                for j in jobs
                if "not yet extracted" in j.get("description", "").lower()
                or "jd pending" in j.get("description", "").lower()
            ]
            if pending:
                print(f"\n  {len(pending)} jobs still need JDs:")
                for job_id, title in pending[:10]:
                    print(f"    [{job_id}] {title}")
                if len(pending) > 10:
                    print(f"    ... and {len(pending) - 10} more")
                print(f"""
  To fill JDs:
    1. Use MCP webfetch on each job URL
    2. Extract "Job Description" section
    3. Update the JSON file
    4. Run: python run_pipeline.py --step migrate
                """)
            else:
                print(f"\n  All JDs filled! ✅")

    print(f"\n{'=' * 60}")
    print(f"  Pipeline complete")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
