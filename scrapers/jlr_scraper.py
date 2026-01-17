#!/usr/bin/env python3
"""
JLR (Jaguar Land Rover) Job Scraper

Scrapes jobs directly from JLR SuccessFactors careers site.

Usage:
    python scrapers/jlr_scraper.py                    # All UK jobs
    python scrapers/jlr_scraper.py --location London  # London only
    python scrapers/jlr_scraper.py --all              # All locations worldwide
"""

import json
import time
import re
import argparse
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import Optional, List

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

# JLR SuccessFactors careers site
BASE_URL = "https://www.jaguarlandrovercareers.com"
SEARCH_URL = f"{BASE_URL}/search/"

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
    company: str = "JLR"


def fetch_job_listings(location: str = "", start: int = 0) -> List[Job]:
    """Fetch job listings from JLR careers website."""
    params = {"q": "", "sortColumn": "referencedate", "sortDirection": "desc"}
    if location:
        params["locationsearch"] = location
    if start > 0:
        params["startrow"] = start

    try:
        response = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching listings: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    jobs = []

    # Check for no results
    no_results = soup.select_one('#noresults-message')
    if no_results and 'no open positions' in no_results.get_text().lower():
        return []

    # JLR SuccessFactors uses table rows for job listings
    # Selector: tr.data-row with a.jobTitle-link
    for row in soup.select('tr.data-row'):
        title_link = row.select_one('a.jobTitle-link')
        location_cell = row.select_one('td.colLocation, .colLocation')

        if not title_link:
            continue

        title = title_link.get_text(strip=True)
        url = title_link.get('href', '')

        # Make URL absolute
        if url and not url.startswith('http'):
            url = f"{BASE_URL}{url}"

        loc = location_cell.get_text(strip=True) if location_cell else ""

        # Extract job ID from URL (e.g., /job/Location-Title-Here/1284156701/)
        job_id_match = re.search(r'/(\d+)/?$', url)
        job_id = job_id_match.group(1) if job_id_match else ""

        if title:
            jobs.append(Job(
                title=title,
                location=loc,
                url=url,
                job_id=job_id
            ))

    # Alternative: look for job links if table structure not found
    if not jobs:
        for link in soup.select('a[href*="/job/"]'):
            url = link.get('href', '')
            title = link.get_text(strip=True)

            if not url.startswith('http'):
                url = f"{BASE_URL}{url}"

            # Extract job ID from URL (e.g., /job/Location-Title-Here/1284156701/)
            job_id_match = re.search(r'/(\d+)/?$', url)
            job_id = job_id_match.group(1) if job_id_match else ""

            # Skip navigation/duplicate links
            if title and len(title) > 5 and job_id:
                jobs.append(Job(
                    title=title,
                    location="",
                    url=url,
                    job_id=job_id
                ))

    return jobs


def fetch_all_jobs(location: str = "") -> List[Job]:
    """Fetch all jobs with pagination."""
    all_jobs = []
    seen_ids = set()
    start = 0
    page_size = 20  # JLR returns 20 jobs per page

    print(f"Fetching JLR jobs{' in ' + location if location else ' (all locations)'}...")

    while True:
        jobs = fetch_job_listings(location=location, start=start)

        if not jobs:
            break

        new_count = 0
        for job in jobs:
            job_key = job.job_id or job.url
            if job_key not in seen_ids:
                seen_ids.add(job_key)
                all_jobs.append(job)
                new_count += 1

        print(f"  Page {start // page_size + 1}: {len(jobs)} jobs, {new_count} new")

        if new_count == 0 or len(jobs) < page_size:
            break

        start += page_size
        time.sleep(1)  # Be polite

    return all_jobs


def fetch_job_description(job: Job, session: requests.Session) -> bool:
    """Fetch full job description from job detail page."""
    if not job.url:
        return False

    try:
        print(f"  Fetching: {job.title[:50]}...")

        response = session.get(job.url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Try multiple selectors for job description
        description = ""

        # Common JLR selectors
        selectors = [
            '.job-description',
            '.description',
            '#job-description',
            '[class*="description"]',
            '.job-details',
            '.content',
        ]

        for selector in selectors:
            desc_el = soup.select_one(selector)
            if desc_el:
                description = desc_el.get_text(separator='\n', strip=True)
                if len(description) > 50:  # Meaningful content
                    break

        job.description = description

        # Requirements
        req_el = soup.select_one('.requirements, .qualifications, #requirements')
        if req_el:
            job.requirements = req_el.get_text(separator='\n', strip=True)

        # Location (if not already set)
        if not job.location:
            loc_el = soup.select_one('.location, .job-location')
            if loc_el:
                job.location = loc_el.get_text(strip=True)

        return bool(description)

    except requests.RequestException as e:
        print(f"    ERROR: {e}")
        return False


def save_jobs(jobs: list[Job], output_path: Path):
    """Save jobs to JSON file."""
    output_data = {
        "company": "JLR",
        "scraped_at": datetime.now().isoformat(),
        "total_jobs": len(jobs),
        "jobs_with_description": sum(1 for j in jobs if j.description),
        "jobs": [asdict(j) for j in jobs]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="JLR Job Scraper")
    parser.add_argument("--location", "-l", default="",
                        help="Filter by location (e.g., 'London', 'Gaydon', 'UK')")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Fetch all locations worldwide")
    parser.add_argument("--no-description", "-nd", action="store_true",
                        help="Skip fetching job descriptions (faster)")
    args = parser.parse_args()

    print("=" * 60)
    print("JLR JOB SCRAPER")
    print("=" * 60)

    # Fetch jobs from website
    location = "" if args.all else (args.location or "UK")
    all_jobs = fetch_all_jobs(location=location)

    print(f"\nFound {len(all_jobs)} unique jobs")

    if not all_jobs:
        print("No jobs found matching criteria")
        print("Try --all to see all locations, or check https://www.jaguarlandrovercareers.com")

        # Still save empty result for tracking
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = OUTPUT_DIR / f"jlr_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_jobs([], output_path)
        return

    # Fetch descriptions
    if not args.no_description:
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
    output_path = OUTPUT_DIR / f"jlr_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
