"""
LinkedIn Job Scraper using Playwright MCP
Extracts job listings from LinkedIn search results
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path


async def scrape_all_pages(page, base_url, max_pages=15):
    """Scrape job listings from all pages."""
    all_jobs = []
    seen_urls = set()

    for page_num in range(max_pages):
        start = page_num * 25
        url = f"{base_url}&start={start}" if start > 0 else base_url

        print(f"\n=== Scraping page {page_num + 1} ===")
        print(f"URL: {url[:80]}...")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)  # Wait for JS to render

        # Scroll to load all visible jobs
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 500)")
            await page.wait_for_timeout(300)

        # Extract job links
        jobs = await page.evaluate("""
            () => {
                const jobs = [];
                const seenUrls = new Set();
                const links = document.querySelectorAll('a[href*="/jobs/view/"]');
                
                links.forEach(link => {
                    const url = link.href;
                    if (seenUrls.has(url)) return;
                    seenUrls.add(url);
                    
                    const fullText = link.innerText.trim();
                    const firstNewline = fullText.indexOf('\\n');
                    const title = firstNewline > 0 ? fullText.substring(0, firstNewline) : fullText;
                    
                    if (title && url) {
                        jobs.push({
                            title: title,
                            url: url,
                            source: 'linkedin'
                        });
                    }
                });
                
                return jobs;
            }
        """)

        print(f"Found {len(jobs)} job links on page {page_num + 1}")

        # Filter out already seen jobs
        new_jobs = [j for j in jobs if j["url"] not in seen_urls]
        seen_urls.update(j["url"] for j in jobs)

        if new_jobs:
            all_jobs.extend(new_jobs)
            print(f"  New jobs: {len(new_jobs)}, Total: {len(all_jobs)}")

        if len(jobs) == 0:
            print("No more jobs found, stopping.")
            break

    return all_jobs


async def main():
    # Search parameters
    keywords = "civil engineering environmental engineering"
    location = "United States"
    date_filter = "r2592000"  # Past month

    base_url = (
        f"https://www.linkedin.com/jobs/search/?keywords={keywords.replace(' ', '%20')}"
        f"&location={location.replace(' ', '%20')}"
        f"&f_TPR={date_filter}"
    )

    print(f"Starting LinkedIn job scrape...")
    print(f"Search: {keywords} in {location}")
    print(f"Date filter: Past month")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        jobs = await scrape_all_pages(page, base_url, max_pages=15)

        await browser.close()

    print(f"\n=== SCRAPING COMPLETE ===")
    print(f"Total jobs collected: {len(jobs)}")

    # Save to JSON
    timestamp = datetime.now().strftime("%Y%m%d")
    output_file = Path(f"data/linkedin_jobs_{timestamp}_new.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Create metadata
    data = {
        "search_keywords": keywords,
        "search_location": location,
        "date_filter": "Past month (30 days)",
        "scraped_at": datetime.now().isoformat(),
        "total_found": len(jobs),
        "jobs": jobs,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Saved to: {output_file}")
    return jobs


if __name__ == "__main__":
    asyncio.run(main())
