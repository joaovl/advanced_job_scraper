#!/usr/bin/env python3
"""
Savanta Job Scraper (BambooHR)

Extracts jobs from saved Savanta HTML and fetches full descriptions.

Usage:
    python scrapers/savanta_scraper.py
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
COMPANY_DIR = BASE_DIR / "Company_Pages" / "Savanta"
OUTPUT_DIR = BASE_DIR / "output"

# BambooHR is generally not heavily protected
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
    employment_type: str = ""
    company: str = "Savanta"


def extract_jobs_from_listing(html_path: Path) -> list[Job]:
    """Extract job listings from saved HTML file."""
    print(f"Reading {html_path.name}...")

    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')
    jobs = []
    seen_ids = set()

    # Try new Fabric/MUI structure first (2024+ layout)
    job_blocks = soup.select('div[data-fabric-component="LayoutEscapeHatch"]')

    for block in job_blocks:
        link = block.select_one('a.fab-LinkUnstyled, a[data-fabric-component="Link"]')
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link.get('href', '')

        # Skip generic CV/resume entries
        if 'send us' in title.lower() or 'cv' in title.lower() or 'resume' in title.lower():
            continue

        # Extract job ID from URL (e.g., /careers/507 -> 507)
        job_id_match = re.search(r'/careers/(\d+)', url)
        job_id = job_id_match.group(1) if job_id_match else ""

        if not job_id:
            continue

        # Find location - look for text like "London, London, City of (Hybrid)"
        location = ""
        location_texts = block.select('p[data-fabric-component="BodyText"]')
        for p in location_texts:
            text = p.get_text(strip=True)
            if 'London' in text or 'New York' in text or 'Toronto' in text or 'Remote' in text or 'Ontario' in text:
                location = text
                break

        # Find department - usually first BodyText after the title
        department = ""
        parent = link.find_parent('div', {'data-fabric-component': 'LayoutBox'})
        if parent:
            dept_el = parent.select_one('p[data-fabric-component="BodyText"]')
            if dept_el:
                department = dept_el.get_text(strip=True)

        # Make URL absolute if relative
        if url and not url.startswith('http'):
            url = f"https://savanta.bamboohr.com{url}"

        if title and job_id not in seen_ids:
            seen_ids.add(job_id)
            jobs.append(Job(
                title=title,
                location=location,
                url=url,
                job_id=job_id,
                department=department
            ))

    # Fallback: try old BambooHR structure
    if not jobs:
        for item in soup.select('.BambooHR-ATS-Jobs-Item'):
            link = item.select_one('a')
            location_el = item.select_one('.BambooHR-ATS-Location')
            department_el = item.select_one('.BambooHR-ATS-Department')

            if link:
                title = link.get_text(strip=True)
                url = link.get('href', '')
                location = location_el.get_text(strip=True) if location_el else ""
                department = department_el.get_text(strip=True) if department_el else ""

                # Skip generic entries
                if 'send us' in title.lower() or 'cv' in title.lower() or 'resume' in title.lower():
                    continue

                # Extract job ID from URL (e.g., /careers/127 -> 127)
                job_id_match = re.search(r'/careers/(\d+)', url)
                job_id = job_id_match.group(1) if job_id_match else ""

                # Make URL absolute if relative
                if url and not url.startswith('http'):
                    url = f"https://savanta.bamboohr.com{url}"

                if title:
                    jobs.append(Job(
                        title=title,
                        location=location,
                        url=url,
                        job_id=job_id,
                        department=department
                    ))

    return jobs


def fetch_job_description(job: Job, session: requests.Session) -> bool:
    """Fetch full job description from BambooHR JSON API."""
    if not job.job_id:
        return False

    try:
        print(f"  Fetching: {job.title[:50]}...")

        # BambooHR has a JSON API endpoint for job details
        api_url = f"https://savanta.bamboohr.com/careers/{job.job_id}/detail"
        api_headers = {
            'User-Agent': HEADERS['User-Agent'],
            'Accept': 'application/json',
        }

        response = session.get(api_url, headers=api_headers, timeout=15)
        response.raise_for_status()

        data = response.json()
        result = data.get('result', {})
        job_data = result.get('jobOpening', {})

        # Extract description (comes as HTML)
        description_html = job_data.get('description', '')
        if description_html:
            # Convert HTML to plain text
            soup = BeautifulSoup(description_html, 'html.parser')
            job.description = soup.get_text(separator='\n', strip=True)

        # Employment type
        job.employment_type = job_data.get('employmentStatusLabel', '')

        # Department
        if not job.department:
            job.department = job_data.get('departmentLabel', '')

        # Location (more detailed from API)
        location_data = job_data.get('location', {})
        if location_data:
            city = location_data.get('city', '')
            state = location_data.get('state', '')
            country = location_data.get('addressCountry', '')
            loc_parts = [p for p in [city, state, country] if p]
            if loc_parts:
                job.location = ', '.join(loc_parts)

        return bool(job.description)

    except requests.RequestException as e:
        print(f"    ERROR: {e}")
        return False
    except (json.JSONDecodeError, KeyError) as e:
        print(f"    ERROR parsing response: {e}")
        return False


def save_jobs(jobs: list[Job], output_path: Path):
    """Save jobs to JSON file."""
    output_data = {
        "company": "Savanta",
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
    print("SAVANTA JOB SCRAPER (BambooHR)")
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
    output_path = OUTPUT_DIR / f"savanta_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
