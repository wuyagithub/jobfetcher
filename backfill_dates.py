"""
backfill_dates.py — Backfill real posting dates for all jobs in jobs.db.

Strategy:
  1. Try webfetch on each LinkedIn job URL → extract datePosted from JSON-LD
  2. Fallback: parse "X days/hours/weeks ago" from DOM, convert with
     SCRAPE_DATE (2026-03-25) as reference
  3. Update jobs.db posted_date AND linkedin_jobs_20260325_new.json

Usage:
  python backfill_dates.py              # interactive (fetches real dates)
  python backfill_dates.py --fallback   # fast fallback using relative dates
"""

import json
import re
import sqlite3
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ============================================================================
# CONFIG
# ============================================================================

DB_PATH = Path(__file__).parent / "data" / "jobs.db"
JSON_PATH = Path(__file__).parent / "data" / "linkedin_jobs_20260325_new.json"
SCRAPE_DATE = datetime(2026, 3, 25)  # reference for relative-date → ISO

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


# ============================================================================
# DATE HELPERS
# ============================================================================

RELATIVE_RE = re.compile(r"(\d+)?\s*(hour|day|week|month)s?\s*ago", re.IGNORECASE)
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def relative_to_iso(relative: str) -> str:
    """Convert '6 days ago' → ISO date using SCRAPE_DATE as reference."""
    if not relative:
        return ""
    m = RELATIVE_RE.search(relative.strip())
    if not m:
        return ""
    count_str, unit = m.group(1), m.group(2).lower()
    count = int(count_str) if count_str else 1
    delta = {"hour": 0, "day": count, "week": count * 7, "month": count * 30}.get(unit, 0)
    result = SCRAPE_DATE - timedelta(days=delta)
    return result.replace(hour=0, minute=0, second=0).isoformat()


# ============================================================================
# EXTRACTION
# ============================================================================


def extract_date_from_html(html: str) -> str:
    """
    Try to extract ISO datePosted from JSON-LD in HTML.
    Fall back to parsing 'X days ago' relative text.
    """
    # Try JSON-LD datePosted
    m = re.search(r'"datePosted"\s*:\s*"([^"]+)"', html)
    if m:
        date_val = m.group(1)
        if ISO_RE.match(date_val[:10]):
            return date_val[:10] + "T00:00:00"

    # Fallback: look for "X days ago" etc. near posted-date elements
    # LinkedIn: <span>1 week ago</span> or "posted-date" class
    patterns = [
        r"jobs-unified-top-card__posted-date[^>]*>([^<]{3,50})",
        r'"postedDate"\s*:\s*"([^"]+)"',
        r"data-test-job-posted-date[^>]*>([^<]{3,50})",
        r">(\d+\s*(hour|day|week|month)s?\s*ago)<",
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
            iso = relative_to_iso(text)
            if iso:
                return iso

    return ""


def fetch_date_via_webfetch(url: str) -> str:
    """Fetch LinkedIn job page via webfetch tool (MCP). Returns ISO date or ''."""
    try:
        import subprocess

        result = subprocess.run(
            [
                "python",
                "-c",
                f"""
import urllib.request
req = urllib.request.Request(
    {repr(url)},
    headers={{'User-Agent': {repr(USER_AGENT)}}}
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode('utf-8', errors='ignore')
        # Look for datePosted in JSON-LD
        import re
        m = re.search(r'"datePosted"\\s*:\\s*"([^"]+)"', html)
        if m:
            print(m.group(1))
        else:
            # Fallback relative
            m2 = re.search(r'>(\\d+\\s*(hour|day|week|month)s?\\s*ago)<', html, re.IGNORECASE)
            if m2:
                print('RELATIVE:', m2.group(1))
            else:
                print('NONE')
except Exception as e:
    print('ERROR:', e)
""",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        out = result.stdout.strip()
        if out.startswith("ERROR") or out == "NONE":
            return ""
        if out.startswith("RELATIVE:"):
            return relative_to_iso(out.split(":", 1)[1].strip())
        return out[:10] + "T00:00:00" if len(out) >= 10 else out
    except Exception:
        return ""


# ============================================================================
# SQL HELPERS
# ============================================================================


def get_all_jobs():
    conn = sqlite3.connect(DB_PATH)
    jobs = conn.execute(
        "SELECT id, job_title, source_url, posted_date FROM jobs ORDER BY posted_date"
    ).fetchall()
    conn.close()
    return jobs


def update_job_date(job_id: str, iso_date: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET posted_date = ? WHERE id = ?", (iso_date, job_id))
    conn.commit()
    conn.close()


def update_json_date(source_url: str, iso_date: str):
    if not JSON_PATH.exists():
        return
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    changed = False
    for job in data:
        if job.get("url") == source_url:
            job["posted_date"] = iso_date
            changed = True
            break
    if changed:
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================================
# MAIN — webfetch via MCP (requires MCP tool access)
# ============================================================================


def main_via_mcp():
    """Use MCP webfetch tool — called by agent, not run directly."""
    print("This script should be called by the agent which uses MCP webfetch.")
    print("Loading jobs from DB...")
    jobs = get_all_jobs()
    pending = [(j[0], j[1][:50], j[2], j[3]) for j in jobs if "T" not in (j[3] or "")]
    print(f"Jobs needing date backfill: {len(pending)}")
    for job_id, title, url, old in pending:
        print(f"  [{job_id}] {title}")
        print(f"    old: {old}")
        print(f"    MCP command: webfetch --url {url} --format text")
        print(f"    Then extract datePosted from JSON-LD or parse relative date")
        print()


# ============================================================================
# FALLBACK — relative dates only
# ============================================================================


def run_fallback():
    """Convert all relative dates to ISO using SCRAPE_DATE as reference.
    Use when MCP/webfetch is unavailable.
    """
    print(f"Relative-date fallback (reference: {SCRAPE_DATE.date()})...")
    conn = sqlite3.connect(DB_PATH)
    jobs = conn.execute("SELECT id, source_url, posted_date FROM jobs").fetchall()
    updated_db = 0
    updated_json = 0

    for job_id, url, old_date in jobs:
        if "T" in (old_date or ""):
            continue
        iso = relative_to_iso(old_date) if old_date else ""
        if iso:
            conn.execute("UPDATE jobs SET posted_date = ? WHERE id = ?", (iso, job_id))
            updated_db += 1
            update_json_date(url, iso)
            updated_json += 1

    conn.commit()
    conn.close()

    # JSON
    if JSON_PATH.exists():
        with open(JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for job in data:
            old = job.get("posted_date", "")
            if "T" not in old and old:
                iso = relative_to_iso(old)
                if iso:
                    job["posted_date"] = iso
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  DB rows updated:   {updated_db}")
    print(f"  JSON jobs updated: {updated_json}")
    verify()


# ============================================================================
# VERIFY
# ============================================================================


def verify():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    iso = conn.execute("SELECT COUNT(*) FROM jobs WHERE posted_date LIKE '%T%'").fetchone()[0]
    range_row = conn.execute(
        "SELECT MIN(posted_date), MAX(posted_date) FROM jobs WHERE posted_date LIKE '%T%'"
    ).fetchone()
    print(f"\nVerification:")
    print(f"  Total jobs:    {total}")
    print(f"  With ISO date: {iso}")
    if range_row and range_row[0]:
        print(f"  Date range:   {range_row[0][:10]} → {range_row[1][:10]}")
    conn.close()


# ============================================================================
# ENTRY
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fallback":
        run_fallback()
    else:
        main_via_mcp()
        print("\n[Or run with --fallback to use relative-date conversion]")
        verify()
