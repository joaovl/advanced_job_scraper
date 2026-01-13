#!/usr/bin/env python3
"""
Barclays Job Scraper

Extracts jobs from saved Barclays HTML and fetches full descriptions.

Usage:
    python scrapers/barclays_scraper.py
"""

import json
import time
import re
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import Optional

BASE_DIR = Path(__file__).parent.parent
COMPANY_DIR = BASE_DIR / "Company_Pages" / "Barclays"
OUTPUT_DIR = BASE_DIR / "output"

# Barclays doesn't heavily block requests if we use good headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}


@dataclass
class Job:
    title: str
    location: str
    url: str
    job_id: str
    description: str = ""
    requirements: str = ""
    department: str = ""
    date_posted: str = ""
    company: str = "Barclays"


def extract_jobs_from_listing(html_path: Path) -> list[Job]:
    """Extract job listings from saved HTML file."""
    print(f"Reading {html_path.name}...")

    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')
    jobs = []

    # Find all job links with data-job-id
    for link in soup.find_all('a', class_='job-title--link', attrs={'data-job-id': True}):
        title = link.get_text(strip=True)
        url = link.get('href', '')
        job_id = link.get('data-job-id', '')

        # Location is in next sibling div
        location = ""
        location_el = link.find_next('div', class_='job-location')
        if location_el:
            location = location_el.get_text(strip=True)

        # Date posted
        date_el = link.find_next('div', class_='job-date')
        date_posted = date_el.get_text(strip=True) if date_el else ""

        if title and url:
            jobs.append(Job(
                title=title,
                location=location,
                url=url,
                job_id=job_id,
                date_posted=date_posted
            ))

    return jobs


def fetch_job_description(job: Job, session: requests.Session) -> bool:
    """Fetch full job description from job detail page."""
    try:
        print(f"  Fetching: {job.title[:50]}...")

        response = session.get(job.url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Get location from detail page (more accurate than listing)
        loc_el = soup.find('p', class_='job-details--location')
        if loc_el:
            job.location = loc_el.get_text(strip=True)

        # Try multiple selectors for job description
        description = ""

        # Primary: ats-description div
        desc_el = soup.find('div', class_='ats-description')
        if desc_el:
            description = desc_el.get_text(separator='\n', strip=True)

        # Fallback: job-description section
        if not description:
            desc_el = soup.find('section', class_='job-description')
            if desc_el:
                description = desc_el.get_text(separator='\n', strip=True)

        # Fallback: any div with description in class
        if not description:
            desc_el = soup.find('div', class_=lambda c: c and 'description' in c.lower() if c else False)
            if desc_el:
                description = desc_el.get_text(separator='\n', strip=True)

        job.description = description

        # Try to get department/category
        dept_el = soup.find('span', class_='job-info__item--department')
        if dept_el:
            job.department = dept_el.get_text(strip=True)

        return bool(description)

    except requests.RequestException as e:
        print(f"    ERROR: {e}")
        return False


def save_jobs(jobs: list[Job], output_path: Path):
    """Save jobs to JSON file."""
    output_data = {
        "company": "Barclays",
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
    print("BARCLAYS JOB SCRAPER")
    print("=" * 60)

    # Find HTML files
    html_files = list(COMPANY_DIR.glob("*.html"))
    if not html_files:
        print(f"No HTML files found in {COMPANY_DIR}")
        return

    # Extract all jobs from all listing files
    all_jobs = []
    seen_ids = set()

    for html_file in html_files:
        jobs = extract_jobs_from_listing(html_file)
        for job in jobs:
            if job.job_id not in seen_ids:
                all_jobs.append(job)
                seen_ids.add(job.job_id)

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
        time.sleep(1)  # Be polite

    print(f"\nSuccessfully fetched {success_count}/{len(all_jobs)} descriptions")

    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"barclays_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_jobs(all_jobs, output_path)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for job in all_jobs[:10]:
        desc_preview = job.description[:50] + "..." if job.description else "(no description)"
        print(f"- {job.title[:40]}")
        print(f"  {job.location}")
        print(f"  {desc_preview}")

    if len(all_jobs) > 10:
        print(f"\n... and {len(all_jobs) - 10} more jobs")


if __name__ == "__main__":
    main()
