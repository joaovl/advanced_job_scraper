#!/usr/bin/env python3
"""
ARM Job Scraper (iCIMS Platform)

Scrapes jobs from ARM's careers site using Playwright (JavaScript required).

Usage:
    python scrapers/arm_scraper.py                    # All UK jobs
    python scrapers/arm_scraper.py --location Cambridge
    python scrapers/arm_scraper.py --all              # All worldwide
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
from typing import List, Optional

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

# ARM iCIMS careers site
BASE_URL = "https://careers.arm.com"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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
    posted_date: str = ""
    company: str = "ARM"




def extract_jobs_from_page(page, seen_ids: set) -> List[Job]:
    """Extract jobs from current page state."""
    jobs = []
    job_links = page.query_selector_all('a[href*="/job/"]')

    for link in job_links:
        try:
            href = link.get_attribute('href') or ""
            title = link.inner_text().strip()

            if not title or '/job/' not in href or len(title) < 3:
                continue

            # Extract job ID
            match = re.search(r'/(\d+)$', href)
            if not match:
                continue
            job_id = match.group(1)

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            url = href if href.startswith('http') else f"{BASE_URL}{href}"

            # Try to get location from parent li
            location_text = ""
            try:
                parent = link.evaluate_handle("el => el.closest('li')")
                if parent:
                    loc_el = parent.query_selector('.job-location, [class*="location"]')
                    if loc_el:
                        location_text = loc_el.inner_text().strip()
            except:
                pass

            jobs.append(Job(
                title=title,
                location=location_text,
                url=url,
                job_id=job_id
            ))
        except:
            continue

    return jobs


def fetch_all_jobs_playwright(location: str = "united kingdom") -> List[Job]:
    """Fetch all jobs using Playwright with URL-based pagination."""
    if not HAS_PLAYWRIGHT:
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    all_jobs = []
    seen_ids = set()

    # URL encode the location
    location_encoded = location.replace(" ", "%20") if location else ""
    base_search_url = f"{BASE_URL}/search-jobs/{location_encoded}" if location else f"{BASE_URL}/search-jobs"

    print(f"Fetching ARM jobs{' in ' + location if location else ' (all locations)'}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # First page to get total count
            page.goto(base_search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector('a[href*="/job/"]', timeout=15000)
            time.sleep(1)

            # Get total pages from pagination
            total_pages = 1
            total_pages_el = page.query_selector('.pagination-total-pages')
            if total_pages_el:
                text = total_pages_el.inner_text().strip()
                match = re.search(r'(\d+)', text)
                if match:
                    total_pages = int(match.group(1))
            print(f"Total pages: {total_pages}")

            # Extract jobs from first page
            new_jobs = extract_jobs_from_page(page, seen_ids)
            all_jobs.extend(new_jobs)
            print(f"  Page 1: {len(new_jobs)} jobs (total: {len(all_jobs)})")

            # Navigate through remaining pages using URL
            for pg in range(2, min(total_pages + 1, 20)):
                page_url = f"{base_search_url}/page-{pg}"

                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_selector('a[href*="/job/"]', timeout=10000)
                    time.sleep(0.5)

                    new_jobs = extract_jobs_from_page(page, seen_ids)
                    all_jobs.extend(new_jobs)
                    print(f"  Page {pg}: {len(new_jobs)} jobs (total: {len(all_jobs)})")

                    if len(new_jobs) == 0:
                        print("  No new jobs, stopping")
                        break
                except Exception as e:
                    print(f"  Page {pg}: error - {e}")
                    break

            print(f"\n  Total: {len(all_jobs)} unique jobs")

        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

    return all_jobs


def fetch_all_jobs(location: str = "united kingdom") -> List[Job]:
    """Fetch all jobs - uses Playwright if available, falls back to basic scraping."""
    if HAS_PLAYWRIGHT:
        return fetch_all_jobs_playwright(location)

    # Fallback: basic scraping (limited to first page)
    print("Warning: Playwright not available, using basic scraping (limited results)")
    all_jobs = []
    seen_ids = set()

    search_url = f"{BASE_URL}/search-jobs/{location}" if location else f"{BASE_URL}/search-jobs"
    print(f"Fetching ARM jobs{' in ' + location if location else ' (all locations)'}...")

    try:
        response = requests.get(search_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        for link in soup.select('a[href*="/job/"]'):
            href = link.get('href', '')
            title = link.get_text(strip=True)

            if not title or '/job/' not in href:
                continue

            match = re.search(r'/(\d+)$', href)
            if not match:
                continue
            job_id = match.group(1)

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            url = href if href.startswith('http') else f"{BASE_URL}{href}"
            all_jobs.append(Job(title=title, location="", url=url, job_id=job_id))

    except requests.RequestException as e:
        print(f"Error: {e}")

    print(f"  Found {len(all_jobs)} jobs (install Playwright for full results)")
    return all_jobs


def fetch_job_description(job: Job, session: requests.Session) -> bool:
    """Fetch full job description from job detail page."""
    if not job.url:
        return False

    try:
        response = session.get(job.url, headers={
            'User-Agent': HEADERS['User-Agent'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Try multiple selectors for job description
        description = ""
        selectors = [
            '.job-description',
            '.ats-description',
            '#job-description',
            '[class*="description"]',
            '.job-details',
            'article',
        ]

        for selector in selectors:
            desc_el = soup.select_one(selector)
            if desc_el:
                description = desc_el.get_text(separator='\n', strip=True)
                if len(description) > 100:
                    break

        if description:
            job.description = description

        # Try to get location if not set
        if not job.location:
            loc_el = soup.select_one('.job-location, [class*="location"]')
            if loc_el:
                job.location = loc_el.get_text(strip=True)

        # Get department
        if not job.department:
            dept_el = soup.select_one('.job-category, [class*="category"], [class*="department"]')
            if dept_el:
                job.department = dept_el.get_text(strip=True)

        return bool(description)

    except requests.RequestException as e:
        print(f"    Error: {e}")
        return False


def save_jobs(jobs: List[Job], output_path: Path):
    """Save jobs to JSON file."""
    output_data = {
        "company": "ARM",
        "scraped_at": datetime.now().isoformat(),
        "platform": "iCIMS",
        "total_jobs": len(jobs),
        "jobs_with_description": sum(1 for j in jobs if j.description),
        "jobs": [asdict(j) for j in jobs]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="ARM Job Scraper")
    parser.add_argument("--location", "-l", default="united kingdom",
                        help="Location filter (default: 'united kingdom')")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Fetch all locations worldwide")
    parser.add_argument("--no-description", "-nd", action="store_true",
                        help="Skip fetching job descriptions")
    args = parser.parse_args()

    print("=" * 60)
    print("ARM JOB SCRAPER (iCIMS)")
    print("=" * 60)

    # Fetch jobs
    location = "" if args.all else args.location
    all_jobs = fetch_all_jobs(location=location)

    print(f"\nFound {len(all_jobs)} unique jobs")

    if not all_jobs:
        print("No jobs found")
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = OUTPUT_DIR / f"arm_icims_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_jobs([], output_path)
        return

    # Fetch descriptions
    if not args.no_description:
        print("\nFetching job descriptions...")
        session = requests.Session()

        success_count = 0
        for i, job in enumerate(all_jobs, 1):
            print(f"[{i}/{len(all_jobs)}] {job.title[:50]}...", end="")
            if fetch_job_description(job, session):
                success_count += 1
                print(" OK")
            else:
                print(" (no desc)")
            time.sleep(0.5)  # Be polite

        print(f"\nFetched {success_count}/{len(all_jobs)} descriptions")

    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"arm_icims_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_jobs(all_jobs, output_path)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for job in all_jobs[:10]:
        print(f"- {job.title[:50]}")
        print(f"  {job.location}")

    if len(all_jobs) > 10:
        print(f"\n... and {len(all_jobs) - 10} more jobs")


if __name__ == "__main__":
    main()
