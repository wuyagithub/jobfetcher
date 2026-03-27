"""
Extract LinkedIn jobs with full JD using bb-browser
"""

import json
import subprocess
import time
import re
from datetime import datetime
from pathlib import Path

def run_bb(cmd):
    """Run bb-browser command and return output"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip()

def extract_jobs_from_page():
    """Extract job links from current search page"""
    cmd = 'bb-browser eval "const items = document.querySelectorAll(\\'[data-job-id]\\'); const urls = Array.from(items).map(x => \\'https://www.linkedin.com/jobs/view/\\' + x.dataset.jobId); JSON.stringify(urls);"'
    output, _ = run_bb(cmd)
    try:
        return json.loads(output)
    except:
        return []

def get_job_detail(url):
    """Get detailed JD from a job page"""
    # Open job page
    run_bb(f'bb-browser open "{url}"')
    time.sleep(1.5)
    
    # Get page text
    cmd = 'bb-browser eval "document.body.innerText"'
    output, _ = run_bb(cmd)
    text = output
    
    # Extract JD section
    lines = text.split('\n')
    job_data = {
        'url': url,
        'source': 'linkedin',
        'extracted_at': datetime.now().isoformat()
    }
    
    # Parse text to extract job info
    title = ''
    company = ''
    location = ''
    description = []
    in_description = False
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        # Skip UI elements
        if any(skip in line for skip in ['notification', 'Skip to', 'Home', 'My Network', 'Jobs', 'Messaging', 'Notifications']):
            continue
            
        # Title (usually first substantial line after URL loads)
        if not title and len(line) > 10 and len(line) < 150:
            if not line.startswith('http') and 'linkedin.com' not in line.lower():
                title = line
        
        # Company
        if 'company' in line.lower() or (title and not company and len(line) > 2 and len(line) < 80):
            if 'Be an early' not in line and 'Viewed' not in line and 'Apply' not in line:
                company = line
        
        # JD sections
        if any(kw in line.lower() for kw in ['description', 'about the job', 'duties', 'responsibilities', 'qualifications']):
            in_description = True
        
        if in_description:
            description.append(line)
            
        # Stop at common endpoints
        if in_description and len(description) > 200:
            break
        if 'similar jobs' in line.lower() or 'referrals' in line.lower():
            in_description = False
    
    job_data['title'] = title[:200] if title else ''
    job_data['company'] = company[:200] if company else ''
    job_data['description'] = '\n'.join(description[:100]) if description else ''
    
    return job_data

def main():
    print("Starting LinkedIn job extraction with bb-browser...")
    print()
    
    # Step 1: Extract job URLs from search page
    print("Step 1: Extracting job URLs from search page...")
    urls = extract_jobs_from_page()
    print(f"Found {len(urls)} jobs on first page")
    
    # Step 2: Extract JD for each job
    print(f"Step 2: Extracting JD for each job (this may take a while)...")
    jobs = []
    
    for i, url in enumerate(urls[:5], 1):  # Start with 5 for testing
        print(f"[{i}/{len(urls)}] Processing: {url[-20:]}")
        try:
            job = get_job_detail(url)
            jobs.append(job)
            print(f"  Title: {job.get('title', 'N/A')[:50]}")
            print(f"  Company: {job.get('company', 'N/A')}")
            print(f"  JD length: {len(job.get('description', ''))} chars")
        except Exception as e:
            print(f"  Error: {e}")
        
        time.sleep(1)  # Rate limit
    
    # Save
    timestamp = datetime.now().strftime("%Y%m%d")
    output_file = Path(f"data/linkedin_jobs_bb_{timestamp}.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        'search_keywords': 'civil engineer environmental engineer jobs in the United States',
        'extracted_at': datetime.now().isoformat(),
        'total_extracted': len(jobs),
        'jobs': jobs
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print()
    print(f"Done! Saved {len(jobs)} jobs to {output_file}")

if __name__ == "__main__":
    main()
