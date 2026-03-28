"""
XCrawl Client — production-grade wrapper around XCrawl Scrape API.

Anti-scraping & reliability features:
  - Exponential backoff retry (max 3 attempts, 2s base)
  - Random jitter delay between requests (1.5–3s)
  - Per-request random User-Agent rotation
  - LinkedIn-specific request tuning (viewport, js_render)
  - Optional proxy support (via ~/.xcrawl/config.json)
  - Graceful fallback: sync → async → give up

Config file: ~/.xcrawl/config.json
  {
    "XCRAWL_API_KEY": "...",
    "max_retries": 3,
    "min_delay": 1.5,
    "max_delay": 3.0,
    "proxy": { "location": "US" },
    "linkedin_viewport": { "width": 1280, "height": 800 }
  }

Usage:
    from xcrawl_client import fetch_jd, scrape_url

    # Single JD fetch
    jd_text = fetch_jd("https://www.linkedin.com/jobs/view/123456789")

    # Batch fetch
    for jd in fetch_jd_batch(urls):
        if jd:
            print(len(jd), "chars")
"""

import json
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path.home() / ".xcrawl" / "config.json"
BASE_URL = "https://run.xcrawl.com"

# Defaults (override via config.json)
DEFAULT_MAX_RETRIES = 3
DEFAULT_MIN_DELAY = 1.5  # seconds between requests
DEFAULT_MAX_DELAY = 3.0
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}

# LinkedIn-specific end markers (more comprehensive)
LINKEDIN_END_MARKERS = [
    "Similar jobs",
    "Referrals increase your chances",
    "Get notified",
    "Show more",
    "Show less",
    "Seniority level",
    "Job function",
    "Industries",
    "Equal Opportunity",
    "Why AECOM",
    "What makes",
    "People also viewed",
    "People also searched",
    "LinkedIn",
    "\n\n\n\n\n",
]

# Realistic browser User-Agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


# ── Config Loading ─────────────────────────────────────────────────────────────


def _load_config() -> dict:
    """Load and merge config from ~/.xcrawl/config.json with defaults."""
    defaults = {
        "max_retries": DEFAULT_MAX_RETRIES,
        "min_delay": DEFAULT_MIN_DELAY,
        "max_delay": DEFAULT_MAX_DELAY,
        "proxy": None,
        "linkedin_viewport": DEFAULT_VIEWPORT,
    }
    if not CONFIG_PATH.exists():
        return defaults
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        # Merge user config over defaults
        merged = defaults.copy()
        merged.update({k: v for k, v in user.items() if v is not None})
        return merged
    except (json.JSONDecodeError, IOError):
        return defaults


# ── API Key ─────────────────────────────────────────────────────────────────


def get_api_key() -> str:
    """Load XCrawl API key from ~/.xcrawl/config.json."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"XCrawl config not found: {CONFIG_PATH}\n"
            "Create it with: ~/.xcrawl/config.json\n"
            '  {"XCRAWL_API_KEY": "your_key_here"}'
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    key = config.get("XCRAWL_API_KEY", "")
    if not key:
        raise ValueError(f"XCRAWL_API_KEY not found in {CONFIG_PATH}")
    return key


# ── Low-level API ─────────────────────────────────────────────────────────────


def _run_curl(method: str, path: str, body: dict = None, timeout: int = 60) -> dict:
    """Execute a XCrawl API call via curl. Returns parsed JSON response."""
    api_key = get_api_key()
    cmd = [
        "curl",
        "-sS",
        "-X",
        method,
        f"{BASE_URL}{path}",
        "-H",
        "Content-Type: application/json",
        "-H",
        f"Authorization: Bearer {api_key}",
    ]
    if body:
        cmd += ["-d", json.dumps(body)]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr[:200]}")
    stdout = result.stdout or ""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from XCrawl: {stdout[:200]}\n{e}")


# ── Request Building ───────────────────────────────────────────────────────────


def _build_scrape_body(url: str, async_mode: bool = False) -> dict:
    """Build LinkedIn-optimized scrape request body."""
    cfg = _load_config()

    body = {
        "url": url,
        "mode": "async" if async_mode else "sync",
        "js_render": {
            "enabled": True,
            "wait_until": "networkidle",
        },
        "request": {
            "device": "desktop",
            "locale": "en-US,en;q=0.9",
        },
        "output": {"formats": ["markdown"]},
    }

    # Viewport (LinkedIn is responsive but desktop gives more content)
    vp = cfg.get("linkedin_viewport") or DEFAULT_VIEWPORT
    body["js_render"]["viewport"] = {
        "width": vp.get("width", 1280),
        "height": vp.get("height", 800),
    }

    # Proxy (XCrawl's built-in residential proxy rotation)
    proxy = cfg.get("proxy")
    if proxy:
        body["proxy"] = proxy

    return body


def _classify_error(resp: dict) -> str:
    """Classify XCrawl error to decide retry strategy."""
    err = resp.get("error", "").lower()
    status = resp.get("status", "")

    # Permanent failures — don't retry
    if status == "failed":
        msg = str(resp.get("message", "")).lower()
        if any(k in msg for k in ["invalid url", "unsupported", "blocked"]):
            return "permanent"
        # Rate limit or transient — retry
        if any(k in msg for k in ["rate", "timeout", "503", "502", "429", "500", "502"]):
            return "retryable"
        return "retryable"

    return "retryable"


# ── Core Scrape Functions ───────────────────────────────────────────────────────


def scrape_url_sync(url: str) -> dict:
    """
    Scrape a URL synchronously with retry + backoff.

    Raises:
        RuntimeError: on permanent failure
        TimeoutError: after max retries exhausted
    """
    cfg = _load_config()
    max_retries = cfg.get("max_retries", DEFAULT_MAX_RETRIES)

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            body = _build_scrape_body(url, async_mode=False)
            resp = _run_curl("POST", "/v1/scrape", body, timeout=90)

            status = resp.get("status", "")
            if status == "completed":
                return resp
            if status == "failed":
                cls = _classify_error(resp)
                if cls == "permanent":
                    raise RuntimeError(f"XCrawl permanent failure: {resp.get('message', resp)}")
                # retryable — fall through to retry

        except (RuntimeError, subprocess.TimeoutExpired, ConnectionError) as e:
            last_err = e
            if attempt == max_retries:
                raise RuntimeError(f"XCrawl scrape failed after {max_retries} attempts: {e}")

        # Exponential backoff: 2s, 4s, 8s ...
        wait = 2**attempt + random.uniform(0, 1)
        time.sleep(wait)

    raise RuntimeError(f"XCrawl scrape exhausted {max_retries} retries: {last_err}")


def scrape_url_async(url: str) -> dict:
    """Start an async scrape. Use poll_result() to get results."""
    body = _build_scrape_body(url, async_mode=True)
    resp = _run_curl("POST", "/v1/scrape", body, timeout=30)
    if resp.get("status") == "failed":
        raise RuntimeError(f"XCrawl async scrape failed: {resp.get('message', resp)}")
    return resp


def poll_result(scrape_id: str, max_wait: int = 180, interval: float = 5.0) -> dict:
    """
    Poll an async scrape until completion.

    Raises:
        TimeoutError: if max_wait exceeded
        RuntimeError: if scrape fails
    """
    start = time.time()
    while time.time() - start < max_wait:
        resp = _run_curl("GET", f"/v1/scrape/{scrape_id}", timeout=30)
        status = resp.get("status", "")
        if status == "completed":
            return resp
        if status == "failed":
            raise RuntimeError(f"XCrawl scrape failed: {resp.get('message', resp)}")
        # pending / crawling — wait with jitter
        jitter = random.uniform(0, 1)
        time.sleep(interval + jitter)
    raise TimeoutError(f"XCrawl scrape {scrape_id} did not complete within {max_wait}s")


def scrape_url_with_fallback(url: str) -> Optional[dict]:
    """
    Scrape a URL: try sync first, fall back to async if slow.

    Returns completed response dict or None on total failure.
    """
    try:
        return scrape_url_sync(url)
    except TimeoutError:
        # Sync timed out — try async as fallback
        try:
            resp = scrape_url_async(url)
            scrape_id = resp.get("scrape_id")
            if scrape_id:
                return poll_result(scrape_id, max_wait=180)
        except (RuntimeError, TimeoutError, Exception) as e:
            print(f"  [XCrawl] Async fallback failed for {url}: {e}")
        return None
    except RuntimeError as e:
        print(f"  [XCrawl] Sync scrape failed for {url}: {e}")
        return None


# ── Random Delay (anti-scraping) ───────────────────────────────────────────────


def wait_before_request() -> None:
    """Random delay between requests to avoid triggering LinkedIn rate limits."""
    cfg = _load_config()
    lo = cfg.get("min_delay", DEFAULT_MIN_DELAY)
    hi = cfg.get("max_delay", DEFAULT_MAX_DELAY)
    delay = random.uniform(lo, hi)
    time.sleep(delay)


# ── JD Extraction ─────────────────────────────────────────────────────────────


def extract_jd_from_markdown(markdown_text: str) -> Optional[str]:
    """
    Extract JD section from XCrawl markdown output.

    Handles LinkedIn's various markdown structures.
    Returns cleaned JD text (min 100 chars) or None.
    """
    if not markdown_text or len(markdown_text) < 100:
        return None

    section = None

    # Priority order: most specific markers first
    markers = [
        # LinkedIn specific
        "Short Description",
        "Job Description",
        "About the job",
        "About this job",
        # General
        "Position Overview",
        "Role Summary",
        "Overview",
        "About the Role",
        "Responsibilities",
        "What You'll Do",
        "What You'll Gain",
        "What You'll Do",
        "About this Position",
        "Job Details",
        "Role Description",
    ]

    for marker in markers:
        idx = markdown_text.find(marker)
        if idx >= 0:
            section = markdown_text[idx:]
            break

    if section is None:
        # No known marker — use content before the first nav/sidebar section
        if len(markdown_text) > 500:
            section = markdown_text
        else:
            return None

    # Truncate at navigation / related-content markers
    for end in LINKEDIN_END_MARKERS:
        pos = section.find(end)
        if 0 < pos < len(section):
            section = section[:pos]
            break

    # Clean up
    section = re.sub(r"[ \t]+", " ", section)
    section = re.sub(r"\n{3,}", "\n\n", section)
    section = section.strip()

    if len(section) < 100:
        return None

    return section


# ── High-level: Single JD Fetch ───────────────────────────────────────────────


def fetch_jd(url: str) -> Optional[str]:
    """
    Fetch and extract JD from a LinkedIn job page.

    Full pipeline: wait → scrape → extract JD.

    Returns:
        JD text on success, None on failure
    """
    wait_before_request()

    resp = scrape_url_with_fallback(url)
    if not resp or resp.get("status") != "completed":
        return None

    markdown = resp.get("data", {}).get("markdown", "")
    return extract_jd_from_markdown(markdown)


# ── High-level: Batch Fetch ───────────────────────────────────────────────────


def fetch_jd_batch(urls: list[str], stop_on_error: bool = False) -> list[Optional[str]]:
    """
    Fetch JDs for multiple URLs sequentially.

    Args:
        urls: List of LinkedIn job URLs
        stop_on_error: If True, raise on first error; if False, skip and continue

    Returns:
        List of JD strings (or None for failed/skipped)
    """
    results = []
    for i, url in enumerate(urls, 1):
        try:
            jd = fetch_jd(url)
            results.append(jd)
            print(f"  [{i}/{len(urls)}] {'OK' if jd else 'SKIP'}: {url[-20:]}")
        except Exception as e:
            print(f"  [{i}/{len(urls)}] ERR: {e}")
            results.append(None)
            if stop_on_error:
                raise
    return results


# ── Database Helpers ─────────────────────────────────────────────────────────────


def rebuild_fts_index(conn) -> bool:
    """Rebuild FTS5 index to sync with updated JDs. Returns True on success."""
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO jobs_fts(jobs_fts) VALUES('rebuild')")
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM jobs_fts")
        fts_count = cur.fetchone()[0]
        cur.execute(
            'SELECT COUNT(*) FROM jobs WHERE description_text IS NOT NULL AND description_text != ""'
        )
        jobs_count = cur.fetchone()[0]
        print(f"  [FTS] Index rebuilt: {fts_count} entries (jobs with JD: {jobs_count})")
        return True
    except Exception as e:
        print(f"  [FTS] Rebuild failed: {e}")
        return False


# ── Credits ─────────────────────────────────────────────────────────────────


def get_credits() -> Optional[int]:
    """Return current XCrawl account credits.

    Credits info is available on the dashboard at https://dash.xcrawl.com/
    """
    return None
