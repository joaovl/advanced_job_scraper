#!/usr/bin/env python3
"""
Export scraped jobs to n8n fintech_jobs.json format

This script reads all scraped job JSON files and exports them
to the format expected by the n8n LinkedIn Job Search workflow.

Usage:
    python export_to_n8n.py                    # Export all jobs
    python export_to_n8n.py --latest           # Export only most recent scrapes
    python export_to_n8n.py --company stripe   # Export specific company
    python export_to_n8n.py --filter london    # Filter by location
"""

import json
import argparse
import re
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
N8N_DIR = BASE_DIR / "N8n"
N8N_OUTPUT = N8N_DIR / "fintech_jobs.json"
COMPANY_PAGES_DIR = BASE_DIR / "Company_Pages"
LINKEDIN_DIR = BASE_DIR / "scrap_with_batch"  # LinkedIn scraper output


def is_valid_job(job: dict) -> bool:
    """Filter out navigation links and invalid job entries."""
    title = job.get('title', '').lower().strip()
    url = job.get('url', '')

    # Must have a title
    if not title:
        return False

    # Must have a URL
    if not url:
        return False

    # Skip navigation/info pages (common in Chrome extension exports)
    invalid_titles = [
        'why ', 'culture', 'benefits', 'belonging', 'teams',
        'how we hire', 'open roles', 'my settings', 'blog',
        'legal', 'privacy', 'locations', 'early careers',
        'visit ', 'candidate details', 'candidate privacy',
        'zero tolerance', 'safety publications', 'research',
        'first responders', 'community', 'notice to',
        'working at', 'g & a'
    ]
    if any(t in title for t in invalid_titles):
        return False

    # Skip very short titles (likely navigation)
    if len(title) < 5:
        return False

    return True


def load_all_jobs(latest_only: bool = False, company_filter: str = None) -> list:
    """Load jobs from output directory and Company_Pages folder."""
    all_jobs = []
    seen_urls = set()

    # Get all JSON files from output directory
    json_files = list(OUTPUT_DIR.glob("*.json"))

    # Also include Company_Pages JSON files
    if COMPANY_PAGES_DIR.exists():
        for json_file in COMPANY_PAGES_DIR.glob("**/*.json"):
            # Skip metadata files
            if json_file.name == "companies.json":
                continue
            json_files.append(json_file)
        print(f"Including Company_Pages folder in search")

    # Include LinkedIn scraper output
    if LINKEDIN_DIR.exists():
        linkedin_files = list(LINKEDIN_DIR.glob("linkedin_jobs_*.json"))
        if linkedin_files:
            json_files.extend(linkedin_files)
            print(f"Including {len(linkedin_files)} LinkedIn job file(s)")

    if not json_files:
        print("No JSON files found in output/")
        return []

    # Sort by modification time (newest first)
    json_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    # If latest_only, group by company and take only most recent
    if latest_only:
        latest_by_company = {}
        for f in json_files:
            # Extract company name from filename (first part before _)
            company = f.stem.split('_')[0].lower()
            if company not in latest_by_company:
                latest_by_company[company] = f
        json_files = list(latest_by_company.values())
        print(f"Using {len(json_files)} most recent files (one per company)")

    for json_file in json_files:
        # Skip combined/master files to avoid duplicates
        if 'combined' in json_file.name.lower() or 'master' in json_file.name.lower():
            continue
        if 'all_jobs' in json_file.name.lower():
            continue

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Handle both formats: {jobs: [...]} and [...]
            if isinstance(data, dict):
                jobs = data.get('jobs', [])
                company_name = data.get('company', json_file.stem.split('_')[0])
            elif isinstance(data, list):
                jobs = data
                company_name = json_file.stem.split('_')[0]
            else:
                continue

            # Apply company filter
            if company_filter:
                if company_filter.lower() not in company_name.lower():
                    continue

            for job in jobs:
                url = job.get('url', '')

                # Skip duplicates by URL
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)

                # Convert to n8n format
                n8n_job = {
                    "title": job.get('title', ''),
                    "company": job.get('company', company_name),
                    "url": url,
                    "description": job.get('description', ''),
                    "location": job.get('location', ''),
                    # Additional fields for filtering
                    "remote_type": job.get('remote_type', ''),
                    "time_type": job.get('time_type', ''),
                    "posted_date": job.get('posted_date', ''),
                    "job_id": job.get('job_id', '') or job.get('job_requisition_id', ''),
                    "department": job.get('department', ''),
                }

                # Only include valid jobs (filters out navigation links)
                if is_valid_job(n8n_job):
                    all_jobs.append(n8n_job)

        except Exception as e:
            print(f"Error reading {json_file.name}: {e}")
            continue

    return all_jobs


def filter_jobs(jobs: list, location_filter: str = None, title_filter: str = None) -> list:
    """Filter jobs by location or title keywords."""
    filtered = jobs

    if location_filter:
        location_lower = location_filter.lower()
        filtered = [
            j for j in filtered
            if location_lower in j.get('location', '').lower()
        ]
        print(f"Filtered to {len(filtered)} jobs in '{location_filter}'")

    if title_filter:
        title_lower = title_filter.lower()
        filtered = [
            j for j in filtered
            if title_lower in j.get('title', '').lower()
        ]
        print(f"Filtered to {len(filtered)} jobs matching title '{title_filter}'")

    return filtered


def export_to_n8n(jobs: list, output_path: Path = None):
    """Export jobs to n8n format."""
    output_path = output_path or N8N_OUTPUT

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    print(f"\nExported {len(jobs)} jobs to {output_path}")

    # Print summary by company
    companies = {}
    for job in jobs:
        company = job.get('company', 'Unknown')
        companies[company] = companies.get(company, 0) + 1

    print("\nJobs by company:")
    for company, count in sorted(companies.items(), key=lambda x: -x[1])[:20]:
        print(f"  {company}: {count}")

    if len(companies) > 20:
        print(f"  ... and {len(companies) - 20} more companies")


def main():
    parser = argparse.ArgumentParser(description="Export jobs to n8n format")
    parser.add_argument("--latest", action="store_true", help="Use only most recent file per company")
    parser.add_argument("--company", "-c", help="Filter by company name")
    parser.add_argument("--location", "-l", help="Filter by location (e.g., 'London')")
    parser.add_argument("--title", "-t", help="Filter by title keyword (e.g., 'Engineer')")
    parser.add_argument("--output", "-o", help="Output file path (default: N8n/fintech_jobs.json)")
    parser.add_argument("--list", action="store_true", help="List available JSON files")
    args = parser.parse_args()

    if args.list:
        print("Available JSON files:")
        for f in sorted(OUTPUT_DIR.glob("*.json")):
            size = f.stat().st_size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
            print(f"  {f.name} ({size:,} bytes, {mtime})")
        return

    print("=" * 60)
    print("EXPORT JOBS TO N8N")
    print("=" * 60)

    # Load jobs
    jobs = load_all_jobs(latest_only=args.latest, company_filter=args.company)
    print(f"Loaded {len(jobs)} total jobs")

    # Apply filters
    jobs = filter_jobs(jobs, location_filter=args.location, title_filter=args.title)

    if not jobs:
        print("No jobs to export!")
        return

    # Export
    output_path = Path(args.output) if args.output else N8N_OUTPUT
    export_to_n8n(jobs, output_path)

    print("\n" + "=" * 60)
    print("Next steps:")
    print("=" * 60)
    print("1. Start n8n: cd N8n && docker-compose up -d")
    print("2. Open n8n: http://localhost:5678")
    print("3. Run 'Fintech Manual Run' trigger")
    print("4. Results will be in N8n/output/ALL_FINTECH_*.xlsx")


if __name__ == "__main__":
    main()
