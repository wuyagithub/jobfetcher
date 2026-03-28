"""
Migration script: flat JSON → structured SQLite database.

Reads the legacy flat JSON format from linkedin_jobs_YYYYMMDD_new.json
and imports it into SQLite using the proper JobListing model schema.
Also creates an FTS5 virtual table for full-text search.
"""

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

JSON_PATH = Path(__file__).parent / "data" / "linkedin_jobs_20260325_new.json"
DB_PATH = Path(__file__).parent / "data" / "jobs.db"

# ── Helpers ───────────────────────────────────────────────────────────────────

# Matches both URL formats:
#   - Old: /jobs/view/4384037771
#   - New: /jobs/view/intern-civil-site-engineering-at-gft-4380391939?position=...
LINKEDIN_ID_RE = re.compile(r"/jobs/view/[a-zA-Z0-9_-]+-(\d+)(?:\?|$)")


def extract_linkedin_id(url: str) -> str:
    m = LINKEDIN_ID_RE.search(url)
    return m.group(1) if m else url


def parse_location(location: str) -> tuple[str, str, str]:
    """Parse 'City, ST (On-site)' into (city, state, location_type)."""
    location_type = "onsite"
    if "(Remote)" in location:
        location_type = "remote"
    elif "(Hybrid)" in location:
        location_type = "hybrid"
    elif "(On-site)" in location:
        location_type = "onsite"

    # Strip tags
    loc_clean = re.sub(r"\s*\([^)]+\)\s*", "", location).strip()

    city, state = "", ""
    if "," in loc_clean:
        parts = loc_clean.split(",", 1)
        city = parts[0].strip()
        state = parts[1].strip()
    else:
        # Try to extract state abbreviation (2 capital letters)
        m = re.search(r"\b([A-Z]{2})\b", loc_clean)
        if m:
            state = m.group(1)
            city = loc_clean[: m.start()].strip()
        else:
            city = loc_clean

    return city, state, location_type


def parse_employment_type(job_type: str) -> str:
    mapping = {
        "Internship": "INTERNSHIP",
        "Co-op": "TEMPORARY",
        "Full-time": "FULL_TIME",
        "Part-time": "PART_TIME",
    }
    return mapping.get(job_type.strip(), "FULL_TIME")


def parse_posted_date(posted: str) -> str:
    """Normalize relative dates to ISO format (using today = 2026-03-25).

    Handles:
      - Relative: "1 week ago", "6 days ago", "3 months ago"
      - ISO:       "2026-03-18T00:00:00" (already converted)
      - Empty:     ""
    """
    if not posted or posted.strip() == "":
        return ""

    # Fast path: if it looks like an ISO date, return as-is
    # (format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
    if re.match(r"\d{4}-\d{2}-\d{2}", posted.strip()):
        return posted.strip()

    posted_lower = posted.strip().lower()
    today = datetime(2026, 3, 25)

    if "hour" in posted_lower or "just" in posted_lower:
        return today.replace(hour=0, minute=0, second=0).isoformat()

    if "day" in posted_lower:
        m = re.search(r"(\d+)", posted_lower)
        days = int(m.group(1)) if m else 1
        return (today - timedelta(days=days)).replace(hour=0, minute=0, second=0).isoformat()

    if "week" in posted_lower:
        m = re.search(r"(\d+)", posted_lower)
        weeks = int(m.group(1)) if m else 1
        return (today - timedelta(weeks=weeks)).replace(hour=0, minute=0, second=0).isoformat()

    if "month" in posted_lower:
        m = re.search(r"(\d+)", posted_lower)
        months = int(m.group(1)) if m else 1
        return (today - timedelta(days=months * 30)).replace(hour=0, minute=0, second=0).isoformat()

    return today.replace(hour=0, minute=0, second=0).isoformat()
    if "day" in posted:
        m = re.search(r"(\d+)", posted)
        days = int(m.group(1)) if m else 1
        return (today.replace(hour=0, minute=0, second=0)).isoformat()
    if "week" in posted:
        m = re.search(r"(\d+)", posted)
        weeks = int(m.group(1)) if m else 1
        return (today.replace(hour=0, minute=0, second=0)).isoformat()
    if "month" in posted:
        m = re.search(r"(\d+)", posted)
        months = int(m.group(1)) if m else 1
        return (today.replace(hour=0, minute=0, second=0)).isoformat()

    # Try parsing as date
    for fmt in ["%Y-%m-%d", "%b %d, %Y"]:
        try:
            return datetime.strptime(posted, fmt).isoformat()
        except ValueError:
            pass
    return today.isoformat()


# ── Schema ───────────────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'linkedin',
    source_url      TEXT UNIQUE NOT NULL,
    job_title       TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    company_url     TEXT,
    location_type   TEXT,
    city            TEXT,
    state           TEXT,
    country         TEXT DEFAULT 'US',
    postal_code     TEXT,
    employment_type TEXT,
    salary_currency TEXT,
    salary_min      REAL,
    salary_max      REAL,
    salary_interval TEXT,
    description_text TEXT,
    description_html TEXT,
    requirements_json TEXT,
    posted_date     TEXT,
    expiry_date     TEXT,
    scraped_at      TEXT NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_source      ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_title       ON jobs(job_title);
CREATE INDEX IF NOT EXISTS idx_jobs_state        ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_company      ON jobs(company_name);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_date  ON jobs(posted_date);
CREATE INDEX IF NOT EXISTS idx_jobs_employment   ON jobs(employment_type);
"""

CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    job_title,
    company_name,
    city,
    state,
    description_text,
    content='jobs',
    content_rowid='rowid'
);
"""

INSERT_FTS_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS jobs_ai AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, job_title, company_name, city, state, description_text)
    VALUES (NEW.rowid, NEW.job_title, NEW.company_name, NEW.city, NEW.state, NEW.description_text);
END;

CREATE TRIGGER IF NOT EXISTS jobs_ad AFTER DELETE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, job_title, company_name, city, state, description_text)
    VALUES ('delete', OLD.rowid, OLD.job_title, OLD.company_name, OLD.city, OLD.state, OLD.description_text);
END;

CREATE TRIGGER IF NOT EXISTS jobs_au AFTER UPDATE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, job_title, company_name, city, state, description_text)
    VALUES ('delete', OLD.rowid, OLD.job_title, OLD.company_name, OLD.city, OLD.state, OLD.description_text);
    INSERT INTO jobs_fts(rowid, job_title, company_name, city, state, description_text)
    VALUES (NEW.rowid, NEW.job_title, NEW.company_name, NEW.city, NEW.state, NEW.description_text);
END;
"""

INSERT_JOB_SQL = """
INSERT OR REPLACE INTO jobs (
    id, source, source_url, job_title,
    company_name, company_url,
    location_type, city, state, country, postal_code,
    employment_type,
    salary_currency, salary_min, salary_max, salary_interval,
    description_text, description_html,
    requirements_json,
    posted_date, expiry_date,
    scraped_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

UPSERT_FTS_SQL = """
INSERT INTO jobs_fts(rowid, job_title, company_name, city, state, description_text)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(rowid) DO UPDATE SET
    job_title = excluded.job_title,
    company_name = excluded.company_name,
    city = excluded.city,
    state = excluded.state,
    description_text = excluded.description_text
"""


# ── Main ──────────────────────────────────────────────────────────────────────


def migrate():
    print(f"Reading: {JSON_PATH}")
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Handle both formats: list or dict with 'jobs' key
    if isinstance(data, list):
        flat_jobs = data
    else:
        flat_jobs = data.get("jobs", [])
        print(f"  Metadata: {data.get('total_found', len(flat_jobs))} total scraped")

    print(f"Total jobs to migrate: {len(flat_jobs)}")

    # Remove old DB to start fresh
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed old DB: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # Create schema
    conn.executescript(CREATE_TABLES_SQL)
    conn.executescript(CREATE_FTS_SQL)

    now_iso = datetime.now().isoformat()
    migrated = 0
    skipped = 0

    for job in flat_jobs:
        url = job.get("url", "")
        job_id = extract_linkedin_id(url)

        if not job_id:
            print(f"  WARNING: Could not extract ID from URL {url}, skipping")
            skipped += 1
            continue

        city, state, loc_type = parse_location(job.get("location", ""))
        emp_type = parse_employment_type(job.get("job_type", ""))
        posted = parse_posted_date(job.get("posted_date", ""))

        # Try to extract salary from description
        salary_min = salary_max = salary_currency = salary_interval = None
        desc = job.get("description", "")
        salary_m = re.search(
            r"\$([\d,]+(?:\.\d{2})?)\s*(?:[-–to]+\s*\$?([\d,]+(?:\.\d{2})?))?\s*(?:/hour|/year|/month|hour|year|per hour|per year|h/yr)?",
            desc,
            re.IGNORECASE,
        )
        if salary_m:
            try:
                salary_min = float(salary_m.group(1).replace(",", ""))
                if salary_m.group(2):
                    salary_max = float(salary_m.group(2).replace(",", ""))
                # Determine interval
                if (
                    "/hour" in desc[salary_m.start() : salary_m.end() + 10].lower()
                    or "per hour" in desc[salary_m.start() : salary_m.end() + 10].lower()
                ):
                    salary_interval = "HOUR"
                elif (
                    "/year" in desc[salary_m.start() : salary_m.end() + 10].lower()
                    or "per year" in desc[salary_m.start() : salary_m.end() + 10].lower()
                ):
                    salary_interval = "YEAR"
                else:
                    salary_interval = "HOUR"  # Most internships are hourly
                salary_currency = "USD"
            except (ValueError, AttributeError):
                pass

        row = (
            job_id,
            "linkedin",
            url,
            job.get("title", "").strip(),
            job.get("company", "").strip(),
            None,  # company_url
            loc_type,
            city,
            state,
            "US",
            None,  # postal_code
            emp_type,
            salary_currency,
            salary_min,
            salary_max,
            salary_interval,
            desc.strip() if desc else None,
            None,  # description_html
            None,  # requirements_json
            posted,
            None,  # expiry_date
            now_iso,
        )

        conn.execute(INSERT_JOB_SQL, row)
        migrated += 1

    conn.commit()
    print(f"Migrated: {migrated} jobs, skipped: {skipped}")

    # Rebuild FTS index
    print("Rebuilding FTS index...")
    conn.execute(
        "INSERT INTO jobs_fts(rowid, job_title, company_name, city, state, description_text) "
        "SELECT rowid, job_title, company_name, city, state, description_text FROM jobs"
    )
    conn.commit()

    # Create FTS triggers
    try:
        conn.executescript(
            UPSERT_FTS_SQL.replace(
                "ON CONFLICT(rowid) DO UPDATE SET", "ON CONFLICT(rowid) DO UPDATE SET"
            )
        )
    except sqlite3.OperationalError:
        pass  # Triggers may already exist

    # Verify
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM jobs_fts").fetchone()[0]
    print(f"\nVerification:")
    print(f"  jobs table: {total} rows")
    print(f"  jobs_fts:   {fts_count} rows")
    print(f"  DB path:    {DB_PATH}")
    print(f"  DB size:    {DB_PATH.stat().st_size / 1024:.1f} KB")

    # Sample queries
    print("\nSample queries:")

    # Top companies
    print("\n  Top 10 companies:")
    for row in conn.execute(
        "SELECT company_name, COUNT(*) as cnt FROM jobs GROUP BY company_name ORDER BY cnt DESC LIMIT 10"
    ):
        print(f"    {row[0]}: {row[1]}")

    # Top states
    print("\n  Top 10 states:")
    for row in conn.execute(
        "SELECT state, COUNT(*) as cnt FROM jobs WHERE state != '' GROUP BY state ORDER BY cnt DESC LIMIT 10"
    ):
        print(f"    {row[0]}: {row[1]}")

    # Employment types
    print("\n  Employment types:")
    for row in conn.execute("SELECT employment_type, COUNT(*) FROM jobs GROUP BY employment_type"):
        print(f"    {row[0]}: {row[1]}")

    # FTS test
    print("\n  FTS test 'civil engineering intern':")
    for row in conn.execute(
        """
        SELECT job_title, company_name, state
        FROM jobs
        WHERE rowid IN (
            SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH 'civil AND engineering AND intern')
        LIMIT 5
    """
    ):
        print(f"    {row[0]} @ {row[1]} ({row[2]})")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    migrate()
