#!/usr/bin/env python3
"""
Remote Jobs Scraper

Scrapes job listings from remote job boards:
- WeWorkRemotely (RSS feeds)
- RemoteOK (JSON API)

Usage:
    python scrapers/remote_jobs_scraper.py                    # Run all sources
    python scrapers/remote_jobs_scraper.py --source wwr       # WeWorkRemotely only
    python scrapers/remote_jobs_scraper.py --source remoteok  # RemoteOK only
    python scrapers/remote_jobs_scraper.py --category dev     # Filter by category
"""

import json
import requests
import argparse
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# WeWorkRemotely categories with RSS feeds
WWR_CATEGORIES = {
    "programming": "remote-programming-jobs",
    "design": "remote-design-jobs",
    "devops": "remote-devops-sysadmin-jobs",
    "product": "remote-product-jobs",
    "customer-support": "remote-customer-support-jobs",
    "marketing": "remote-marketing-jobs",
    "sales": "remote-sales-jobs",
    "finance": "remote-finance-legal-jobs",
    "hr": "remote-hr-recruiting-jobs",
    "all": "remote-jobs",
}


def clean_html(html_text: str) -> str:
    """Strip HTML tags and clean whitespace."""
    if not html_text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def fetch_weworkremotely(categories: list = None) -> list:
    """Fetch jobs from WeWorkRemotely RSS feeds."""
    jobs = []
    categories = categories or ["programming", "devops", "product"]

    print(f"Fetching from WeWorkRemotely ({len(categories)} categories)...")

    for cat in categories:
        if cat not in WWR_CATEGORIES:
            print(f"  Unknown category: {cat}, skipping")
            continue

        url = f"https://weworkremotely.com/categories/{WWR_CATEGORIES[cat]}.rss"

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"  {cat}: HTTP {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, "xml")
            items = soup.find_all("item")

            for item in items:
                title_text = item.find("title").text if item.find("title") else ""

                # Extract company from title (format: "Company: Job Title")
                company = ""
                title = title_text
                if ": " in title_text:
                    parts = title_text.split(": ", 1)
                    company = parts[0].strip()
                    title = parts[1].strip()

                job = {
                    "title": title,
                    "company": company,
                    "location": item.find("region").text if item.find("region") else "Remote",
                    "category": item.find("category").text if item.find("category") else cat,
                    "url": item.find("link").text if item.find("link") else "",
                    "description": clean_html(item.find("description").text if item.find("description") else ""),
                    "posted": item.find("pubDate").text if item.find("pubDate") else "",
                    "source": "weworkremotely",
                }
                jobs.append(job)

            print(f"  {cat}: {len(items)} jobs")

        except Exception as e:
            print(f"  {cat}: Error - {e}")

    return jobs


def fetch_remoteok(tags: list = None) -> list:
    """Fetch jobs from RemoteOK JSON API."""
    jobs = []

    print("Fetching from RemoteOK API...")

    try:
        response = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"  HTTP {response.status_code}")
            return jobs

        data = response.json()

        # First item is legal notice, skip it
        for item in data[1:]:
            # Filter by tags if specified
            if tags:
                item_tags = [t.lower() for t in item.get("tags", [])]
                if not any(tag.lower() in item_tags for tag in tags):
                    continue

            job = {
                "title": item.get("position", ""),
                "company": item.get("company", ""),
                "location": item.get("location", "Remote"),
                "category": ", ".join(item.get("tags", [])[:3]),
                "url": item.get("url", ""),
                "description": clean_html(item.get("description", "")),
                "salary": item.get("salary_min", ""),
                "salary_max": item.get("salary_max", ""),
                "posted": item.get("date", ""),
                "source": "remoteok",
                "logo": item.get("company_logo", ""),
            }
            jobs.append(job)

        print(f"  Found {len(jobs)} jobs")

    except Exception as e:
        print(f"  Error: {e}")

    return jobs


def save_jobs(jobs: list, source: str) -> Path:
    """Save jobs to JSON file."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"{source}_remote_{timestamp}.json"

    output = {
        "source": source,
        "scraped_at": datetime.now().isoformat(),
        "total_jobs": len(jobs),
        "jobs": jobs
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output_file


def main():
    parser = argparse.ArgumentParser(description="Remote Jobs Scraper")
    parser.add_argument("--source", choices=["wwr", "remoteok", "all"], default="all",
                       help="Source to scrape")
    parser.add_argument("--category", help="Category filter (wwr: programming, devops, etc.)")
    parser.add_argument("--tags", help="Comma-separated tags filter (remoteok)")
    args = parser.parse_args()

    print("=" * 60)
    print("REMOTE JOBS SCRAPER")
    print("=" * 60)

    all_jobs = []

    # WeWorkRemotely
    if args.source in ["wwr", "all"]:
        categories = [args.category] if args.category else None
        wwr_jobs = fetch_weworkremotely(categories)
        all_jobs.extend(wwr_jobs)

        if wwr_jobs:
            output_file = save_jobs(wwr_jobs, "weworkremotely")
            print(f"\nSaved {len(wwr_jobs)} WWR jobs to {output_file}")

    # RemoteOK
    if args.source in ["remoteok", "all"]:
        tags = args.tags.split(",") if args.tags else None
        rok_jobs = fetch_remoteok(tags)
        all_jobs.extend(rok_jobs)

        if rok_jobs:
            output_file = save_jobs(rok_jobs, "remoteok")
            print(f"Saved {len(rok_jobs)} RemoteOK jobs to {output_file}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total jobs: {len(all_jobs)}")

    # Show sample jobs
    for job in all_jobs[:5]:
        print(f"\n- {job['title']}")
        print(f"  {job['company']} | {job['location']}")
        print(f"  {job['url'][:60]}...")


if __name__ == "__main__":
    main()
