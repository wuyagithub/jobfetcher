"""
Fast JD extractor using Google site: search.
"""

import json
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def google_search(query, max_results=3):
    """Search Google and return top result URLs."""
    url = f"https://www.google.com/search?q={quote_plus(query)}&num={max_results}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            # Filter out Google internal links
            if href.startswith("/url?q="):
                # Extract actual URL
                match = re.search(r"/url\?q=([^&]+)", href)
                if match:
                    actual_url = match.group(1)
                    actual_url = actual_url.split("&")[0]
                    if actual_url.startswith("http"):
                        results.append(actual_url)
            elif href.startswith("http") and "google.com" not in href:
                results.append(href)
        return results[:max_results]
    except Exception as e:
        print(f"  [!] Search error: {e}")
        return []


def fetch_page(url, timeout=15):
    """Fetch a URL and return soup."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        if resp.apparent_encoding:
            resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [!] Fetch error: {e}")
        return None


def extract_jd_from_soup(soup, job_title, company):
    """Extract JD text from a page."""
    if soup is None:
        return None

    # Remove noise
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        tag.decompose()

    # Try to find main content
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if not text or len(text) < 200:
        return None

    # Find relevant content by looking for job-related keywords
    lines = text.split("\n")
    jd_parts = []
    capturing = False
    capture_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Start capturing when we hit relevant keywords
        lower = line.lower()
        if any(
            kw in lower
            for kw in [
                "responsibility",
                "qualification",
                "requirement",
                "description",
                "about the job",
                "about this role",
                "what you'll do",
                "what you'll",
                "skills",
                "experience",
                "duties",
                "you will",
                "overview",
            ]
        ):
            capturing = True
        if capturing:
            jd_parts.append(line)
            capture_count += 1
            if capture_count > 150:  # Limit capture
                break
        # Also capture lines that look substantive even before keyword
        elif len(line) > 80 and not capturing:
            # Check if it contains typical JD language
            if any(
                kw in lower
                for kw in [
                    "design",
                    "engineer",
                    "project",
                    "team",
                    "work",
                    "develop",
                    "support",
                    "assist",
                ]
            ):
                jd_parts.append(line)
                if len(jd_parts) > 30:  # Only very long lines
                    capturing = True

    if jd_parts:
        # Clean up
        text = "\n".join(jd_parts)
        # Remove too short lines
        lines = [l for l in text.split("\n") if len(l) > 30]
        return "\n".join(lines[:100])

    # Fallback: just get body text
    body = soup.find("body")
    if body:
        text = body.get_text(separator="\n", strip=True)
        lines = [l for l in text.split("\n") if len(l) > 30]
        if lines:
            return "\n".join(lines[:80])

    return None


def process_company(company_name, job_title, location):
    """Search for a specific job."""
    # Build search query - prioritize company careers page
    queries = [
        f'"{job_title}" "{location}" site:{company_name.lower().replace(" ", "-")}.com/careers',
        f'"{job_title}" "{location}" "{company_name}" careers',
        f'"{job_title}" "{location}" "{company_name}" job description',
    ]

    for q in queries:
        urls = google_search(q, max_results=3)
        for url in urls:
            if url and not any(
                x in url
                for x in ["linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com"]
            ):
                soup = fetch_page(url)
                if soup:
                    jd = extract_jd_from_soup(soup, job_title, company_name)
                    if jd and len(jd) > 150:
                        return url, jd
        time.sleep(0.5)  # Rate limit between queries

    return None, None


def main():
    input_file = r"D:\opencode\jobfetcher\data\linkedin_jobs_20260325_new.json"

    with open(input_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    pending = [
        (i, j) for i, j in enumerate(jobs) if "JD not yet extracted" in j.get("description", "")
    ]
    print(f"Total: {len(jobs)}, Pending: {len(pending)}")

    filled = 0
    for idx, job in pending:
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "").split(" (")[0].split(" · ")[0]
        url = job.get("url", "")

        print(f"\n[{idx + 1}/{len(jobs)}] {company} | {title[:50]}")

        result_url, jd_text = process_company(company, title, location)

        if jd_text:
            jobs[idx]["description"] = jd_text
            jobs[idx]["source_url"] = result_url
            print(f"  [+] SUCCESS ({len(jd_text)} chars) <- {result_url[:80]}")
            filled += 1
        else:
            print(f"  [-] Not found")

        time.sleep(1)  # Be polite between jobs

    # Save
    with open(input_file, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    still_pending = sum(1 for j in jobs if "JD not yet extracted" in j.get("description", ""))
    print(f"\n{'=' * 50}")
    print(f"Filled: {filled}/{len(pending)}")
    print(f"Still pending: {still_pending}")


if __name__ == "__main__":
    main()
