#!/usr/bin/env python3
"""
Playwright-based Job Scraper
For JavaScript-heavy career sites that require browser rendering.

Supports: Cisco, Google, IBM, Apple, Meta

Usage:
    python scrapers/playwright_scraper.py --company cisco --location London
    python scrapers/playwright_scraper.py --company google --location London
    python scrapers/playwright_scraper.py --company ibm --location "United Kingdom"
    python scrapers/playwright_scraper.py --all --location London
"""

import json
import argparse
import asyncio
import re
import time
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

# Company configurations with selectors
COMPANIES = {
    "cisco": {
        "name": "Cisco",
        "url": "https://jobs.cisco.com/jobs/SearchJobs/?21176=%5B169552%5D&21176_format=1482&listFilterMode=1",
        "url_template": "https://jobs.cisco.com/jobs/SearchJobs/?21176=%5B169552%5D&21176_format=1482&listFilterMode=1&projectOffset={offset}",
        "wait_selector": ".searchJobsResults, .job-results, table tbody tr",
        "job_selector": "table.searchJobsResults tbody tr, .job-card, .job-listing",
        "title_selector": "td:first-child a, .job-title a, h3 a",
        "location_selector": "td:nth-child(2), .job-location, .location",
        "link_selector": "td:first-child a, .job-title a, h3 a",
        "next_page": ".pagination .next, a[aria-label='Next']",
        "base_url": "https://jobs.cisco.com",
    },
    "google": {
        "name": "Google",
        "url": "https://www.google.com/about/careers/applications/jobs/results?location=London%2C%20UK",
        "wait_selector": "[data-job-id], .gc-card, .lLd2eb",
        "job_selector": "[data-job-id], .gc-card, li.lLd2eb",
        "title_selector": "h3, .QJPWVe, .gc-card__title",
        "location_selector": ".pwO9Dc, .gc-card__detail, span:has-text('London')",
        "link_selector": "a",
        "base_url": "https://www.google.com",
    },
    "ibm": {
        "name": "IBM",
        "url": "https://www.ibm.com/careers/search?field_keyword_05[0]=United%20Kingdom",
        "wait_selector": ".bx--card, .job-card, [data-job-id], .job-listing",
        "job_selector": ".bx--card, .job-card, [data-job-id], article",
        "title_selector": "h3, .job-title, .bx--card__heading",
        "location_selector": ".job-location, .location, p:has-text('United Kingdom')",
        "link_selector": "a",
        "base_url": "https://www.ibm.com",
    },
    "apple": {
        "name": "Apple",
        "url": "https://jobs.apple.com/en-gb/search?location=london-GBR",
        "wait_selector": "table#jobs-table tbody tr, .table-row, [role='row']",
        "job_selector": "table#jobs-table tbody tr, .results-table tbody tr",
        "title_selector": "td:first-child a, .table-col-1 a",
        "location_selector": "td:nth-child(2), .table-col-2",
        "link_selector": "td:first-child a, a.table-col-1",
        "base_url": "https://jobs.apple.com",
    },
    "meta": {
        "name": "Meta",
        "url": "https://www.metacareers.com/jobs?offices[0]=London%2C%20UK",
        "wait_selector": "[data-testid='job-card'], .job-card, ._8sel",
        "job_selector": "[data-testid='job-card'], .job-card, ._8sel",
        "title_selector": "a div, .job-title, ._8seo",
        "location_selector": ".job-location, ._8sep",
        "link_selector": "a",
        "base_url": "https://www.metacareers.com",
    },
}


async def scrape_cisco(page, location="London", max_jobs=200):
    """Scrape Cisco jobs from their new careers site."""
    jobs = []

    print(f"  Navigating to Cisco careers...")

    # Use the search results page with UK filter
    url = f"https://careers.cisco.com/global/en/search-results?keywords=&location={location}%2C%20United%20Kingdom"
    await page.goto(url, wait_until="networkidle", timeout=60000)

    # Wait for content to load
    await asyncio.sleep(3)

    # Scroll to load more jobs
    for _ in range(10):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)

    # Try to click "Show more" button if available
    try:
        for _ in range(10):
            show_more = await page.query_selector("button:has-text('Show more'), [data-ph-at-load-more-jobs-btn]")
            if show_more:
                await show_more.click()
                await asyncio.sleep(1)
            else:
                break
    except:
        pass

    # Extract job cards
    job_cards = await page.query_selector_all("a[href*='/job/']")

    print(f"  Found {len(job_cards)} job links")

    seen_urls = set()
    for card in job_cards:
        try:
            href = await card.get_attribute("href")
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            # Get job title from the link text or parent
            title = await card.inner_text()
            title = title.strip()

            # Skip navigation links
            if len(title) < 5 or title.lower() in ['apply', 'view', 'details']:
                continue

            if not href.startswith("http"):
                href = f"https://careers.cisco.com{href}"

            # Try to get location from nearby element
            parent = await card.evaluate_handle("el => el.closest('[data-ph-at-job-card]') || el.parentElement")
            location_text = location

            try:
                loc_el = await parent.query_selector("[data-ph-at-job-location-text], .job-location")
                if loc_el:
                    location_text = await loc_el.inner_text()
            except:
                pass

            jobs.append({
                "title": title,
                "location": location_text.strip(),
                "url": href,
                "posted_date": "",
                "job_id": "",
                "description": "",
                "company": "Cisco"
            })

            if len(jobs) >= max_jobs:
                break

        except Exception as e:
            continue

    # If no jobs found with location filter, try category pages
    if len(jobs) == 0:
        print("  No jobs found, trying category pages...")
        categories = ["engineering-software-jobs", "sales-jobs", "it-jobs", "support-jobs"]

        for cat in categories:
            cat_url = f"https://careers.cisco.com/global/en/c/{cat}"
            await page.goto(cat_url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)

            # Scroll to load
            for _ in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)

            job_cards = await page.query_selector_all("a[href*='/job/']")

            for card in job_cards:
                try:
                    href = await card.get_attribute("href")
                    if not href or href in seen_urls:
                        continue
                    seen_urls.add(href)

                    title = await card.inner_text()
                    title = title.strip()

                    if len(title) < 5:
                        continue

                    if not href.startswith("http"):
                        href = f"https://careers.cisco.com{href}"

                    # Check if job is in UK/London (from title or location)
                    parent = await card.evaluate_handle("el => el.closest('[data-ph-at-job-card]') || el.parentElement")
                    location_text = ""
                    try:
                        loc_el = await parent.query_selector("[data-ph-at-job-location-text], .job-location")
                        if loc_el:
                            location_text = await loc_el.inner_text()
                    except:
                        pass

                    # Filter for UK jobs
                    if location.lower() in location_text.lower() or "uk" in location_text.lower() or "united kingdom" in location_text.lower():
                        jobs.append({
                            "title": title,
                            "location": location_text.strip(),
                            "url": href,
                            "posted_date": "",
                            "job_id": "",
                            "description": "",
                            "company": "Cisco"
                        })

                except:
                    continue

            print(f"    Category {cat}: found {len(jobs)} UK jobs total")

            if len(jobs) >= max_jobs:
                break

    return jobs


async def scrape_google(page, location="London, UK", max_jobs=100):
    """Scrape Google jobs."""
    jobs = []

    url = f"https://www.google.com/about/careers/applications/jobs/results?location={location.replace(' ', '%20').replace(',', '%2C')}"
    print(f"  Navigating to Google careers...")

    await page.goto(url, wait_until="networkidle", timeout=60000)

    # Wait for job titles to load
    try:
        await page.wait_for_selector("h3.QJPWVe", timeout=15000)
    except PlaywrightTimeout:
        print("  Waiting for jobs to load...")
        await asyncio.sleep(5)

    # Scroll to load more jobs
    for _ in range(10):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)

    # Google's career page shows jobs in a list with h3.QJPWVe for titles
    # Each job is a clickable card - we need to click each one to get details
    # Alternative: extract data-* attributes or find the unique identifiers

    job_titles = await page.query_selector_all("h3.QJPWVe")
    print(f"  Found {len(job_titles)} job titles")

    seen_titles = set()
    for h3 in job_titles[:max_jobs]:
        try:
            title = await h3.inner_text()
            title = title.strip()

            if not title or title in seen_titles:
                continue
            seen_titles.add(title)

            # Get the closest ancestor with job data
            parent = await h3.evaluate_handle("""el => {
                let p = el.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (p && (p.getAttribute('data-id') || p.querySelector('a[href*=\"jobs/results\"]'))) {
                        return p;
                    }
                    p = p?.parentElement;
                }
                return el.parentElement?.parentElement;
            }""")

            # Get location - clean up the "place" icon text
            location_text = location
            try:
                loc_el = await parent.query_selector(".pwO9Dc, [class*='r0wTof']")
                if loc_el:
                    raw_loc = await loc_el.inner_text()
                    # Remove icon text like "place"
                    location_text = raw_loc.replace("place", "").strip()
            except:
                pass

            # Try to get a unique URL for this job
            # Google uses SPA navigation, so we need to construct the URL
            href = ""
            try:
                # Get the job ID from data attribute or URL pattern
                job_id = await parent.evaluate("el => el.getAttribute('data-id') || ''")
                if job_id:
                    href = f"https://www.google.com/about/careers/applications/jobs/results/{job_id}"
                else:
                    # Try to find a link
                    link_el = await parent.query_selector("a[href*='jobs/results']")
                    if link_el:
                        href = await link_el.get_attribute("href")
                        if href and not href.startswith("http"):
                            href = f"https://www.google.com/about/careers/applications/{href}"
            except:
                pass

            # If no specific URL, use the search results page
            if not href:
                # Construct URL from title (Google's URL pattern)
                title_slug = title.lower().replace(" ", "-").replace(",", "")[:50]
                href = f"https://www.google.com/about/careers/applications/jobs/results?location={location}&q={title_slug}"

            jobs.append({
                "title": title,
                "location": location_text,
                "url": href,
                "job_id": "",
                "description": "",
                "company": "Google"
            })

        except Exception as e:
            continue

    return jobs


async def scrape_ibm(page, location="United Kingdom", max_jobs=200):
    """Scrape IBM jobs."""
    jobs = []

    # Use the UK-specific URL
    url = f"https://www.ibm.com/uk-en/careers/search?field_keyword_05[0]={location.replace(' ', '%20')}"
    print(f"  Navigating to IBM careers...")

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Wait for job cards
    try:
        await page.wait_for_selector(".bx--card, [class*='job-card']", timeout=15000)
    except PlaywrightTimeout:
        print("  Waiting for jobs to load...")
        await asyncio.sleep(5)

    # Scroll to load more
    for _ in range(15):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)

    # Try to click "Load more" if available
    try:
        for _ in range(10):
            load_more = await page.query_selector("button:has-text('Load more'), button:has-text('Show more'), .bx--btn--primary")
            if load_more:
                visible = await load_more.is_visible()
                if visible:
                    await load_more.click()
                    await asyncio.sleep(1)
                else:
                    break
            else:
                break
    except:
        pass

    # Extract jobs from bx--card elements
    job_cards = await page.query_selector_all(".bx--card")

    print(f"  Found {len(job_cards)} card elements")

    seen_titles = set()
    for card in job_cards:
        try:
            # Get title from h3/h4 in card
            title_el = await card.query_selector("h3, h4, .bx--card__heading")
            if not title_el:
                continue

            title = await title_el.inner_text()
            title = title.strip()

            # Skip non-job cards (navigation, etc)
            if not title or len(title) < 5 or title in seen_titles:
                continue
            if title.lower() in ['search jobs', 'explore careers', 'learn more']:
                continue
            seen_titles.add(title)

            # Get link
            link_el = await card.query_selector("a")
            href = ""
            if link_el:
                href = await link_el.get_attribute("href")
                if href and not href.startswith("http"):
                    href = f"https://www.ibm.com{href}"

            # Skip if not a job link
            if href and "job" not in href.lower() and "career" not in href.lower():
                continue

            # Get location from card
            location_text = location
            loc_el = await card.query_selector("p, .bx--card__copy, [class*='location']")
            if loc_el:
                loc_text = await loc_el.inner_text()
                if loc_text and len(loc_text) < 100:
                    location_text = loc_text.strip()

            jobs.append({
                "title": title[:200],
                "location": location_text,
                "url": href,
                "job_id": "",
                "description": "",
                "company": "IBM"
            })

            if len(jobs) >= max_jobs:
                break

        except Exception as e:
            continue

    return jobs


async def scrape_apple(page, location="london-GBR", max_jobs=100):
    """Scrape Apple jobs."""
    jobs = []

    url = f"https://jobs.apple.com/en-gb/search?location={location}"
    print(f"  Navigating to Apple careers...")

    await page.goto(url, wait_until="networkidle", timeout=60000)

    # Wait for table
    try:
        await page.wait_for_selector("table#jobs-table tbody tr, .table-row", timeout=15000)
    except PlaywrightTimeout:
        print("  Waiting for jobs to load...")
        await asyncio.sleep(3)

    # Scroll to load more
    for _ in range(5):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)

    # Extract jobs
    rows = await page.query_selector_all("table#jobs-table tbody tr")

    if not rows:
        rows = await page.query_selector_all(".results-table tbody tr, [role='row']")

    print(f"  Found {len(rows)} job rows")

    for row in rows[:max_jobs]:
        try:
            title_el = await row.query_selector("td:first-child a, .table-col-1 a")
            loc_el = await row.query_selector("td:nth-child(2), .table-col-2")
            date_el = await row.query_selector("td:nth-child(3), .table-col-3")

            if title_el:
                title = await title_el.inner_text()
                href = await title_el.get_attribute("href")
                location_text = await loc_el.inner_text() if loc_el else ""
                date_text = await date_el.inner_text() if date_el else ""

                if href and not href.startswith("http"):
                    href = f"https://jobs.apple.com{href}"

                jobs.append({
                    "title": title.strip(),
                    "location": location_text.strip(),
                    "url": href,
                    "posted_date": date_text.strip(),
                    "job_id": "",
                    "description": "",
                    "company": "Apple"
                })
        except Exception as e:
            continue

    return jobs


async def scrape_meta(page, location="London, UK", max_jobs=100):
    """Scrape Meta/Facebook jobs."""
    jobs = []

    url = f"https://www.metacareers.com/jobs?offices[0]={location.replace(' ', '%20').replace(',', '%2C')}"
    print(f"  Navigating to Meta careers...")

    await page.goto(url, wait_until="networkidle", timeout=60000)

    # Wait for job cards
    try:
        await page.wait_for_selector("[data-testid='job-card'], ._8sel, .job-card", timeout=15000)
    except PlaywrightTimeout:
        print("  Waiting for jobs to load...")
        await asyncio.sleep(5)

    # Scroll to load more
    for _ in range(10):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)

    # Extract jobs
    job_cards = await page.query_selector_all("[data-testid='job-card'], ._8sel")

    print(f"  Found {len(job_cards)} job elements")

    for card in job_cards[:max_jobs]:
        try:
            link_el = await card.query_selector("a")
            if not link_el:
                continue

            href = await link_el.get_attribute("href")

            # Get all text and try to parse
            text = await card.inner_text()
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            title = lines[0] if lines else ""
            location_text = lines[1] if len(lines) > 1 else ""

            if href and not href.startswith("http"):
                href = f"https://www.metacareers.com{href}"

            if title:
                jobs.append({
                    "title": title.strip(),
                    "location": location_text.strip(),
                    "url": href,
                    "job_id": "",
                    "description": "",
                    "company": "Meta"
                })
        except Exception as e:
            continue

    return jobs


async def scrape_company(company_key: str, location: str = "London", max_jobs: int = 100, headless: bool = True):
    """Main scraping function."""

    if company_key not in COMPANIES:
        print(f"Unknown company: {company_key}")
        print(f"Available: {', '.join(COMPANIES.keys())}")
        return None

    config = COMPANIES[company_key]
    print("=" * 60)
    print(f"{config['name'].upper()} JOB SCRAPER (Playwright)")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        jobs = []

        try:
            if company_key == "cisco":
                jobs = await scrape_cisco(page, location, max_jobs)
            elif company_key == "google":
                jobs = await scrape_google(page, location, max_jobs)
            elif company_key == "ibm":
                jobs = await scrape_ibm(page, location, max_jobs)
            elif company_key == "apple":
                jobs = await scrape_apple(page, location, max_jobs)
            elif company_key == "meta":
                jobs = await scrape_meta(page, location, max_jobs)
            else:
                print(f"No scraper implemented for {company_key}")

        except Exception as e:
            print(f"Error scraping {company_key}: {e}")

        finally:
            await browser.close()

    # Remove duplicates
    seen = set()
    unique_jobs = []
    for job in jobs:
        key = (job["title"], job["url"])
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    print(f"\nFound {len(unique_jobs)} unique jobs")

    output = {
        "company": config["name"],
        "scraped_at": datetime.now().isoformat(),
        "location_searched": location,
        "careers_url": config.get("url", ""),
        "total_jobs": len(unique_jobs),
        "jobs": unique_jobs
    }

    return output


def main():
    parser = argparse.ArgumentParser(description="Playwright Job Scraper")
    parser.add_argument("--company", "-c", help="Company to scrape")
    parser.add_argument("--location", "-l", default="London", help="Location to search")
    parser.add_argument("--limit", type=int, default=100, help="Max jobs to fetch")
    parser.add_argument("--list", action="store_true", help="List available companies")
    parser.add_argument("--all", "-a", action="store_true", help="Scrape all companies")
    parser.add_argument("--visible", action="store_true", help="Show browser (not headless)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.list:
        print("Available companies (Playwright):")
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
        result = asyncio.run(scrape_company(
            company_key,
            args.location,
            args.limit,
            headless=not args.visible
        ))

        if result:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = OUTPUT_DIR / f"{company_key}_playwright_{timestamp}.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"Saved to {output_file}")

            if result["total_jobs"] > 0:
                print(f"\nSample jobs:")
                for job in result["jobs"][:5]:
                    print(f"  - {job['title'][:55]}")
                    print(f"    {job['location']}")
                if result["total_jobs"] > 5:
                    print(f"\n  ... and {result['total_jobs'] - 5} more jobs")

        print()


if __name__ == "__main__":
    main()
