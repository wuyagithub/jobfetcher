"""
JobFetcher Pipeline Orchestrator — runs the full unattended workflow.

Steps:
  1. Scrape LinkedIn (Playwright headless + cookie auth)
  2. Migrate JSON to SQLite
  3. Fetch missing JDs via XCrawl
  4. Rebuild FTS5 index
  5. Generate HTML table with timestamp

Usage:
    python run_pipeline.py                    # Full pipeline (no JD fetch)
    python run_pipeline.py --scrape           # Scrape only
    python run_pipeline.py --migrate          # Migrate JSON -> SQLite only
    python run_pipeline.py --jd                # Fetch missing JDs via XCrawl
    python run_pipeline.py --html              # Generate HTML table only
    python run_pipeline.py --all               # Full pipeline including JD fetch
    python run_pipeline.py --check             # Show status without running

Examples:
    # Scheduled run (cron):
    python run_pipeline.py --all --html

    # JD fetch only (uses XCrawl):
    python run_pipeline.py --jd
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "jobs.db"
COOKIE_FILE = DATA_DIR / "linkedin_cookies.json"
CONFIG_PATH = Path.home() / ".xcrawl" / "config.json"


# ── Helpers ───────────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def run_script(name: str, script: Path, args: list[str] = None) -> bool:
    """Run a Python script as subprocess. Returns True on success."""
    log(f"Starting: {name}")
    try:
        result = subprocess.run(
            [sys.executable, str(script)] + (args or []),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            # Print last 5 meaningful lines
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            for line in lines[-5:]:
                print(f"  {line}")
            log(f"Done: {name}")
            return True
        else:
            print(f"  STDERR: {result.stderr[-300:]}")
            log(f"Failed: {name} (exit {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        log(f"Timeout: {name} (> 5 min)")
        return False
    except Exception as e:
        log(f"Error: {name}: {e}")
        return False


def db_status() -> dict:
    """Get current database status."""
    import sqlite3

    if not DB_PATH.exists():
        return {"total": 0, "with_jd": 0, "missing_jd": 0, "fts": 0}

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        with_jd = conn.execute(
            'SELECT COUNT(*) FROM jobs WHERE description_text IS NOT NULL AND description_text != ""'
        ).fetchone()[0]
        fts = conn.execute("SELECT COUNT(*) FROM jobs_fts").fetchone()[0]
    except Exception:
        total = with_jd = fts = 0
    conn.close()
    return {"total": total, "with_jd": with_jd, "missing_jd": total - with_jd, "fts": fts}


def print_status():
    """Print current pipeline status."""
    import sqlite3
    from xcrawl_client import get_credits

    log("Pipeline Status Check")
    print("-" * 40)

    # XCrawl
    if CONFIG_PATH.exists():
        print(f"  XCrawl: configured ({CONFIG_PATH})")
        credits = get_credits()
        if credits is not None:
            print(f"  XCrawl credits: {credits}")
        else:
            print("  XCrawl credits: check https://dash.xcrawl.com/")
    else:
        print(f"  XCrawl: NOT CONFIGURED (missing {CONFIG_PATH})")

    # Database
    status = db_status()
    print(f"\n  Database: {DB_PATH}")
    print(f"  Total jobs: {status['total']}")
    pct = f"{status['with_jd'] / status['total'] * 100:.0f}%" if status["total"] else "N/A"
    print(f"  With JD: {status['with_jd']} ({pct})")
    print(f"  Missing JD: {status['missing_jd']}")
    print(f"  FTS entries: {status['fts']}")

    # JSON
    json_files = list(DATA_DIR.glob("linkedin_jobs_*.json"))
    if json_files:
        latest = max(json_files, key=lambda p: p.stat().st_mtime)
        print(f"\n  Latest JSON: {latest.name}")
    else:
        print(f"\n  JSON: No files found")

    print()


# ── Pipeline Steps ────────────────────────────────────────────────────────────


def step_scrape(args) -> bool:
    """Step 1: Scrape LinkedIn (headless if cookies available)."""
    script = Path(__file__).parent / "scrape_all_jobs.py"
    scrape_args = []
    if args.headless or COOKIE_FILE.exists():
        scrape_args.append("--headless")
    scrape_args.extend(["--pages", str(args.pages)])
    return run_script("Step 1: Scrape LinkedIn", script, scrape_args)


def step_migrate(args) -> bool:
    """Step 2: Migrate JSON to SQLite."""
    script = Path(__file__).parent / "migrate_to_sqlite.py"
    return run_script("Step 2: Migrate to SQLite", script)


def step_fetch_jd(args) -> bool:
    """Step 3: Fetch missing JDs via XCrawl (uses xcrawl_client.py)."""
    script = Path(__file__).parent / "jd_fetch.py"
    fetch_args = ["--fetch"]
    if hasattr(args, "async_mode") and args.async_mode:
        fetch_args.append("--async")
    return run_script("Step 3: Fetch JDs via XCrawl", script, fetch_args)


def step_html(args) -> bool:
    """Step 4: Generate HTML table."""
    script = Path(__file__).parent / "gen_table.py"
    return run_script("Step 4: Generate HTML Table", script)


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="JobFetcher Pipeline")
    parser.add_argument("--all", action="store_true", help="Run full pipeline")
    parser.add_argument("--scrape", action="store_true", help="Scrape LinkedIn")
    parser.add_argument("--migrate", action="store_true", help="Migrate to SQLite")
    parser.add_argument("--jd", action="store_true", help="Fetch missing JDs")
    parser.add_argument("--html", action="store_true", help="Generate HTML table")
    parser.add_argument("--check", action="store_true", help="Show status only")
    parser.add_argument("--headless", action="store_true", help="Use headless mode for scraping")
    parser.add_argument("--pages", type=int, default=5, help="Max scrape pages (default: 5)")
    args = parser.parse_args()

    # Status only
    if args.check:
        print_status()
        return

    # Default: show what would run
    if not any([args.all, args.scrape, args.migrate, args.jd, args.html]):
        print("JobFetcher Pipeline — no steps specified")
        print("Run with --help for usage")
        print("\nExamples:")
        print("  python run_pipeline.py --check          # Show status")
        print("  python run_pipeline.py --scrape         # Scrape only")
        print("  python run_pipeline.py --all            # Full pipeline")
        print("  python run_pipeline.py --scrape --html  # Scrape + HTML")
        return

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] JobFetcher Pipeline started")
    print("=" * 60)

    steps = []
    if args.all:
        steps = ["scrape", "migrate", "jd", "html"]
    else:
        if args.scrape:
            steps.append("scrape")
        if args.migrate:
            steps.append("migrate")
        if args.jd:
            steps.append("jd")
        if args.html:
            steps.append("html")

    step_map = {
        "scrape": step_scrape,
        "migrate": step_migrate,
        "jd": step_fetch_jd,
        "html": step_html,
    }

    success = True
    for name in steps:
        ok = step_map[name](args)
        if not ok and name in ("scrape", "migrate"):
            print(f"[ERROR] Step '{name}' failed — stopping pipeline")
            success = False
            break
        elif not ok:
            success = False

    print("\n" + "=" * 60)
    if success:
        print(f"[{datetime.now():%H:%M:%S}] Pipeline completed successfully")
        print_status()
    else:
        print(f"[{datetime.now():%H:%M:%S}] Pipeline completed with errors")

    # Show reminder for manual steps
    if args.jd:
        print("\n[MCP] If JD fetch failed, run manually inside OpenClaw:")
        print("  python jd_fetch.py --status")


if __name__ == "__main__":
    import random  # noqa: F401 — used in _fetch_jd_automated

    main()
