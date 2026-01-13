#!/usr/bin/env python3
"""
HSBC Job Scraper

Fetches jobs directly from HSBC's Phenom People API.
Can filter by location (default: London, United Kingdom).

Usage:
    python scrapers/hsbc_scraper.py
    python scrapers/hsbc_scraper.py --location "New York"
    python scrapers/hsbc_scraper.py --all  # Get all jobs worldwide
"""

import json
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

# HSBC uses Phenom People platform
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}

# API base URL
API_BASE = "https://portal.careers.hsbc.com/api/apply/v2/jobs"


@dataclass
class Job:
    title: str
    location: str
    url: str
    job_id: str
    description: str = ""
    qualifications: str = ""
    department: str = ""
    business_unit: str = ""
    company: str = "HSBC"


def fetch_job_listings(location: str = None, fetch_all: bool = False) -> list[Job]:
    """Fetch job listings from HSBC API with pagination."""
    jobs = []
    start = 0
    page_size = 10  # API returns max 10 per request

    # Build query params
    params = {
        'domain': 'hsbc.com',
        'query': '*',
        'num': page_size,
    }
    if location and not fetch_all:
        params['location'] = location

    session = requests.Session()
    total_count = None

    print(f"Fetching job listings{f' for {location}' if location else ' (all locations)'}...")

    while True:
        params['start'] = start
        try:
            response = session.get(API_BASE, params=params, headers=HEADERS, timeout=15)
            response.raise_for_status()
            data = response.json()

            if total_count is None:
                total_count = data.get('count', 0)
                print(f"  Total available: {total_count} jobs")

            positions = data.get('positions', [])
            if not positions:
                break

            for pos in positions:
                job_id = str(pos.get('id', ''))
                jobs.append(Job(
                    title=pos.get('name', ''),
                    location=pos.get('location', ''),
                    url=f"https://portal.careers.hsbc.com/careers/job/{job_id}",
                    job_id=job_id,
                    department=pos.get('department', ''),
                    business_unit=pos.get('business_unit', ''),
                ))

            print(f"  Page {start // page_size + 1}: fetched {len(positions)} jobs (total: {len(jobs)})")

            start += page_size
            if len(jobs) >= total_count:
                break

            time.sleep(0.5)  # Be polite

        except requests.RequestException as e:
            print(f"  ERROR fetching page: {e}")
            break

    return jobs


def fetch_job_description(job: Job, session: requests.Session) -> bool:
    """Fetch full job description from HSBC JSON API."""
    if not job.job_id:
        return bool(job.description)

    try:
        print(f"  Fetching: {job.title[:50]}...")

        api_url = f"{API_BASE}/{job.job_id}"
        response = session.get(api_url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        data = response.json()

        # Update with detailed info
        if not job.title:
            job.title = data.get('name', '')
        if not job.location:
            job.location = data.get('location', '')
        if not job.department:
            job.department = data.get('department', '')
        if not job.business_unit:
            job.business_unit = data.get('business_unit', '')

        # Get description (comes as HTML)
        description_html = data.get('job_description', '')
        if description_html:
            soup = BeautifulSoup(description_html, 'html.parser')
            job.description = soup.get_text(separator='\n', strip=True)

        # Get qualifications
        qualifications_html = data.get('qualifications', '')
        if qualifications_html:
            soup = BeautifulSoup(qualifications_html, 'html.parser')
            job.qualifications = soup.get_text(separator='\n', strip=True)

        return bool(job.description)

    except requests.RequestException as e:
        print(f"    ERROR: {e}")
        return False
    except (json.JSONDecodeError, KeyError) as e:
        print(f"    ERROR parsing: {e}")
        return False


def save_jobs(jobs: list[Job], output_path: Path, location: str = None):
    """Save jobs to JSON file."""
    output_data = {
        "company": "HSBC",
        "location_filter": location or "All locations",
        "scraped_at": datetime.now().isoformat(),
        "total_jobs": len(jobs),
        "jobs_with_description": sum(1 for j in jobs if j.description),
        "jobs": [asdict(j) for j in jobs]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Scrape HSBC job listings")
    parser.add_argument('--location', '-l', default='London, United Kingdom',
                        help='Location to filter jobs (default: London, United Kingdom)')
    parser.add_argument('--all', '-a', action='store_true',
                        help='Fetch all jobs worldwide (ignores --location)')
    parser.add_argument('--no-descriptions', action='store_true',
                        help='Skip fetching full descriptions (faster)')
    args = parser.parse_args()

    print("=" * 60)
    print("HSBC JOB SCRAPER (Phenom People API)")
    print("=" * 60)

    # Fetch job listings
    location = None if args.all else args.location
    all_jobs = fetch_job_listings(location=location, fetch_all=args.all)

    print(f"\nFound {len(all_jobs)} jobs")

    if not all_jobs:
        print("No jobs to process")
        return

    # Fetch descriptions
    if not args.no_descriptions:
        print("\nFetching job descriptions...")
        session = requests.Session()

        success_count = 0
        for i, job in enumerate(all_jobs, 1):
            print(f"[{i}/{len(all_jobs)}]", end="")
            if fetch_job_description(job, session):
                success_count += 1
            time.sleep(0.5)  # Be polite

        print(f"\nSuccessfully fetched {success_count}/{len(all_jobs)} descriptions")

    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    loc_suffix = location.split(',')[0].lower().replace(' ', '_') if location else 'all'
    output_path = OUTPUT_DIR / f"hsbc_{loc_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_jobs(all_jobs, output_path, location)

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
