#!/usr/bin/env python3
"""
Stripe Job Scraper

Extracts jobs from saved Stripe HTML and fetches full descriptions.

Usage:
    python scrapers/stripe_scraper.py
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
COMPANY_DIR = BASE_DIR / "Company_Pages" / "Stripe"
OUTPUT_DIR = BASE_DIR / "output"

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
    department: str = ""
    company: str = "Stripe"


def extract_jobs_from_listing(html_path: Path) -> list[Job]:
    """Extract job listings from saved HTML file."""
    print(f"Reading {html_path.name}...")

    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')
    jobs = []

    # Find all table rows with job listings
    for row in soup.find_all('tr', class_='TableRow'):
        # Job title and URL from link
        link = row.find('a', class_='JobsListings__link')
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link.get('href', '')

        # Extract job_id from URL (last part after final /)
        job_id = ""
        if url:
            match = re.search(r'/(\d+)$', url)
            if match:
                job_id = match.group(1)

        # Department from list item
        department = ""
        dept_el = row.find('li', class_='JobsListings__departmentsListItem')
        if dept_el:
            department = dept_el.get_text(strip=True)

        # Location from span
        location = ""
        loc_el = row.find('span', class_='JobsListings__locationDisplayName')
        if loc_el:
            location = loc_el.get_text(strip=True)

        if title and url:
            jobs.append(Job(
                title=title,
                location=location,
                url=url,
                job_id=job_id,
                department=department
            ))

    return jobs


def fetch_job_description(job: Job, session: requests.Session) -> bool:
    """Fetch full job description from job detail page."""
    try:
        print(f"  Fetching: {job.title[:50]}...")

        response = session.get(job.url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Get location from detail page (more accurate)
        loc_div = soup.find('div', class_='JobDetailCardProperty')
        if loc_div:
            loc_p = loc_div.find_all('p')
            if len(loc_p) >= 2:
                job.location = loc_p[1].get_text(strip=True)

        # Main job description is in ArticleMarkdown div
        description_parts = []

        # Primary: ArticleMarkdown contains the full job description
        article = soup.find('div', class_='ArticleMarkdown')
        if article:
            text = article.get_text(separator='\n', strip=True)
            if text:
                description_parts.append(text)

        # Also get Copy__body sections (In-office, Pay/benefits)
        for section in soup.find_all('div', class_='Copy__body'):
            text = section.get_text(separator='\n', strip=True)
            if text and len(text) > 50:
                description_parts.append(text)

        if description_parts:
            job.description = '\n\n'.join(description_parts)
        else:
            # Fallback: try finding any div with substantial content
            main_content = soup.find('main')
            if main_content:
                texts = []
                for el in main_content.find_all(['p', 'ul', 'ol', 'h2', 'h3']):
                    text = el.get_text(separator=' ', strip=True)
                    if text:
                        texts.append(text)
                if texts:
                    job.description = '\n'.join(texts)

        return bool(job.description)

    except requests.RequestException as e:
        print(f"    ERROR: {e}")
        return False


def save_jobs(jobs: list[Job], output_path: Path):
    """Save jobs to JSON file."""
    output_data = {
        "company": "Stripe",
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
    print("STRIPE JOB SCRAPER")
    print("=" * 60)

    # Find HTML files (exclude _files folders)
    html_files = [f for f in COMPANY_DIR.glob("*.html") if not f.name.endswith('_files')]
    if not html_files:
        print(f"No HTML files found in {COMPANY_DIR}")
        return

    # Extract all jobs from all listing files
    all_jobs = []
    seen_ids = set()

    for html_file in html_files:
        # Skip files that look like detail pages (have job titles as names)
        if 'Jobs' not in html_file.name:
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
        time.sleep(1)  # Be polite

    print(f"\nSuccessfully fetched {success_count}/{len(all_jobs)} descriptions")

    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"stripe_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_jobs(all_jobs, output_path)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for job in all_jobs[:10]:
        desc_preview = job.description[:50] + "..." if job.description else "(no description)"
        print(f"- {job.title[:40]}")
        print(f"  {job.location} | {job.department}")
        print(f"  {desc_preview}")

    if len(all_jobs) > 10:
        print(f"\n... and {len(all_jobs) - 10} more jobs")


if __name__ == "__main__":
    main()
