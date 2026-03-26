# JobFetcher - LinkedIn Civil/Environmental Engineering Internship Scraper

Scrapes LinkedIn job listings for civil and environmental engineering internships in the United States using Playwright MCP (browser automation with authenticated session).

## Workflow

```
python run_pipeline.py --step all        # Full pipeline (recommended)
python run_pipeline.py --step scrape     # Step 1: scrape only
python run_pipeline.py --step migrate    # Step 3: migrate JSON → SQLite

# Inside --step all:
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Scrape (scrape_all_jobs.py)                            │
│  - Uses Playwright MCP to browse LinkedIn search results         │
│  - Search: "civil engineering and environmental engineering     │
│    intern" in "United States" with f_TPR=r2592000 (past month) │
│  - Extracts: title, company, location, URL, posted_date         │
│    (real ISO date from JSON-LD datePosted field)               │
│  - Handles pagination (22 pages, 25 jobs each)                  │
│  - Deduplicates against SQLite DB + active JSON file           │
│  - Output: data/linkedin_jobs_20260325_new.json                │
│  - ✅ Auto-migrates to SQLite on completion                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Fill JDs (MCP webfetch — manual or scripted)           │
│  - Uses webfetch tool to pull JD text from LinkedIn job URLs   │
│  - Parses "Job Description" / "About the job" section         │
│  - Truncates at "Seniority level", "Similar jobs", "Referrals" │
│  - Updates description field in JSON in-place                   │
│  - Fallback: jd_fallback.py / jd_fallback2.py                  │
│  - After all JDs filled: python jd_fetch.py --migrate         │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (after all JDs filled)
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Migrate to SQLite (migrate_to_sqlite.py)              │
│  - Auto-runs after scrape_all_jobs.py completes                 │
│  - Transforms flat JSON → structured SQLite schema              │
│  - Auto-parses: city/state, employment_type, salary, dates     │
│  - Creates FTS5 full-text search index                          │
│  - Output: data/jobs.db (SQLite)                               │
└─────────────────────────────────────────────────────────────────┘
```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Scrape all job listings (scrape_all_jobs.py)           │
│  - Uses Playwright MCP to browse LinkedIn search results        │
│  - Search: "civil engineering and environmental engineering     │
│    intern" in "United States" with f_TPR=r2592000 (past month)│
│  - Extracts: title, company, location, URL, posted_date         │
│    (real ISO date from JSON-LD datePosted field)                │
│  - Handles pagination (22 pages, 25 jobs each)                  │
│  - Deduplicates by job ID                                        │
│  - Output: data/linkedin_jobs_YYYYMMDD.json                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Fetch job descriptions (jd_fetch.py)                    │
│  - Uses webfetch tool to pull JD text from LinkedIn job URLs   │
│  - Parses "Job Description" / "About the job" section         │
│  - Truncates at "Seniority level", "Similar jobs", "Referrals" │
│  - Updates description field in JSON in-place                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (if blocked)
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2b: Fallback (jd_fallback.py / jd_fallback2.py)           │
│  - Attempt alternative parsing strategies                        │
│  - Google site: search fallback (if webfetch is blocked)        │
│  - Company careers page direct search                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Batch fill remaining JDs (update_jds*.py)              │
│  - For each remaining pending job:                               │
│    1. webfetch LinkedIn job URL directly                        │
│    2. Parse JD text from response                               │
│    3. Write update script with JD text                           │
│    4. Run script to update JSON in-place                         │
│  - Repeat until 0 pending                                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: Migrate to SQLite (migrate_to_sqlite.py)               │
│  - Transforms flat JSON → structured SQLite schema               │
│  - Auto-parses: city/state, employment_type, salary, dates     │
│    (handles both ISO dates and relative "X days ago" dates)   │
│  - Creates FTS5 full-text search index                          │
│  - Output: data/jobs.db (SQLite)                               │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure

```
jobfetcher/
├── README.md                  # This file
├── requirements.txt           # Python dependencies
├── pyproject.toml            # Project config
├── run_pipeline.py           # ✅ Master orchestrator (use this!)
├── scrape_all_jobs.py        # Step 1: LinkedIn scraper (Playwright MCP)
├── jd_fetch.py               # Step 2: JD filler + auto-migrate
├── jd_fallback.py            # Step 2b: Fallback JD strategies
├── jd_fallback2.py           # Step 2b: Additional fallback strategies
├── backfill_dates.py         # Backfill real posting dates from LinkedIn
├── migrate_to_sqlite.py      # JSON → SQLite migration + FTS (auto-called)
├── playwright_extractor.py   # Playwright browser utilities
├── src/                      # Original jobfetcher package
│   └── jobfetcher/
│       ├── api/              # FastAPI REST API
│       ├── cli/              # Command-line interface
│       ├── models/           # Data models (JobListing, etc.)
│       ├── scrapers/         # Platform scrapers (LinkedIn, etc.)
│       └── storage/          # SQLite, JSON, CSV backends
└── data/
    ├── jobs.db               # ✅ SQLite database (persistent storage)
    └── linkedin_jobs_20260325_new.json  # JSON source (fed to SQLite)
```

## SQLite Database Schema

```sql
-- Main table
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'linkedin',
    source_url      TEXT UNIQUE NOT NULL,
    job_title       TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    company_url     TEXT,
    location_type   TEXT,         -- 'onsite', 'remote', 'hybrid'
    city            TEXT,
    state           TEXT,         -- 2-letter state abbr, e.g. 'TX'
    country         TEXT DEFAULT 'US',
    postal_code     TEXT,
    employment_type TEXT,         -- 'INTERNSHIP', 'FULL_TIME', etc.
    salary_currency TEXT,
    salary_min      REAL,
    salary_max      REAL,
    salary_interval TEXT,        -- 'HOUR', 'YEAR', etc.
    description_text TEXT,
    description_html TEXT,
    requirements_json TEXT,
    posted_date     TEXT,         -- ISO date string
    expiry_date     TEXT,
    scraped_at      TEXT NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_jobs_source      ON jobs(source);
CREATE INDEX idx_jobs_title       ON jobs(job_title);
CREATE INDEX idx_jobs_state        ON jobs(state);
CREATE INDEX idx_jobs_company      ON jobs(company_name);
CREATE INDEX idx_jobs_posted_date  ON jobs(posted_date);
CREATE INDEX idx_jobs_employment   ON jobs(employment_type);

-- Full-text search (FTS5)
CREATE VIRTUAL TABLE jobs_fts USING fts5(
    job_title, company_name, city, state, description_text,
    content='jobs', content_rowid='rowid'
);
```

## SQLite Usage Examples

```python
import sqlite3

conn = sqlite3.connect("data/jobs.db")

# All jobs from WSP
for row in conn.execute(
    "SELECT job_title, city, state FROM jobs WHERE company_name = ?",
    ("WSP in the U.S.",)
):
    print(row)

# Civil engineering internships in Texas
for row in conn.execute("""
    SELECT job_title, company_name, city
    FROM jobs
    WHERE state = 'TX'
      AND employment_type = 'INTERNSHIP'
      AND (job_title LIKE '%civil%' OR job_title LIKE '%environmental%')
    ORDER BY company_name
"""):
    print(row)

# Full-text search
for row in conn.execute("""
    SELECT job_title, company_name, city, snippet(jobs_fts, 4, '<b>', '</b>', '...', 20) as context
    FROM jobs_fts
    JOIN jobs ON jobs.rowid = jobs_fts.rowid
    WHERE jobs_fts MATCH 'storm water OR wastewater'
    LIMIT 10
"""):
    print(f"{row[0]} @ {row[1]} ({row[2]})")
    print(f"  {row[3]}")

# Salary range for internships
for row in conn.execute("""
    SELECT job_title, company_name, salary_min, salary_max, salary_interval
    FROM jobs
    WHERE salary_min IS NOT NULL AND employment_type = 'INTERNSHIP'
    ORDER BY salary_min DESC
    LIMIT 10
"""):
    print(row)

# Stats
print(conn.execute("SELECT COUNT(*) FROM jobs").fetchone())
print(conn.execute("SELECT company_name, COUNT(*) FROM jobs GROUP BY company_name ORDER BY COUNT(*) DESC LIMIT 5").fetchall())
print(conn.execute("SELECT state, COUNT(*) FROM jobs WHERE state != '' GROUP BY state ORDER BY COUNT(*) DESC").fetchall())

# Cleanup old jobs
conn.execute("DELETE FROM jobs WHERE scraped_at < date('now', '-30 days')")
conn.commit()
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# ── One-command pipeline (recommended) ────────────────────────────
python run_pipeline.py --step all    # Full pipeline: scrape → auto-migrate

# ── Step-by-step ─────────────────────────────────────────────────
python run_pipeline.py --step scrape  # Scrape jobs (requires Playwright MCP)
python jd_fetch.py                   # Fill JDs via MCP webfetch (manual)
python run_pipeline.py --step migrate  # Push JSON → SQLite + FTS

# ── Query the database ───────────────────────────────────────────
python -c "
import sqlite3
conn = sqlite3.connect('data/jobs.db')
print('Total:', conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0])
print(conn.execute('SELECT company_name, COUNT(*) FROM jobs GROUP BY company_name ORDER BY COUNT(*) DESC LIMIT 5').fetchall())
"

# ── Backfill dates for legacy data ───────────────────────────────
python backfill_dates.py --fallback
```

## Data Schema (JSON legacy)

```json
{
  "title": "Civil Engineering Intern",
  "company": "WSP in the U.S.",
  "location": "Houston, TX (On-site)",
  "url": "https://www.linkedin.com/jobs/view/4384037771",
  "source": "linkedin",
  "job_type": "Internship",
  "posted_date": "1 week ago",
  "description": "Full job description text..."
}
```

## Key Findings (2026-03-25 Scraped Data)

| Metric | Value |
|--------|-------|
| Total Jobs | 124 |
| Companies | 29 unique |
| Top Company | WSP in the U.S. (23 jobs) |
| Top State | TX (19 jobs) |
| Job Types | Internship (115), Co-op/Temporary (4), Full-time (4), Part-time (1) |
| Date Range | 2026-02-25 → 2026-03-25 |
| Past Week Jobs | 71 (2026-03-18 to 2026-03-25) |
| DB Size | 720 KB (SQLite with FTS) |

## Notes

- **Use `run_pipeline.py`** as the main entry point. It handles the full pipeline.
- LinkedIn requires an authenticated session. Run with Playwright MCP connected to a logged-in browser.
- `f_TPR=r2592000` filters to jobs posted in the past 30 days.
- `scrape_all_jobs.py` auto-migrates to SQLite on completion — no manual step needed after scraping.
- After filling JDs via MCP webfetch, run `python jd_fetch.py --migrate` to push updates to SQLite.
- If LinkedIn blocks direct JD access, use `webfetch` on the job URL — it bypasses JS rendering blocking.
- SQLite is the primary storage. JSON is the portable exchange format fed into SQLite.
- `backfill_dates.py --fallback` converts remaining relative dates to ISO using scrape date as reference.
