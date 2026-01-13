#!/usr/bin/env python3
"""
Enterprise Job Scraper
Scrapes jobs from major tech companies that use custom career platforms.

Supports: Cisco, Google, IBM, and other non-Workday companies.

Usage:
    python scrapers/enterprise_scraper.py --company cisco --location London
    python scrapers/enterprise_scraper.py --company google --location "London, UK"
    python scrapers/enterprise_scraper.py --company ibm --location "United Kingdom"
    python scrapers/enterprise_scraper.py --all --location London
"""

import json
import requests
import argparse
import time
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlencode, quote_plus

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Company configurations
COMPANIES = {
    "cisco": {
        "name": "Cisco",
        "type": "eightfold",
        "search_url": "https://jobs.cisco.com/jobs/SearchJobs/?21176=%5B169552%5D&21176_format=1482&listFilterMode=1",  # UK filter
        "api_base": "https://jobs.cisco.com",
        "careers_url": "https://careers.cisco.com/global/en/search-results",
    },
    "google": {
        "name": "Google",
        "type": "google",
        "search_url": "https://www.google.com/about/careers/applications/jobs/results",
        "careers_url": "https://www.google.com/about/careers/applications/jobs/results?location=London%2C%20UK",
    },
    "ibm": {
        "name": "IBM",
        "type": "ibm",
        "api_url": "https://careers.ibm.com/api/search",
        "careers_url": "https://www.ibm.com/uk-en/careers/search",
    },
    "meta": {
        "name": "Meta",
        "type": "meta",
        "careers_url": "https://www.metacareers.com/jobs?offices[0]=London%2C%20UK",
    },
    "amazon": {
        "name": "Amazon",
        "type": "amazon",
        "api_url": "https://www.amazon.jobs/en-gb/search.json",
        "careers_url": "https://www.amazon.jobs/en-gb/locations/london-england",
    },
    "apple": {
        "name": "Apple",
        "type": "apple",
        "api_url": "https://jobs.apple.com/api/role/search",
        "careers_url": "https://jobs.apple.com/en-gb/search?location=london-LND",
    },
}


def scrape_amazon(location="London", limit=100):
    """Scrape Amazon jobs using their API."""
    print(f"Scraping Amazon jobs in {location}...")

    jobs = []
    offset = 0

    while len(jobs) < limit:
        params = {
            "facets[]": ["location", "business_category", "category", "schedule_type_id"],
            "offset": offset,
            "result_limit": 25,
            "sort": "relevant",
            "city[]": [location],
            "country[]": ["GBR"],
            "latitude": "",
            "longitude": "",
            "loc_group_id": "",
            "loc_query": location,
            "base_query": "",
            "query": "",
            "normalized_location[]": [f"{location}, England, GBR"],
            "radius": "24km"
        }

        try:
            resp = requests.get(
                "https://www.amazon.jobs/en-gb/search.json",
                params=params,
                headers=HEADERS,
                timeout=30
            )

            if resp.status_code != 200:
                print(f"  Error: Status {resp.status_code}")
                break

            data = resp.json()
            job_list = data.get("jobs", [])

            if not job_list:
                break

            for job in job_list:
                jobs.append({
                    "title": job.get("title", ""),
                    "location": job.get("normalized_location", job.get("city", "")),
                    "url": f"https://www.amazon.jobs{job.get('job_path', '')}",
                    "job_id": job.get("id_icims", ""),
                    "description": job.get("description_short", ""),
                    "posted_date": job.get("posted_date", ""),
                    "company": "Amazon"
                })

            print(f"  Fetched {len(jobs)} jobs...")

            if len(job_list) < 25:
                break

            offset += 25
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error: {e}")
            break

    return jobs


def scrape_apple(location="london-LND", limit=100):
    """Scrape Apple jobs using their API."""
    print(f"Scraping Apple jobs in {location}...")

    jobs = []
    page = 1

    headers = {
        **HEADERS,
        'Content-Type': 'application/json',
    }

    while len(jobs) < limit:
        payload = {
            "query": "",
            "filters": {
                "range": {
                    "standardWeeklyHours": {"start": None, "end": None}
                },
                "location": [{
                    "type": "location",
                    "value": location
                }]
            },
            "page": page,
            "locale": "en-gb",
            "sort": "relevance"
        }

        try:
            resp = requests.post(
                "https://jobs.apple.com/api/role/search",
                json=payload,
                headers=headers,
                timeout=30
            )

            if resp.status_code != 200:
                print(f"  Error: Status {resp.status_code}")
                break

            data = resp.json()
            results = data.get("searchResults", [])

            if not results:
                break

            for job in results:
                transform = job.get("transformedPostingTitle", "")
                posting_title = job.get("postingTitle", transform)

                locations = job.get("locations", [])
                loc_str = ", ".join([loc.get("name", "") for loc in locations[:3]])

                jobs.append({
                    "title": posting_title,
                    "location": loc_str,
                    "url": f"https://jobs.apple.com/en-gb/details/{job.get('positionId', '')}",
                    "job_id": job.get("positionId", ""),
                    "description": "",
                    "team": job.get("team", {}).get("teamName", ""),
                    "company": "Apple"
                })

            print(f"  Fetched {len(jobs)} jobs...")

            total = data.get("totalRecords", 0)
            if len(jobs) >= total:
                break

            page += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error: {e}")
            break

    return jobs


def scrape_cisco_html(location="London"):
    """Scrape Cisco jobs by parsing their search results page."""
    print(f"Scraping Cisco jobs in {location}...")

    # Cisco uses a complex JS-rendered page, try fetching with filters
    # UK location ID is 169552
    url = f"https://jobs.cisco.com/jobs/SearchJobs/?21176=%5B169552%5D&21176_format=1482&listFilterMode=1&projectOffset=0"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        print(f"  Status: {resp.status_code}, URL: {resp.url[:60]}")

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')

            jobs = []
            # Look for job listings
            for job_el in soup.select('.job-listing, .job-card, [data-job-id], .searchJobsResults tr'):
                title_el = job_el.select_one('a.job-title, .job-title a, h2 a, td a')
                if title_el:
                    title = title_el.get_text(strip=True)
                    url = title_el.get('href', '')
                    if not url.startswith('http'):
                        url = f"https://jobs.cisco.com{url}"

                    loc_el = job_el.select_one('.location, .job-location, td:nth-child(2)')
                    location = loc_el.get_text(strip=True) if loc_el else ""

                    jobs.append({
                        "title": title,
                        "location": location,
                        "url": url,
                        "job_id": "",
                        "description": "",
                        "company": "Cisco"
                    })

            print(f"  Found {len(jobs)} jobs from HTML")
            return jobs

    except Exception as e:
        print(f"  Error: {e}")

    return []


def scrape_google_html(location="London, UK"):
    """Scrape Google jobs - note: requires JavaScript rendering."""
    print(f"Scraping Google jobs in {location}...")
    print("  Note: Google careers requires JavaScript. Results may be limited.")

    # Google's careers page is heavily JS-rendered
    # We can try their direct URL format
    url = f"https://www.google.com/about/careers/applications/jobs/results?location={quote_plus(location)}&has_remote=true"

    jobs = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        print(f"  Status: {resp.status_code}")

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')

            # Try to find job data in the page
            for script in soup.find_all('script'):
                text = script.string or ""
                if 'jobsData' in text or 'positions' in text:
                    # Try to extract JSON
                    match = re.search(r'jobsData\s*=\s*(\[.*?\]);', text, re.DOTALL)
                    if match:
                        try:
                            data = json.loads(match.group(1))
                            for job in data:
                                jobs.append({
                                    "title": job.get("title", ""),
                                    "location": job.get("location", ""),
                                    "url": job.get("url", ""),
                                    "job_id": job.get("id", ""),
                                    "description": job.get("description", ""),
                                    "company": "Google"
                                })
                        except:
                            pass

            # Fallback: parse visible HTML
            if not jobs:
                for job_el in soup.select('[data-job-id], .gc-card, .job-result'):
                    title_el = job_el.select_one('h3, .gc-card__title, .job-title')
                    if title_el:
                        title = title_el.get_text(strip=True)
                        link = job_el.select_one('a')
                        url = link.get('href', '') if link else ""

                        loc_el = job_el.select_one('.gc-card__location, .job-location')
                        location = loc_el.get_text(strip=True) if loc_el else ""

                        jobs.append({
                            "title": title,
                            "location": location,
                            "url": f"https://www.google.com{url}" if url and not url.startswith('http') else url,
                            "job_id": "",
                            "description": "",
                            "company": "Google"
                        })

        print(f"  Found {len(jobs)} jobs")

    except Exception as e:
        print(f"  Error: {e}")

    return jobs


def scrape_ibm(location="United Kingdom", limit=200):
    """Scrape IBM jobs."""
    print(f"Scraping IBM jobs in {location}...")

    jobs = []

    # IBM's new API endpoint
    api_url = "https://careers.ibm.com/search-api/jobs"

    params = {
        "query": "",
        "country": location,
        "offset": 0,
        "limit": 50,
    }

    try:
        resp = requests.get(api_url, params=params, headers=HEADERS, timeout=30)
        print(f"  Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", data.get("jobs", []))

            for job in results:
                jobs.append({
                    "title": job.get("title", ""),
                    "location": job.get("location", job.get("city", "")),
                    "url": job.get("url", job.get("apply_url", "")),
                    "job_id": job.get("id", job.get("job_id", "")),
                    "description": job.get("description", ""),
                    "company": "IBM"
                })

            print(f"  Found {len(jobs)} jobs")

    except Exception as e:
        print(f"  Error: {e}")

        # Fallback: try the old avature endpoint
        print("  Trying Avature endpoint...")
        try:
            avature_url = "https://ibmglobal.avature.net/api/v1/pipelines/careers/jobs"
            resp = requests.get(avature_url, params={"country": location}, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                for job in data.get("data", []):
                    jobs.append({
                        "title": job.get("title", ""),
                        "location": job.get("location", ""),
                        "url": job.get("url", ""),
                        "job_id": str(job.get("id", "")),
                        "description": "",
                        "company": "IBM"
                    })
        except:
            pass

    return jobs


def scrape_company(company_key, location="London", limit=100):
    """Scrape jobs for a specific company."""

    if company_key not in COMPANIES:
        print(f"Unknown company: {company_key}")
        print(f"Available: {', '.join(COMPANIES.keys())}")
        return None

    config = COMPANIES[company_key]
    print("=" * 60)
    print(f"{config['name'].upper()} JOB SCRAPER")
    print("=" * 60)

    jobs = []

    if company_key == "amazon":
        jobs = scrape_amazon(location, limit)
    elif company_key == "apple":
        # Apple uses location codes like "london-LND"
        loc_code = "london-LND" if "london" in location.lower() else location
        jobs = scrape_apple(loc_code, limit)
    elif company_key == "cisco":
        jobs = scrape_cisco_html(location)
    elif company_key == "google":
        jobs = scrape_google_html(location)
    elif company_key == "ibm":
        jobs = scrape_ibm(location, limit)
    else:
        print(f"No scraper implemented for {company_key}")
        return None

    if not jobs:
        print(f"\nNo jobs found for {config['name']} in {location}")
        print(f"Try visiting: {config['careers_url']}")
        return {
            "company": config["name"],
            "scraped_at": datetime.now().isoformat(),
            "location_searched": location,
            "total_jobs": 0,
            "jobs": [],
            "note": "This company uses JavaScript-heavy pages. Manual scraping or Selenium may be required."
        }

    # Build output
    output = {
        "company": config["name"],
        "scraped_at": datetime.now().isoformat(),
        "location_searched": location,
        "careers_url": config.get("careers_url", ""),
        "total_jobs": len(jobs),
        "jobs": jobs
    }

    return output


def main():
    parser = argparse.ArgumentParser(description="Enterprise Job Scraper")
    parser.add_argument("--company", "-c", help="Company to scrape (cisco, google, ibm, amazon, apple)")
    parser.add_argument("--location", "-l", default="London", help="Location to search")
    parser.add_argument("--limit", type=int, default=100, help="Max jobs to fetch")
    parser.add_argument("--list", action="store_true", help="List available companies")
    parser.add_argument("--all", "-a", action="store_true", help="Scrape all companies")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.list:
        print("Available companies:")
        for key, config in COMPANIES.items():
            print(f"  {key:15} - {config['name']}")
        return

    companies_to_scrape = []

    if args.company:
        companies_to_scrape = [args.company.lower()]
    elif args.all:
        companies_to_scrape = list(COMPANIES.keys())
    else:
        print("Specify --company NAME or --all")
        print("Use --list to see available companies")
        return

    for company_key in companies_to_scrape:
        result = scrape_company(company_key, args.location, args.limit)

        if result:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = OUTPUT_DIR / f"{company_key}_enterprise_{timestamp}.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"\nSaved to {output_file}")

            if result["total_jobs"] > 0:
                print(f"\nSample jobs:")
                for job in result["jobs"][:5]:
                    print(f"  - {job['title'][:50]}")
                    print(f"    {job['location']}")
                if result["total_jobs"] > 5:
                    print(f"\n  ... and {result['total_jobs'] - 5} more jobs")

        print()


if __name__ == "__main__":
    main()
