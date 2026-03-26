"""
Fallback JD extractor for LinkedIn jobs.
Searches company careers pages via DuckDuckGo 'site:' queries,
fetches the top result, and extracts job description text.
"""

import json
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}


def duckduckgo_search(query, max_results=3):
    """Search DuckDuckGo and return top result URLs."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if href.startswith("http") and "duckduckgo" not in href:
                results.append(href)
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"  [!] Search failed: {e}")
        return []


def fetch_page(url, timeout=15):
    """Fetch a URL and return (text, soup)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        # Try to detect encoding
        if resp.apparent_encoding:
            resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        return resp.text, soup
    except Exception as e:
        print(f"  [!] Fetch failed for {url}: {e}")
        return None, None


def extract_text_from_soup(soup):
    """Try to extract clean text from a BeautifulSoup object."""
    if soup is None:
        return ""
    # Remove script and style elements
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def find_careers_url(company_name, job_title, location):
    """Search for the job on company's careers page."""
    # Try different search patterns
    queries = [
        f"{job_title} {location} site:{company_name.lower().replace(' ', '')}.com careers",
        f'"{job_title}" "{location}" {company_name} careers',
        f"{job_title} {company_name} {location} job",
    ]
    for q in queries:
        urls = duckduckgo_search(q, max_results=3)
        for url in urls:
            if url:
                return url
    return None


def extract_jd_from_page(soup, job_title, company):
    """Try to extract JD text from a careers page."""
    text = extract_text_from_soup(soup)
    if not text:
        return None

    # Look for the section containing our job title or similar text
    lines = text.split("\n")
    # Find lines that might be section headers or job content
    jd_candidates = []
    in_jd = False
    for i, line in enumerate(lines):
        line_clean = line.strip()
        if not line_clean:
            continue
        # Check if this looks like JD content (longer descriptive text)
        if len(line_clean) > 50 and any(
            kw in line_clean.lower()
            for kw in [
                "responsibilities",
                "qualifications",
                "requirements",
                "skills",
                "description",
                "about",
                "you will",
                "you'll",
                "duties",
            ]
        ):
            in_jd = True
        if in_jd:
            jd_candidates.append(line_clean)
        # Stop after about 100 lines of JD content
        if len(jd_candidates) > 100:
            break

    if jd_candidates:
        return "\n".join(jd_candidates[:80])
    return None


def process_job(job, idx, total):
    """Process a single job and return updated job dict."""
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "").split(" (")[0]  # Remove (On-site) etc
    url = job.get("url", "")
    job_id = url.split("/")[-1] if url else str(idx)

    print(f"\n[{idx}/{total}] {company} - {title[:60]}")
    print(f"  LinkedIn: {url}")

    # Skip if already has full JD
    if "JD not yet extracted" not in job.get("description", ""):
        print("  [=] Already has JD, skipping")
        return job

    # Try to find the job on company website
    careers_url = find_careers_url(company, title, location)
    if not careers_url:
        print(f"  [!] No results found")
        return job

    print(f"  [>] Found: {careers_url}")

    html, soup = fetch_page(careers_url)
    if soup is None:
        print(f"  [!] Could not fetch page")
        return job

    jd_text = extract_jd_from_page(soup, title, company)
    if jd_text and len(jd_text) > 100:
        print(f"  [+] Extracted JD ({len(jd_text)} chars)")
        job["description"] = jd_text
        job["source_url"] = careers_url
    else:
        print(f"  [!] Could not extract JD content")

    time.sleep(1)  # Be polite
    return job


def main():
    input_file = r"D:\opencode\jobfetcher\data\linkedin_jobs_20260325_new.json"
    output_file = r"D:\opencode\jobfetcher\data\linkedin_jobs_20260325_new.json"

    with open(input_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    pending_indices = [
        i for i, j in enumerate(jobs) if "JD not yet extracted" in j.get("description", "")
    ]

    print(f"Total jobs: {len(jobs)}")
    print(f"Pending JDs: {len(pending_indices)}")

    for idx in pending_indices:
        jobs[idx] = process_job(jobs[idx], idx + 1, len(jobs))

    # Save updated JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    # Report results
    still_pending = sum(1 for j in jobs if "JD not yet extracted" in j.get("description", ""))
    filled = len(pending_indices) - still_pending
    print(f"\n{'=' * 50}")
    print(f"Done! Filled: {filled}/{len(pending_indices)} JDs")
    print(f"Still pending: {still_pending}")


if __name__ == "__main__":
    main()
