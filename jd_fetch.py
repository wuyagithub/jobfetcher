"""
Batch JD extractor — fetches full job descriptions for pending jobs.

After all pending JDs are filled, automatically runs migrate_to_sqlite.py
to push updated data into the SQLite database.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = DATA_DIR / "linkedin_jobs_20260325_new.json"


# ── JD extraction ──────────────────────────────────────────────────────


def extract_jd_from_webfetch_text(text: str) -> str | None:
    """Extract JD section from raw webfetch text."""
    if not text:
        return None

    for marker in ["Job Description", "About the job", "About this job"]:
        idx = text.find(marker)
        if idx >= 0:
            section = text[idx:]
            for end in [
                "Similar jobs",
                "Referrals increase",
                "Get notified",
                "Show more",
                "Show less",
                "Seniority level",
                "Job function",
                "Industries",
                "\n\n\n",
            ]:
                pos = section.find(end)
                if 0 < pos < len(section):
                    section = section[:pos]
                    break
            section = re.sub(r"\s+", " ", section)
            section = re.sub(r"\n+", "\n", section)
            section = section.replace("Job Description", "", 1).strip()
            return section if len(section) > 100 else None
    return None


# ── Auto-migrate ──────────────────────────────────────────────────────


def _auto_migrate() -> bool:
    """Run migrate_to_sqlite.py as a subprocess. Returns True on success."""
    migrate_script = Path(__file__).parent / "migrate_to_sqlite.py"
    if not migrate_script.exists():
        print("[SQLite] migrate_to_sqlite.py not found, skipping.")
        return False
    try:
        print("\n[SQLite] Running auto-migration...")
        result = subprocess.run(
            [sys.executable, str(migrate_script)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if any(
                    k in line
                    for k in ["Migrated:", "Verification:", "Total jobs", "DB size", "jobs table"]
                ):
                    print(f"  {line}")
            return True
        else:
            print(f"  [SQLite] Migration failed: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"  [SQLite] Migration error: {e}")
        return False


# ── Main ───────────────────────────────────────────────────────────────


def main():
    if not OUTPUT_FILE.exists():
        print(f"ERROR: {OUTPUT_FILE} not found. Run scrape_all_jobs.py first.")
        return

    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    pending = [
        (i, j)
        for i, j in enumerate(jobs)
        if "not yet extracted" in j.get("description", "").lower()
        or "jd pending" in j.get("description", "").lower()
    ]
    print(f"Total jobs: {len(jobs)}, Pending JDs: {len(pending)}")

    if not pending:
        print("No pending JDs. Running migration...")
        _auto_migrate()
        return

    print("""
NOTE: This script requires the MCP webfetch tool to fill JDs.
Run it interactively via the OpenCode MCP client.
After all JDs are filled, run: python jd_fetch.py --migrate
Or run migrate_to_sqlite.py manually: python migrate_to_sqlite.py
""")

    updated = 0
    for idx, job in pending:
        url = job.get("url", "")
        title = job.get("title", "")[:50]
        if not url:
            continue
        print(f"[{idx}] {title}")
        print(f"    URL: {url}")
        print(f"    Action: Use MCP webfetch tool to fetch JD")
        # JD filling is done externally via MCP — mark placeholder
        updated += 1

    print(f"\n{updated} jobs need JD fetching via MCP webfetch.")
    print("After filling JDs, run: python jd_fetch.py --migrate")


if __name__ == "__main__":
    migrate_only = len(sys.argv) > 1 and sys.argv[1] == "--migrate"
    if migrate_only:
        _auto_migrate()
    else:
        main()
