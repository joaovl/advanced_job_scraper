#!/usr/bin/env python3
"""
ClearBank Job Scraper

Extracts jobs from saved ClearBank HTML and fetches descriptions from Ashby HQ.

Usage:
    python scrapers/clearbank_scraper.py
"""

import json
import time
import re
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict

BASE_DIR = Path(__file__).parent.parent
COMPANY_DIR = BASE_DIR / "Company_Pages" / "clear_bank"
OUTPUT_DIR = BASE_DIR / "output"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
}


@dataclass
class Job:
    title: str
    location: str
    url: str
    job_id: str
    description: str = ""
    department: str = ""
    work_type: str = ""
    workplace_type: str = ""
    company: str = "ClearBank"


def extract_jobs_from_listing(html_path: Path) -> list[Job]:
    """Extract job listings from saved HTML file."""
    print(f"Reading {html_path.name}...")

    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')
    jobs = []

    # Find all job divs with class workable__job
    for job_div in soup.find_all('div', class_='workable__job'):
        link = job_div.find('a')
        if not link:
            continue

        url = link.get('href', '')

        # Title from span.workable__job-title
        title_el = job_div.find('span', class_='workable__job-title')
        title = title_el.get_text(strip=True) if title_el else ""

        # Extract job_id from URL
        job_id = ""
        if url:
            match = re.search(r'/([a-f0-9-]+)$', url)
            if match:
                job_id = match.group(1)

        # Get tags
        tags = [tag.get_text(strip=True) for tag in job_div.find_all('span', class_='workable__job-tag')]

        # Workplace type (Remote/Hybrid)
        workplace_type = ""
        workplace_el = job_div.find('span', class_='workplace-type--desktop')
        if workplace_el:
            workplace_type = workplace_el.get_text(strip=True)

        # Parse other tags
        location = ""
        department = ""
        work_type = ""

        for tag in tags:
            if tag in ['Remote', 'Hybrid', 'On-site']:
                continue  # Already captured
            elif tag in ['Full-time', 'Part-time', 'Temporary', 'Contract']:
                work_type = tag
            elif 'ClearBank' in tag:
                department = tag
            else:
                location = tag

        if title and url:
            jobs.append(Job(
                title=title,
                location=location,
                url=url,
                job_id=job_id,
                department=department,
                work_type=work_type,
                workplace_type=workplace_type
            ))

    return jobs


def find_local_detail_page(job: Job) -> Path | None:
    """Find locally saved detail page for a job."""
    # Look for HTML files that contain the job title
    for html_file in COMPANY_DIR.glob("*.html"):
        if '_files' in str(html_file):
            continue
        # Check if filename contains part of job title
        title_part = job.title.split('(')[0].strip().lower()
        if title_part[:20] in html_file.name.lower():
            return html_file
    return None


def extract_description_from_local(html_path: Path) -> str:
    """Extract job description from locally saved Ashby HQ page."""
    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')

    # Ashby HQ stores job data in script tags as JSON
    # Look for script with job posting data
    for script in soup.find_all('script'):
        text = script.string or ""
        if 'descriptionHtml' in text or 'description' in text:
            # Try to extract JSON data
            import re
            import json as json_module
            # Look for job description in JSON
            match = re.search(r'"descriptionHtml"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                try:
                    # Use json to properly unescape the string
                    desc = json_module.loads('"' + match.group(1) + '"')
                    desc_soup = BeautifulSoup(desc, 'html.parser')
                    return desc_soup.get_text(separator='\n', strip=True)
                except (json_module.JSONDecodeError, UnicodeDecodeError):
                    pass

    # Fallback: get all text from body
    body = soup.find('body')
    if body:
        # Remove script and style tags
        for tag in body.find_all(['script', 'style', 'noscript']):
            tag.decompose()
        text = body.get_text(separator='\n', strip=True)
        # Filter to meaningful lines
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 20]
        if lines:
            return '\n'.join(lines[:50])  # First 50 meaningful lines

    return ""


def fetch_job_description(job: Job, session: requests.Session) -> bool:
    """Fetch full job description - try local file first, then HTTP."""
    print(f"  Fetching: {job.title[:50]}...")

    # First try local saved detail page
    local_file = find_local_detail_page(job)
    if local_file:
        print(f"    Using local: {local_file.name}")
        description = extract_description_from_local(local_file)
        if description:
            job.description = description
            return True

    # Try HTTP fetch (may not work for JS-rendered pages)
    try:
        response = session.get(job.url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')
        description = ""

        # Try common content selectors
        for selector in ['article', 'main', '.job-description', '.posting-content']:
            content = soup.select_one(selector)
            if content:
                description = content.get_text(separator='\n', strip=True)
                if len(description) > 100:
                    break

        # Fallback: all paragraphs
        if not description or len(description) < 100:
            paragraphs = soup.find_all(['p', 'li', 'h2', 'h3'])
            texts = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
            if texts:
                description = '\n'.join(texts)

        job.description = description
        return bool(description)

    except requests.RequestException as e:
        print(f"    HTTP failed: {e}")
        return False


def save_jobs(jobs: list[Job], output_path: Path):
    """Save jobs to JSON file."""
    output_data = {
        "company": "ClearBank",
        "scraped_at": datetime.now().isoformat(),
        "total_jobs": len(jobs),
        "jobs_with_description": sum(1 for j in jobs if j.description),
        "jobs": [asdict(j) for j in jobs]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_path}")


def main():
    print("=" * 60)
    print("CLEARBANK JOB SCRAPER (Ashby HQ)")
    print("=" * 60)

    # Find HTML files
    html_files = [f for f in COMPANY_DIR.glob("*.html") if '_files' not in str(f)]
    if not html_files:
        print(f"No HTML files found in {COMPANY_DIR}")
        return

    # Extract all jobs from listing files
    all_jobs = []
    seen_ids = set()

    for html_file in html_files:
        # Skip detail pages (they contain @ in name)
        if '@' in html_file.name:
            continue
        jobs = extract_jobs_from_listing(html_file)
        for job in jobs:
            if job.job_id and job.job_id not in seen_ids:
                all_jobs.append(job)
                seen_ids.add(job.job_id)
            elif not job.job_id:
                all_jobs.append(job)

    print(f"\nFound {len(all_jobs)} unique jobs")

    if not all_jobs:
        print("No jobs to process")
        return

    # Fetch descriptions
    print("\nFetching job descriptions...")
    session = requests.Session()

    success_count = 0
    for i, job in enumerate(all_jobs, 1):
        print(f"[{i}/{len(all_jobs)}]", end="")
        if fetch_job_description(job, session):
            success_count += 1
        time.sleep(1)

    print(f"\nSuccessfully fetched {success_count}/{len(all_jobs)} descriptions")

    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"clearbank_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_jobs(all_jobs, output_path)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for job in all_jobs[:10]:
        desc_preview = job.description[:50] + "..." if job.description else "(no description)"
        print(f"- {job.title[:40]}")
        print(f"  {job.location} | {job.workplace_type} | {job.work_type}")
        print(f"  {desc_preview}")

    if len(all_jobs) > 10:
        print(f"\n... and {len(all_jobs) - 10} more jobs")


if __name__ == "__main__":
    main()
