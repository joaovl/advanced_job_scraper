#!/usr/bin/env python3
"""
Playwright Job Scraper v2 - With Anti-Detection
For JavaScript-heavy career sites that block headless browsers.

Usage:
    python scrapers/playwright_scraper_v2.py --company cisco --location London
    python scrapers/playwright_scraper_v2.py --all --location London
"""

import json
import argparse
import asyncio
import re
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"


async def create_stealth_browser(playwright, headless=True):
    """Create a browser with anti-detection measures."""
    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
        ]
    )

    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="en-GB",
        timezone_id="Europe/London",
    )

    # Add stealth scripts
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en-US', 'en'] });
        window.chrome = { runtime: {} };
    """)

    return browser, context


async def wait_and_scroll(page, wait_time=5, scroll_times=10):
    """Wait for content and scroll to trigger lazy loading."""
    await asyncio.sleep(wait_time)

    for _ in range(scroll_times):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)

    await asyncio.sleep(2)


async def scrape_cisco(page, location="London"):
    """Scrape Cisco careers by iterating through category pages."""
    jobs = []
    seen = set()

    print(f"  Loading Cisco careers by category...")

    # Cisco categories that typically have UK jobs
    categories = [
        "sales-jobs",
        "engineering-software-jobs",
        "it-jobs",
        "support-jobs",
        "consulting-jobs",
        "marketing-jobs",
        "finance-jobs",
        "human-resources-jobs",
    ]

    for cat in categories:
        url = f"https://careers.cisco.com/global/en/c/{cat}"
        print(f"  Checking {cat}...")

        try:
            await page.goto(url, timeout=30000)
            await wait_and_scroll(page, wait_time=3, scroll_times=5)

            # Find job links
            elements = await page.query_selector_all("a[href*='/job/']")

            for el in elements:
                try:
                    href = await el.get_attribute("href")
                    text = await el.inner_text()
                    text = text.strip()

                    if not href or not text or len(text) < 5:
                        continue
                    if href in seen or text.lower() in ['apply', 'view', 'details']:
                        continue
                    seen.add(href)

                    if not href.startswith("http"):
                        href = f"https://careers.cisco.com{href}"

                    # Try to get location from parent
                    loc_text = location
                    try:
                        parent = await el.evaluate_handle("el => el.closest('[data-ph-at-job-card]') || el.parentElement")
                        loc_el = await parent.query_selector("[data-ph-at-job-location-text], .job-location")
                        if loc_el:
                            loc_text = await loc_el.inner_text()
                    except:
                        pass

                    # Filter for UK/London jobs
                    loc_lower = loc_text.lower()
                    if location.lower() in loc_lower or "uk" in loc_lower or "united kingdom" in loc_lower or "london" in loc_lower:
                        jobs.append({
                            "title": text[:200],
                            "location": loc_text.strip(),
                            "url": href,
                            "company": "Cisco"
                        })

                except:
                    continue

            print(f"    Found {len(jobs)} UK jobs so far")

        except Exception as e:
            print(f"    Error: {str(e)[:30]}")
            continue

    return jobs


async def scrape_google(page, location="London, UK"):
    """Scrape Google careers."""
    jobs = []

    print(f"  Loading Google careers page...")

    url = f"https://www.google.com/about/careers/applications/jobs/results?location={location.replace(' ', '%20').replace(',', '%2C')}"
    await page.goto(url, timeout=60000)

    await wait_and_scroll(page, wait_time=8, scroll_times=10)

    # Look for job titles (h3 elements)
    titles = await page.query_selector_all("h3.QJPWVe, h3[class*='title']")
    print(f"  Found {len(titles)} h3 elements")

    seen = set()
    for h3 in titles:
        try:
            title = await h3.inner_text()
            title = title.strip()

            if not title or title in seen or len(title) < 5:
                continue
            seen.add(title)

            # Get location from sibling/parent
            loc_text = location
            try:
                parent = await h3.evaluate_handle("el => el.parentElement?.parentElement")
                loc_el = await parent.query_selector("[class*='location'], .pwO9Dc")
                if loc_el:
                    loc_text = await loc_el.inner_text()
                    loc_text = loc_text.replace("place", "").strip()
            except:
                pass

            # Build search URL for this job
            title_slug = re.sub(r'[^a-z0-9]+', '-', title.lower())[:50]
            job_url = f"https://www.google.com/about/careers/applications/jobs/results?q={title_slug}&location={location}"

            jobs.append({
                "title": title,
                "location": loc_text,
                "url": job_url,
                "company": "Google"
            })
        except:
            continue

    return jobs


async def scrape_ibm(page, location="United Kingdom"):
    """Scrape IBM careers."""
    jobs = []

    print(f"  Loading IBM careers page...")

    url = f"https://www.ibm.com/uk-en/careers/search?field_keyword_05[0]={location.replace(' ', '%20')}"
    await page.goto(url, wait_until="domcontentloaded", timeout=90000)

    # IBM needs much longer wait time for content to load
    print("  Waiting for jobs to load (this takes a while)...")
    await asyncio.sleep(10)  # Initial wait for JS to initialize
    await wait_and_scroll(page, wait_time=10, scroll_times=25)

    # Try to click load more buttons
    for _ in range(10):
        try:
            btn = await page.query_selector("button:has-text('Load more'), button:has-text('Show more')")
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1)
            else:
                break
        except:
            break

    # Extract job links directly
    job_links = await page.query_selector_all("a[href*='job']")
    print(f"  Found {len(job_links)} job links")

    seen = set()
    skip_words = ['search jobs', 'explore', 'learn more', 'ibm', 'follow', 'connect', 'discover']

    for link in job_links:
        try:
            text = await link.inner_text()
            text = text.strip()

            # Clean up multi-line text - IBM structure is:
            # Line 1: Category (Software Engineering, etc)
            # Line 2: Job Title
            # Line 3: Level (Professional)
            # Line 4: Location
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            if len(lines) < 2:
                continue

            # Second line is the actual job title
            title = lines[1] if len(lines) > 1 else lines[0]
            category = lines[0]
            loc_text = lines[-1] if len(lines) > 2 else location

            if not title or len(title) < 10 or len(title) > 200:
                continue
            if title in seen:
                continue
            if any(skip in title.lower() for skip in skip_words):
                continue
            seen.add(title)

            href = await link.get_attribute("href")
            if href and not href.startswith("http"):
                href = f"https://www.ibm.com{href}"

            jobs.append({
                "title": title,
                "location": loc_text,
                "url": href,
                "department": category,
                "company": "IBM"
            })

        except:
            continue

    return jobs


async def scrape_apple(page, location="london"):
    """Scrape Apple careers."""
    jobs = []

    print(f"  Loading Apple careers page...")

    url = f"https://jobs.apple.com/en-gb/search?location={location}-GBR"
    await page.goto(url, timeout=60000)

    await wait_and_scroll(page, wait_time=8, scroll_times=10)

    # Find all job detail links
    links = await page.query_selector_all("a[href*='/details/']")
    print(f"  Found {len(links)} detail links")

    seen = set()
    skip_titles = ['see full role description', 'where we', 'apply now', 'learn more', 'view job']

    for link in links:
        try:
            text = await link.inner_text()
            text = text.strip()

            # Skip non-title links
            if not text or len(text) < 10 or len(text) > 150:
                continue
            if any(skip in text.lower() for skip in skip_titles):
                continue
            if text in seen:
                continue
            seen.add(text)

            href = await link.get_attribute("href")
            if href and not href.startswith("http"):
                href = f"https://jobs.apple.com{href}"

            jobs.append({
                "title": text,
                "location": location.title(),
                "url": href,
                "company": "Apple"
            })

        except:
            continue

    return jobs


async def scrape_meta(page, location="London, UK"):
    """Scrape Meta careers."""
    jobs = []

    print(f"  Loading Meta careers page...")

    url = f"https://www.metacareers.com/jobs?offices[0]={location.replace(' ', '%20').replace(',', '%2C')}"
    await page.goto(url, wait_until="networkidle", timeout=90000)

    # Meta needs time to load job listings
    print("  Waiting for jobs to load (this takes a while)...")
    await asyncio.sleep(8)  # Initial wait for JS to initialize
    await wait_and_scroll(page, wait_time=8, scroll_times=20)

    # Look for job links - Meta uses /profile/job_details/ pattern
    job_links = await page.query_selector_all("a[href*='job']")
    print(f"  Found {len(job_links)} job links")

    seen = set()
    skip_words = ['search', 'filter', 'career', 'blog', 'team', 'program', 'about', 'login', 'sign']

    for link in job_links:
        try:
            href = await link.get_attribute("href") or ""

            # Skip non-job links - Meta uses job_details pattern
            if not href:
                continue
            if "job_details" not in href and "/jobs/" not in href:
                continue
            if any(skip in href.lower() for skip in ['search', 'filter']):
                continue
            if href in seen:
                continue
            seen.add(href)

            # Get text
            text = await link.inner_text()
            text = text.strip()

            if not text or len(text) < 10 or len(text) > 200:
                continue
            if any(skip in text.lower() for skip in skip_words):
                continue

            # Clean up the text - get first meaningful line
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            title = lines[0] if lines else text

            if not href.startswith("http"):
                href = f"https://www.metacareers.com{href}"

            jobs.append({
                "title": title,
                "location": location,
                "url": href,
                "company": "Meta"
            })

        except:
            continue

    return jobs


async def scrape_amazon(page, location="London"):
    """Scrape Amazon careers using their JSON API with pagination."""
    import aiohttp

    jobs = []
    print(f"  Fetching Amazon jobs via API...")

    # Amazon has a JSON API - filter by city directly for better results
    location_lower = location.lower()
    base_url = f"https://www.amazon.jobs/en-gb/search.json?country=GBR&city={location}&result_limit=100"

    try:
        async with aiohttp.ClientSession() as session:
            offset = 0
            total_hits = None

            while True:
                api_url = f"{base_url}&offset={offset}"
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        print(f"  API returned status {resp.status}")
                        break

                    data = await resp.json()

                    if total_hits is None:
                        total_hits = data.get("hits", 0)
                        print(f"  Total {location} jobs available: {total_hits}")

                    batch = data.get("jobs", [])
                    if not batch:
                        break

                    for job in batch:
                        job_id = job.get("id_icims", job.get("id", ""))
                        jobs.append({
                            "title": job.get("title", ""),
                            "location": f"{job.get('city', '')}, {job.get('country_code', '')}",
                            "url": f"https://www.amazon.jobs/en-gb/jobs/{job_id}",
                            "department": job.get("job_category", ""),
                            "company": "Amazon"
                        })

                    offset += len(batch)
                    print(f"  Fetched {offset}/{total_hits} jobs...")

                    if offset >= total_hits:
                        break

    except Exception as e:
        print(f"  API error: {e}")

    return jobs


SCRAPERS = {
    "cisco": scrape_cisco,
    "google": scrape_google,
    "ibm": scrape_ibm,
    "apple": scrape_apple,
    "meta": scrape_meta,
    "amazon": scrape_amazon,
}

# Location mapping per company (some companies need specific location formats)
LOCATION_MAP = {
    "ibm": {"London": "United Kingdom", "london": "United Kingdom"},
    "meta": {"London": "London, UK", "london": "London, UK"},
    "google": {"London": "London, UK", "london": "London, UK"},
    "apple": {"London": "london", "london": "london"},
}


def get_location_for_company(company: str, location: str) -> str:
    """Get the appropriate location format for a company."""
    if company in LOCATION_MAP and location in LOCATION_MAP[company]:
        return LOCATION_MAP[company][location]
    return location


async def main_scrape(company: str, location: str, headless: bool = True):
    """Main scraping function."""

    if company not in SCRAPERS:
        print(f"Unknown company: {company}")
        print(f"Available: {', '.join(SCRAPERS.keys())}")
        return None

    # Get company-specific location format
    company_location = get_location_for_company(company, location)

    print("=" * 60)
    print(f"{company.upper()} JOB SCRAPER v2 (Playwright)")
    print("=" * 60)

    async with async_playwright() as p:
        browser, context = await create_stealth_browser(p, headless=headless)
        page = await context.new_page()

        try:
            jobs = await SCRAPERS[company](page, company_location)
        except Exception as e:
            print(f"  Error: {e}")
            jobs = []
        finally:
            await browser.close()

    # Remove duplicates
    seen = set()
    unique = []
    for job in jobs:
        key = job["title"]
        if key not in seen:
            seen.add(key)
            unique.append(job)

    print(f"\nFound {len(unique)} unique jobs")

    return {
        "company": company.title(),
        "scraped_at": datetime.now().isoformat(),
        "location_searched": location,
        "total_jobs": len(unique),
        "jobs": unique
    }


async def run_all_scrapers(companies: list, location: str, headless: bool = True):
    """Run multiple scrapers in a single async context with delays between them."""
    results = []

    for i, company in enumerate(companies):
        if company not in SCRAPERS:
            print(f"Unknown company: {company}")
            continue

        # Get company-specific location format
        company_location = get_location_for_company(company, location)

        print("=" * 60)
        print(f"{company.upper()} JOB SCRAPER v2 (Playwright)")
        print(f"Location: {company_location}")
        print("=" * 60)

        async with async_playwright() as p:
            browser, context = await create_stealth_browser(p, headless=headless)
            page = await context.new_page()

            try:
                jobs = await SCRAPERS[company](page, company_location)
            except Exception as e:
                print(f"  Error: {e}")
                jobs = []
            finally:
                await browser.close()

        # Remove duplicates
        seen = set()
        unique = []
        for job in jobs:
            key = job["title"]
            if key not in seen:
                seen.add(key)
                unique.append(job)

        print(f"\nFound {len(unique)} unique jobs")

        result = {
            "company": company.title(),
            "scraped_at": datetime.now().isoformat(),
            "location_searched": company_location,
            "total_jobs": len(unique),
            "jobs": unique
        }
        results.append((company, result))

        # Add delay between companies to avoid rate limiting
        if i < len(companies) - 1:
            print("\nWaiting 5 seconds before next company...")
            await asyncio.sleep(5)

    return results


def safe_print(text):
    """Print text safely, handling encoding issues."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('ascii', 'replace').decode('ascii'))


def main():
    parser = argparse.ArgumentParser(description="Playwright Job Scraper v2")
    parser.add_argument("--company", "-c", help="Company to scrape")
    parser.add_argument("--location", "-l", default="London", help="Location")
    parser.add_argument("--list", action="store_true", help="List companies")
    parser.add_argument("--all", "-a", action="store_true", help="Scrape all")
    parser.add_argument("--visible", action="store_true", help="Show browser")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.list:
        print("Available companies:")
        for name in SCRAPERS:
            print(f"  - {name}")
        return

    companies = [args.company] if args.company else list(SCRAPERS.keys()) if args.all else []

    if not companies:
        print("Use --company NAME or --all")
        return

    # Run all scrapers in a single async context
    results = asyncio.run(run_all_scrapers(companies, args.location, not args.visible))

    # Save results
    for company, result in results:
        if result:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            outfile = OUTPUT_DIR / f"{company}_v2_{timestamp}.json"

            with open(outfile, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"Saved to {outfile}")

            if result["jobs"]:
                print("\nSample jobs:")
                for job in result["jobs"][:5]:
                    safe_print(f"  - {job['title'][:50]}")
                    safe_print(f"    {job['location']}")

        print()


if __name__ == "__main__":
    main()
