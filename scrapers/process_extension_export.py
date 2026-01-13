#!/usr/bin/env python3
"""
Process Chrome Extension Job Exports

Reads jobs_export.json from extension, fetches descriptions, and saves full output.
Also checks for any saved HTML files in the same folder for local description extraction.

Usage:
    python scrapers/process_extension_export.py <company_folder>
    python scrapers/process_extension_export.py Mercedes-Benz

Expects:
    Company_Pages/<company_folder>/jobs_export.json

Optionally uses:
    Company_Pages/<company_folder>/*.html (for local description extraction)
"""

import json
import time
import re
import sys
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent.parent
COMPANY_PAGES_DIR = BASE_DIR / "Company_Pages"
OUTPUT_DIR = BASE_DIR / "output"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def extract_description_from_html(html: str) -> str:
    """Extract job description from a detail page HTML."""
    soup = BeautifulSoup(html, 'html.parser')

    # Try various common patterns

    # Workable-style sections
    desc_section = soup.find('section', attrs={'data-ui': 'job-description'})
    if desc_section:
        parts = [desc_section.get_text(separator='\n', strip=True)]
        for section_name in ['job-requirements', 'job-benefits']:
            section = soup.find('section', attrs={'data-ui': section_name})
            if section:
                parts.append(section.get_text(separator='\n', strip=True))
        return '\n\n'.join(parts)

    # Greenhouse style
    for selector in ['#content', '.content', '#app_body']:
        content = soup.select_one(selector)
        if content:
            text = content.get_text(separator='\n', strip=True)
            if len(text) > 200:
                return text[:5000]

    # Lever style
    content = soup.find('div', class_=re.compile(r'posting-|content'))
    if content:
        text = content.get_text(separator='\n', strip=True)
        if len(text) > 200:
            return text[:5000]

    # Generic: look for main content areas
    for tag in ['main', 'article', '[role="main"]']:
        content = soup.select_one(tag)
        if content:
            text = content.get_text(separator='\n', strip=True)
            if len(text) > 200:
                return text[:5000]

    # Fallback: largest text block
    body = soup.find('body')
    if body:
        text = body.get_text(separator='\n', strip=True)
        # Clean up
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return '\n'.join(lines[:100])

    return ""


def fetch_description(url: str) -> str:
    """Fetch job description from URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return extract_description_from_html(resp.text)
    except Exception as e:
        print(f"    Error fetching {url}: {e}")
    return ""


def load_local_descriptions(folder: Path, jobs: list) -> dict:
    """Load descriptions from local HTML files in the folder."""
    descriptions = {}

    html_files = list(folder.glob('*.html')) + list(folder.glob('*.htm'))

    for html_file in html_files:
        try:
            html = html_file.read_text(encoding='utf-8', errors='ignore')
            filename = html_file.name.lower()

            # Try to match this HTML file to a job
            for job in jobs:
                job_url = job.get('url', '')
                job_title = job.get('title', '')
                job_id = job.get('job_id', '')

                # Skip if already have description for this job
                if job_url in descriptions:
                    continue

                matched = False

                # Method 1: URL appears in HTML (canonical link, og:url, etc.)
                if job_url and job_url in html:
                    matched = True

                # Method 2: Job ID appears in HTML
                if not matched and job_id and len(job_id) > 3 and job_id in html:
                    matched = True

                # Method 3: Job title matches filename (fuzzy)
                if not matched and job_title:
                    # Normalize both for comparison
                    title_words = set(re.findall(r'\w+', job_title.lower()))
                    file_words = set(re.findall(r'\w+', filename))
                    # If at least 3 words match or 60% overlap
                    common = title_words & file_words
                    if len(common) >= 3 or (len(title_words) > 0 and len(common) / len(title_words) >= 0.6):
                        matched = True

                # Method 4: Job title appears in page title or h1
                if not matched and job_title:
                    soup = BeautifulSoup(html, 'html.parser')
                    page_title = soup.find('title')
                    h1 = soup.find('h1')
                    title_lower = job_title.lower()
                    if page_title and title_lower in page_title.get_text().lower():
                        matched = True
                    elif h1 and title_lower in h1.get_text().lower():
                        matched = True

                if matched:
                    desc = extract_description_from_html(html)
                    if desc and len(desc) > 100:
                        descriptions[job_url] = desc
                        print(f"  Matched: {job_title[:40]} <- {html_file.name[:30]}")
                        break

        except Exception as e:
            print(f"  Error reading {html_file.name}: {e}")

    return descriptions


def is_navigation_item(job: dict) -> bool:
    """Check if a job entry is actually a navigation/info page link."""
    title = job.get('title', '').lower().strip()
    url = job.get('url', '').lower()

    # Navigation title patterns
    nav_titles = [
        'why ', 'working at', 'culture', 'benefits', 'belonging',
        'community', 'locations', 'teams', 'how we hire', 'open roles',
        'visit ', 'my settings', 'early careers', 'blog', 'research',
        'legal', 'first responders', 'candidate ', 'notice to',
        'zero tolerance', 'safety ', 'policy', 'g & a', 'g&a',
        'software engineering', 'ops & supply', 'ai foundations',
        'hardware engineering', 'product & design', 'about', 'contact',
        'privacy', 'terms', 'cookie', 'accessibility', 'waymo community'
    ]

    # URL patterns that indicate navigation
    nav_url_patterns = [
        '?page=', '?query=', '/search?', '/search#', 'search$',
        '#', 'javascript:'
    ]

    # Check title
    for nav in nav_titles:
        if title == nav.strip() or title.startswith(nav):
            return True

    # Check URL
    for pattern in nav_url_patterns:
        if pattern in url:
            return True

    # Very short titles are usually navigation
    if len(title) < 5:
        return True

    return False


def process_export(company_folder: str):
    """Process a Chrome extension export."""
    folder = COMPANY_PAGES_DIR / company_folder
    export_file = folder / "jobs_export.json"

    if not export_file.exists():
        print(f"Error: {export_file} not found")
        print(f"\nExpected path: {export_file}")
        print("\nMake sure you:")
        print("1. Used the Chrome extension to export jobs")
        print(f"2. Saved to Company_Pages/{company_folder}/jobs_export.json")
        sys.exit(1)

    print("=" * 60)
    print(f"{company_folder.upper()} - PROCESSING EXTENSION EXPORT")
    print("=" * 60)

    # Load export
    with open(export_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    jobs = data.get('jobs', [])
    original_count = len(jobs)

    # Filter out navigation items
    jobs = [j for j in jobs if not is_navigation_item(j)]
    filtered_count = original_count - len(jobs)

    if filtered_count > 0:
        print(f"Filtered out {filtered_count} navigation/info links")
    company_name = data.get('company', company_folder)

    print(f"Loaded {len(jobs)} jobs from export")

    # Check for local HTML files for descriptions
    print("\nChecking for local HTML files...")
    local_descriptions = load_local_descriptions(folder, jobs)
    print(f"Found {len(local_descriptions)} descriptions from local files")

    # Fetch remaining descriptions online
    jobs_needing_fetch = [j for j in jobs if j.get('url') not in local_descriptions and not j.get('description')]

    if jobs_needing_fetch:
        print(f"\nFetching {len(jobs_needing_fetch)} descriptions online...")

        for i, job in enumerate(jobs_needing_fetch):
            url = job.get('url', '')
            title = job.get('title', 'Unknown')[:40]
            print(f"[{i+1}/{len(jobs_needing_fetch)}] {title}...")

            desc = fetch_description(url)
            if desc:
                job['description'] = desc

            # Rate limiting
            time.sleep(0.5)

    # Apply local descriptions
    for job in jobs:
        url = job.get('url', '')
        if url in local_descriptions and not job.get('description'):
            job['description'] = local_descriptions[url]

    # Count descriptions
    jobs_with_desc = sum(1 for j in jobs if j.get('description'))
    data['jobs_with_description'] = jobs_with_desc
    data['jobs'] = jobs

    # Save output
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = company_folder.lower().replace(' ', '_').replace('-', '_')
    output_file = OUTPUT_DIR / f"{safe_name}_full_{timestamp}.json"

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_file}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total jobs: {len(jobs)}")
    print(f"With descriptions: {jobs_with_desc}/{len(jobs)}")
    print(f"\nJobs:")
    for job in jobs[:10]:
        title = job.get('title', '')[:45]
        loc = job.get('location', '')[:30]
        has_desc = "+" if job.get('description') else "-"
        print(f"  [{has_desc}] {title}")
        if loc:
            print(f"      {loc}")

    if len(jobs) > 10:
        print(f"  ... and {len(jobs) - 10} more")


def main():
    if len(sys.argv) < 2:
        print("Usage: python process_extension_export.py <company_folder>")
        print("\nExample:")
        print("  python scrapers/process_extension_export.py Mercedes-Benz")
        print("\nThis script expects:")
        print("  Company_Pages/<company_folder>/jobs_export.json")
        print("\nOptionally place HTML files in the same folder for local description extraction.")
        sys.exit(1)

    company_folder = sys.argv[1]
    process_export(company_folder)


if __name__ == '__main__':
    main()
