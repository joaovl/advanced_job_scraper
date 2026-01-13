#!/usr/bin/env python3
"""
Generic Job Scraper - Multi-Platform Support

Supports: Greenhouse, Workable, Lever, Avature, and custom sites.
Auto-detects platform from HTML structure.

Usage:
    python scrapers/generic_scraper.py <company_folder>
    python scrapers/generic_scraper.py 10xbanking
"""

import json
import time
import re
import sys
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict

BASE_DIR = Path(__file__).parent.parent
COMPANY_PAGES_DIR = BASE_DIR / "Company_Pages"
OUTPUT_DIR = BASE_DIR / "output"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


@dataclass
class Job:
    title: str
    location: str
    url: str
    job_id: str
    description: str = ""
    department: str = ""
    company: str = ""
    # Additional metadata fields
    remote_type: str = ""  # Hybrid, Remote, On-site
    time_type: str = ""    # Full time, Part time, Contract
    posted_date: str = ""  # When the job was posted
    job_category: str = "" # Job category/family


def detect_platform(html: str) -> str:
    """Detect which ATS platform the HTML is from."""
    html_lower = html.lower()

    # Check specific company patterns first
    if 'oaknorth.co.uk/jobs' in html_lower or 'job-opportunity' in html_lower:
        return 'oaknorth'
    if 'rapyd.net' in html_lower or 'vcex-post-type-entry' in html_lower:
        return 'rapyd'
    if 'marqeta.com' in html_lower or 'current job openings at marqeta' in html_lower:
        return 'marqeta'
    if 'careers.adyen.com' in html_lower or 'vacancies-list-item' in html_lower:
        return 'adyen'
    if 'starlingbank.com/careers' in html_lower or 'starling-job' in html_lower:
        return 'starling'
    if 'careers.microsoft.com' in html_lower or 'apply.careers.microsoft.com' in html_lower:
        return 'microsoft'
    if 'amazon.jobs' in html_lower or 'class="job-link"' in html_lower:
        return 'amazon'
    if 'jobs.apple.com' in html_lower:
        return 'apple'
    if 'jobs.netflix' in html_lower or 'position-card' in html_lower:
        return 'netflix'
    if 'google.com/about/careers' in html_lower:
        return 'google'
    if 'ibmglobal.avature.net' in html_lower:
        return 'ibm'
    if 'careers.oracle.com' in html_lower and 'job-tile' in html_lower:
        return 'oracle'
    if 'jobs.mercedes-benz.com' in html_lower or 'mjp-job-ad-card' in html_lower:
        return 'mercedes'

    # Then check ATS platforms
    if 'workable.com' in html_lower or 'wc-card' in html_lower:
        return 'workable'
    if 'greenhouse.io' in html_lower or 'boards.greenhouse' in html_lower:
        return 'greenhouse'
    if 'lever.co' in html_lower or 'lever-jobs' in html_lower:
        return 'lever'
    if 'avature.net' in html_lower or 'article--result' in html_lower:
        return 'avature'
    if 'ashbyhq.com' in html_lower or 'workable__job' in html_lower:
        return 'ashby'
    if 'smartrecruiters' in html_lower:
        return 'smartrecruiters'

    return 'generic'


def extract_greenhouse_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Greenhouse job board HTML."""
    jobs = []

    # Greenhouse uses various structures
    for section in soup.find_all('section', class_='level-0'):
        dept = section.find('h3')
        dept_name = dept.get_text(strip=True) if dept else ""

        for opening in section.find_all('div', class_='opening'):
            link = opening.find('a')
            if not link:
                continue

            title = link.get_text(strip=True)
            url = link.get('href', '')

            location_el = opening.find('span', class_='location')
            location = location_el.get_text(strip=True) if location_el else ""

            job_id = ""
            if url:
                match = re.search(r'/jobs/(\d+)', url)
                if match:
                    job_id = match.group(1)

            jobs.append(Job(
                title=title,
                location=location,
                url=url,
                job_id=job_id,
                department=dept_name
            ))

    # Alternative structure
    if not jobs:
        for link in soup.find_all('a', href=re.compile(r'/jobs/\d+')):
            title = link.get_text(strip=True)
            url = link.get('href', '')
            if title and len(title) > 3:
                job_id = re.search(r'/jobs/(\d+)', url).group(1) if url else ""
                jobs.append(Job(title=title, location="", url=url, job_id=job_id))

    return jobs


def extract_workable_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Workable job board HTML."""
    jobs = []

    # Look for job cards
    for card in soup.find_all(['li', 'div'], attrs={'data-ui': re.compile(r'job')}):
        link = card.find('a', attrs={'data-ui': 'job-title'})
        if not link:
            link = card.find('a')
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link.get('href', '')

        # Location
        loc_el = card.find(attrs={'data-ui': re.compile(r'location|workplace')})
        location = loc_el.get_text(strip=True) if loc_el else ""

        # Job ID from URL
        job_id = ""
        if url:
            match = re.search(r'/j/([A-Za-z0-9]+)', url)
            if match:
                job_id = match.group(1)

        if title:
            jobs.append(Job(title=title, location=location, url=url, job_id=job_id))

    return jobs


def extract_lever_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Lever job board HTML."""
    jobs = []

    for posting in soup.find_all('div', class_=re.compile(r'posting|lever-job')):
        link = posting.find('a', class_=re.compile(r'posting-title|job-title'))
        if not link:
            link = posting.find('a')
        if not link:
            continue

        title_el = posting.find(['h5', 'h4', 'h3'], class_=re.compile(r'posting-name|title'))
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
        url = link.get('href', '')

        loc_el = posting.find(class_=re.compile(r'location|posting-categories'))
        location = loc_el.get_text(strip=True) if loc_el else ""

        job_id = ""
        if url:
            match = re.search(r'/([a-f0-9-]{36})', url)
            if match:
                job_id = match.group(1)

        if title:
            jobs.append(Job(title=title, location=location, url=url, job_id=job_id))

    return jobs


def extract_avature_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Avature career site HTML."""
    jobs = []

    for article in soup.find_all('article', class_='article--result'):
        title_el = article.find('h3', class_=re.compile(r'title'))
        link = title_el.find('a') if title_el else article.find('a')
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link.get('href', '')

        loc_el = article.find('span', class_='list-item-location')
        location = loc_el.get_text(strip=True) if loc_el else ""

        job_id = ""
        if url:
            match = re.search(r'/(\d+)$', url)
            if match:
                job_id = match.group(1)

        if title:
            jobs.append(Job(title=title, location=location, url=url, job_id=job_id))

    return jobs


def extract_rapyd_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Rapyd careers page."""
    jobs = []

    for entry in soup.find_all('div', class_='vcex-post-type-entry'):
        link = entry.find('a', class_='c-button')
        if not link:
            continue

        url = link.get('href', '')

        # Get details from list
        details_list = entry.find('ul', class_='c-position-details__list')
        if details_list:
            items = details_list.find_all('li')
            title = items[0].get_text(strip=True) if len(items) > 0 else ""
            department = items[1].get_text(strip=True) if len(items) > 1 else ""
        else:
            title = ""
            department = ""

        # Location from data attribute or name div
        location = entry.get('data-name', '')
        if not location:
            loc_div = entry.find('div', class_='name')
            if loc_div:
                location = loc_div.get_text(strip=True)

        if title and url:
            jobs.append(Job(title=title, location=location, url=url, job_id="", department=department))

    return jobs


def extract_marqeta_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Marqeta careers page (table structure)."""
    jobs = []

    # Marqeta uses table rows as links with href="/careers/ID"
    for link in soup.find_all('a', href=re.compile(r'/careers/\d+')):
        cells = link.find_all('td')
        if len(cells) >= 3:
            title = cells[0].get_text(strip=True)
            department = cells[1].get_text(strip=True)
            location = cells[2].get_text(strip=True)

            url = link.get('href', '')
            if not url.startswith('http'):
                url = f"https://www.marqeta.com{url}"

            job_id = ""
            match = re.search(r'/careers/(\d+)', url)
            if match:
                job_id = match.group(1)

            if title:
                jobs.append(Job(
                    title=title,
                    location=location,
                    url=url,
                    job_id=job_id,
                    department=department
                ))

    return jobs


def extract_adyen_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Adyen careers page (vacancies-list-item structure)."""
    jobs = []
    seen = set()

    # Adyen uses vacancies-list-item divs with links containing job titles
    for item in soup.find_all('div', class_='vacancies-list-item'):
        # Get the job title link (has class vacancies-list-item__link)
        link = item.find('a', class_=re.compile(r'vacancies-list-item__link'))
        if not link:
            continue

        title = link.get('aria-label', '') or link.get_text(strip=True)
        url = link.get('href', '')

        # Skip if already seen
        if title in seen or not title:
            continue
        seen.add(title)

        # Make URL absolute
        if url and not url.startswith('http'):
            url = f"https://careers.adyen.com{url}"

        # Get department from team link
        dept_link = item.find('a', href=re.compile(r'\?team='))
        department = dept_link.get_text(strip=True) if dept_link else ""

        # Get location from location link
        loc_link = item.find('a', href=re.compile(r'\?location='))
        location = loc_link.get_text(strip=True) if loc_link else ""

        # Extract job_id from URL
        job_id = ""
        match = re.search(r'/vacancies/(\d+)', url)
        if match:
            job_id = match.group(1)

        jobs.append(Job(
            title=title,
            location=location,
            url=url,
            job_id=job_id,
            department=department
        ))

    return jobs


def extract_starling_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Starling Bank careers page."""
    jobs = []
    seen = set()

    # Starling uses h3 tags with job titles and Workable links
    # Job titles are in h3 tags with class 'zp6bqebk'
    for h3 in soup.find_all('h3', class_=re.compile(r'zp6bqebk')):
        title = h3.get_text(strip=True)

        # Skip non-job titles
        if len(title) < 5 or len(title) > 150:
            continue
        if title in seen:
            continue

        seen.add(title)

        # Find the parent container and look for Workable link
        parent = h3.parent
        url = ""
        location = ""

        # Look in sibling elements for the Workable link
        for _ in range(5):  # Check up to 5 levels up
            if parent:
                workable_link = parent.find('a', href=re.compile(r'apply\.workable\.com/j/'))
                if workable_link:
                    url = workable_link.get('href', '')
                    # Get location from the link text
                    loc_text = workable_link.get_text(strip=True)
                    if loc_text and len(loc_text) < 50:
                        location = loc_text
                    break
                parent = parent.parent

        # Extract job ID from Workable URL
        job_id = ""
        if url:
            match = re.search(r'/j/([A-Z0-9]+)', url)
            if match:
                job_id = match.group(1)

        jobs.append(Job(title=title, location=location, url=url, job_id=job_id))

    return jobs


def extract_microsoft_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Microsoft careers page."""
    jobs = []
    seen = set()

    # Microsoft uses links with aria-label containing job titles
    # URL pattern: https://apply.careers.microsoft.com/careers/...
    for link in soup.find_all('a', href=re.compile(r'apply\.careers\.microsoft\.com/careers')):
        # Get title from aria-label attribute
        title = link.get('aria-label', '')

        # Skip non-job links
        if not title or len(title) < 5 or len(title) > 150:
            continue
        if title.lower() in ['apply now', 'join talent network', 'manage', 'support']:
            continue
        if title in seen:
            continue

        seen.add(title)

        url = link.get('href', '')

        # Try to get location from sibling elements
        location = ""
        parent = link.parent
        if parent:
            loc_el = parent.find(class_=re.compile(r'location|subTitle'))
            if loc_el:
                location = loc_el.get_text(strip=True)

        # Extract job ID from URL if present
        job_id = ""
        match = re.search(r'/v2/global/en/job/(\d+)', url)
        if match:
            job_id = match.group(1)

        jobs.append(Job(title=title, location=location, url=url, job_id=job_id))

    return jobs


def extract_amazon_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Amazon jobs page."""
    jobs = []
    seen = set()

    # Amazon uses class="job-link" with href to amazon.jobs/en/jobs/ID/title
    for link in soup.find_all('a', class_='job-link'):
        title = link.get_text(strip=True)
        url = link.get('href', '')

        if not title or len(title) < 5 or title in seen:
            continue
        seen.add(title)

        # Extract job ID from URL
        job_id = ""
        match = re.search(r'/jobs/(\d+)/', url)
        if match:
            job_id = match.group(1)

        # Try to get location from parent container
        location = ""
        parent = link.find_parent('div', class_=re.compile(r'job'))
        if parent:
            loc_el = parent.find(class_=re.compile(r'location'))
            if loc_el:
                location = loc_el.get_text(strip=True)

        jobs.append(Job(title=title, location=location, url=url, job_id=job_id))

    return jobs


def extract_apple_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Apple careers page."""
    jobs = []
    seen = set()

    # Apple uses href to jobs.apple.com/en-us/details/ID/title
    for link in soup.find_all('a', href=re.compile(r'jobs\.apple\.com/[^/]+/details/\d+')):
        url = link.get('href', '')

        # Skip duplicate URLs
        if url in seen:
            continue
        seen.add(url)

        # Extract job ID and title from URL
        match = re.search(r'/details/(\d+)/([^/?]+)', url)
        if match:
            job_id = match.group(1)
            # Convert URL slug to title
            title = match.group(2).replace('-', ' ').title()
        else:
            job_id = ""
            title = link.get_text(strip=True)

        if not title or len(title) < 5:
            continue

        jobs.append(Job(title=title, location="", url=url, job_id=job_id))

    return jobs


def extract_netflix_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Netflix careers page (Eightfold-based)."""
    jobs = []
    seen = set()

    # Netflix uses position-card class
    for card in soup.find_all(class_='position-card'):
        title_el = card.find(class_='position-title')
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        if not title or title in seen:
            continue
        seen.add(title)

        # Find link
        link = card.find('a', href=True)
        url = link.get('href', '') if link else ""

        # Location
        loc_el = card.find(class_=re.compile(r'location'))
        location = loc_el.get_text(strip=True) if loc_el else ""

        jobs.append(Job(title=title, location=location, url=url, job_id=""))

    return jobs


def extract_google_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Google careers page."""
    jobs = []
    seen = set()

    # Google uses URLs like /jobs/results/ID-title
    for link in soup.find_all('a', href=re.compile(r'/jobs/results/\d+-')):
        url = link.get('href', '')

        if url in seen:
            continue
        seen.add(url)

        # Extract job ID and title from URL
        match = re.search(r'/jobs/results/(\d+)-([^?]+)', url)
        if match:
            job_id = match.group(1)
            title = match.group(2).replace('-', ' ').title()
        else:
            continue

        if not title or len(title) < 5:
            continue

        # Make URL absolute
        if not url.startswith('http'):
            url = f"https://www.google.com{url}"

        jobs.append(Job(title=title, location="", url=url, job_id=job_id))

    return jobs


def extract_ibm_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from IBM careers page (Avature-based)."""
    jobs = []
    seen = set()

    # IBM uses Avature with JobDetail?jobId=ID URLs
    for link in soup.find_all('a', href=re.compile(r'avature\.net.*JobDetail\?jobId=\d+')):
        url = link.get('href', '')
        title = link.get_text(strip=True)

        # Extract job ID
        match = re.search(r'jobId=(\d+)', url)
        job_id = match.group(1) if match else ""

        if job_id in seen or not title or len(title) < 5:
            continue
        seen.add(job_id)

        # Skip navigation links
        if title.lower() in ['apply', 'view', 'details', 'more']:
            continue

        jobs.append(Job(title=title, location="", url=url, job_id=job_id))

    return jobs


def extract_oracle_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Oracle careers page."""
    jobs = []
    seen = set()

    # Oracle uses job-grid-item class
    for item in soup.find_all(class_='job-grid-item'):
        # Find title element (job-tile__title class)
        title_el = item.find(class_=re.compile(r'job-tile__title'))
        if not title_el:
            title_el = item.find(['h2', 'h3', 'a'])
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        if not title or title in seen or len(title) < 5:
            continue
        seen.add(title)

        # Find link
        link = item.find('a', href=True)
        url = link.get('href', '') if link else ""
        if url and not url.startswith('http'):
            url = f"https://careers.oracle.com{url}"

        # Find location
        loc_el = item.find(class_=re.compile(r'location|subheader'))
        location = loc_el.get_text(strip=True) if loc_el else ""

        jobs.append(Job(title=title, location=location, url=url, job_id=""))

    return jobs


def extract_oaknorth_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from OakNorth careers page (Lever-based)."""
    jobs = []
    seen = set()

    # OakNorth uses job-opportunity containers with job-title elements
    for opp in soup.find_all('div', class_='job-opportunity'):
        title_el = opp.find(class_=re.compile(r'job.*title', re.I))
        if not title_el:
            continue

        title = title_el.get_text(strip=True)

        # Skip descriptions (too long)
        if len(title) > 100:
            continue

        # Find link to job details
        link = opp.find('a', href=re.compile(r'/jobs/'))
        if link and title not in seen:
            seen.add(title)
            url = link.get('href', '')

            # Extract job_id from URL
            job_id = ""
            match = re.search(r'id=([a-f0-9-]+)', url)
            if match:
                job_id = match.group(1)

            jobs.append(Job(title=title, location="", url=url, job_id=job_id))

    return jobs


def extract_mercedes_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Extract jobs from Mercedes-Benz careers page."""
    jobs = []
    seen = set()

    # Mercedes uses mjp-job-ad-card containers
    for card in soup.find_all('div', class_='mjp-job-ad-card'):
        # Find the link
        link = card.find('a', class_='mjp-job-ad-card__link')
        if not link:
            continue

        url = link.get('href', '')
        if not url or url in seen:
            continue

        # Extract title from span with class mjp-job-ad-card__title-text
        title_el = card.find('span', class_='mjp-job-ad-card__title-text')
        title = title_el.get_text(strip=True) if title_el else ""

        if not title:
            continue

        # Extract location from mjp-job-ad-card__location
        loc_el = card.find(class_='mjp-job-ad-card__location')
        location = ""
        if loc_el:
            loc_span = loc_el.find('span', class_='mjp-at-most-two-lines')
            if loc_span:
                location = loc_span.get_text(strip=True)

        # Extract job_id from URL pattern like MER0003WG4
        job_id = ""
        match = re.search(r'(MER[0-9A-Z]+)', url)
        if match:
            job_id = match.group(1)

        seen.add(url)
        jobs.append(Job(title=title, location=location, url=url, job_id=job_id))

    return jobs


def extract_generic_jobs(soup: BeautifulSoup, base_url: str) -> list[Job]:
    """Generic extraction for unknown platforms."""
    jobs = []
    seen_urls = set()

    # Look for common job listing patterns
    job_patterns = [
        ('a', {'class': re.compile(r'job|career|position|opening', re.I)}),
        ('a', {'href': re.compile(r'/jobs/|/careers/|/position|/opening', re.I)}),
        ('div', {'class': re.compile(r'job-card|job-item|vacancy|posting', re.I)}),
        ('li', {'class': re.compile(r'job|position|opening', re.I)}),
    ]

    for tag, attrs in job_patterns:
        for el in soup.find_all(tag, attrs):
            link = el if tag == 'a' else el.find('a')
            if not link:
                continue

            title = link.get_text(strip=True)
            url = link.get('href', '')

            # Skip navigation/menu items
            if len(title) < 5 or len(title) > 200:
                continue
            if title.lower() in ['jobs', 'careers', 'apply', 'search', 'view all', 'details']:
                continue
            if url in seen_urls:
                continue
            # Skip anchors and navigation
            if url.endswith('#') or url.endswith('#0'):
                continue

            seen_urls.add(url)
            jobs.append(Job(title=title, location="", url=url, job_id=""))

    return jobs


def extract_jobs(html: str, platform: str, base_url: str = "") -> list[Job]:
    """Extract jobs based on detected platform."""
    soup = BeautifulSoup(html, 'html.parser')

    extractors = {
        'greenhouse': extract_greenhouse_jobs,
        'workable': extract_workable_jobs,
        'lever': extract_lever_jobs,
        'avature': extract_avature_jobs,
        'rapyd': extract_rapyd_jobs,
        'marqeta': extract_marqeta_jobs,
        'oaknorth': extract_oaknorth_jobs,
        'adyen': extract_adyen_jobs,
        'starling': extract_starling_jobs,
        'microsoft': extract_microsoft_jobs,
        'amazon': extract_amazon_jobs,
        'apple': extract_apple_jobs,
        'netflix': extract_netflix_jobs,
        'google': extract_google_jobs,
        'ibm': extract_ibm_jobs,
        'oracle': extract_oracle_jobs,
        'mercedes': extract_mercedes_jobs,
        'generic': extract_generic_jobs,
    }

    extractor = extractors.get(platform, extract_generic_jobs)
    return extractor(soup, base_url)


def extract_job_metadata_from_html(html: str) -> dict:
    """Extract job metadata (remote_type, time_type, posted_date) from a detail page HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    metadata = {
        "remote_type": "",
        "time_type": "",
        "posted_date": "",
        "location": "",
    }

    # Greenhouse format - look for job__location div
    loc_div = soup.find('div', class_='job__location')
    if loc_div:
        metadata["location"] = loc_div.get_text(strip=True)

    # Workable format - look for data-ui attributes
    remote_el = soup.find(attrs={'data-ui': re.compile(r'workplace|remote', re.I)})
    if remote_el:
        metadata["remote_type"] = remote_el.get_text(strip=True)

    # Look for remote type indicators in various formats
    for pattern in [
        ('span', {'class': re.compile(r'remote|workplace', re.I)}),
        ('div', {'class': re.compile(r'remote|workplace', re.I)}),
        ('dd', {'class': re.compile(r'remote', re.I)}),
    ]:
        el = soup.find(pattern[0], pattern[1])
        if el and not metadata["remote_type"]:
            text = el.get_text(strip=True)
            if any(x in text.lower() for x in ['hybrid', 'remote', 'on-site', 'onsite', 'office']):
                metadata["remote_type"] = text
                break

    # Look for time type (Full time, Part time, Contract)
    for pattern in [
        ('span', {'class': re.compile(r'time.*type|employment', re.I)}),
        ('div', {'class': re.compile(r'time.*type|employment', re.I)}),
        ('dd', {}),
        ('li', {}),
    ]:
        for el in soup.find_all(pattern[0], pattern[1]):
            text = el.get_text(strip=True)
            text_lower = text.lower()
            if any(x in text_lower for x in ['full time', 'full-time', 'part time', 'part-time', 'contract', 'temporary', 'permanent']):
                metadata["time_type"] = text
                break
        if metadata["time_type"]:
            break

    # Look for posted date
    for pattern in [
        ('time', {}),
        ('span', {'class': re.compile(r'date|posted|time', re.I)}),
        ('div', {'class': re.compile(r'date|posted', re.I)}),
    ]:
        el = soup.find(pattern[0], pattern[1])
        if el:
            # Check for datetime attribute first
            dt = el.get('datetime', '')
            if dt:
                metadata["posted_date"] = dt
                break
            text = el.get_text(strip=True)
            if any(x in text.lower() for x in ['posted', 'days ago', 'week', 'month', 'today', 'yesterday']):
                metadata["posted_date"] = text
                break

    return metadata


def extract_description_from_html(html: str) -> str:
    """Extract job description from a detail page HTML."""
    soup = BeautifulSoup(html, 'html.parser')

    # Try Workable-style sections first (data-ui="job-description")
    desc_section = soup.find('section', attrs={'data-ui': 'job-description'})
    if desc_section:
        req_section = soup.find('section', attrs={'data-ui': 'job-requirements'})
        ben_section = soup.find('section', attrs={'data-ui': 'job-benefits'})

        parts = []
        for section in [desc_section, req_section, ben_section]:
            if section:
                for tag in section.find_all(['script', 'style']):
                    tag.decompose()
                text = section.get_text(separator='\n', strip=True)
                if text:
                    parts.append(text)
        if parts:
            return '\n\n'.join(parts)

    # Try common description selectors
    selectors = [
        'div.content',
        'div.job-description',
        'div.description',
        'section.job-description',
        'div[class*="description"]',
        'article',
        'main',
    ]

    for selector in selectors:
        content = soup.select_one(selector)
        if content:
            for tag in content.find_all(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()
            text = content.get_text(separator='\n', strip=True)
            if len(text) > 100:
                return text

    return ""


def load_descriptions_from_local_files(company_dir: Path, jobs: list[Job]) -> int:
    """Try to match jobs with saved HTML detail files and extract descriptions and metadata."""
    success = 0

    # Get all HTML files that might be job detail pages
    detail_files = [f for f in company_dir.glob("*.html")
                    if '_files' not in str(f) and '@' not in f.name]

    for job in jobs:
        if job.description:  # Already has description
            continue

        # Try to find a matching file by job title
        job_title_lower = job.title.lower()
        for html_file in detail_files:
            file_name_lower = html_file.stem.lower()
            # Check if file name contains significant part of job title
            if job_title_lower[:20] in file_name_lower or file_name_lower[:20] in job_title_lower:
                with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                    html = f.read()

                desc = extract_description_from_html(html)
                if desc and len(desc) > 100:
                    job.description = desc
                    success += 1

                    # Also extract metadata
                    metadata = extract_job_metadata_from_html(html)
                    if metadata.get("remote_type") and not job.remote_type:
                        job.remote_type = metadata["remote_type"]
                    if metadata.get("time_type") and not job.time_type:
                        job.time_type = metadata["time_type"]
                    if metadata.get("posted_date") and not job.posted_date:
                        job.posted_date = metadata["posted_date"]
                    if metadata.get("location") and not job.location:
                        job.location = metadata["location"]

                    break

    return success


def fetch_description(job: Job, session: requests.Session) -> bool:
    """Fetch job description and metadata from detail page."""
    if not job.url or job.description:  # Skip if no URL or already has description
        return bool(job.description)

    try:
        response = session.get(job.url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        # Extract description
        desc = extract_description_from_html(response.text)
        if desc:
            job.description = desc

        # Extract metadata (remote_type, time_type, posted_date)
        metadata = extract_job_metadata_from_html(response.text)
        if metadata.get("remote_type") and not job.remote_type:
            job.remote_type = metadata["remote_type"]
        if metadata.get("time_type") and not job.time_type:
            job.time_type = metadata["time_type"]
        if metadata.get("posted_date") and not job.posted_date:
            job.posted_date = metadata["posted_date"]
        if metadata.get("location") and not job.location:
            job.location = metadata["location"]

        return bool(desc)

    except Exception as e:
        print(f"    Error: {e}")
        return False


def scrape_company(folder_name: str, company_name: str = None):
    """Scrape jobs for a company folder."""
    company_dir = COMPANY_PAGES_DIR / folder_name

    if not company_dir.exists():
        print(f"Folder not found: {company_dir}")
        return

    company = company_name or folder_name.replace('_', ' ').replace('-', ' ').title()

    print("=" * 60)
    print(f"{company.upper()} JOB SCRAPER")
    print("=" * 60)

    # Find listing HTML and TXT files (some saved pages are .txt with HTML content)
    html_files = [f for f in company_dir.glob("*.html")
                  if '_files' not in str(f) and '@' not in f.name]
    txt_files = [f for f in company_dir.glob("*.txt")
                 if '_files' not in str(f)]
    all_files = html_files + txt_files

    if not all_files:
        print(f"No HTML/TXT files found in {company_dir}")
        return

    all_jobs = []
    seen_ids = set()

    for html_file in all_files:
        # Skip detail pages (often have specific job titles in name)
        if any(x in html_file.name.lower() for x in ['engineer', 'manager', 'analyst', 'senior', 'junior']):
            if 'jobs' not in html_file.name.lower() and 'careers' not in html_file.name.lower():
                continue

        print(f"Reading {html_file.name}...")

        with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()

        platform = detect_platform(html)
        print(f"  Detected platform: {platform}")

        jobs = extract_jobs(html, platform)

        for job in jobs:
            job.company = company
            key = job.job_id or job.title
            if key not in seen_ids:
                all_jobs.append(job)
                seen_ids.add(key)

    print(f"\nFound {len(all_jobs)} unique jobs")

    # Fetch descriptions (even if 0 jobs, we'll save empty result)
    if all_jobs:
        # First, try to load descriptions from saved local HTML files
        print("\nLoading descriptions from local files...")
        local_success = load_descriptions_from_local_files(company_dir, all_jobs)
        print(f"  Found {local_success} descriptions from local files")

        # Then try to fetch remaining descriptions online
        remaining = [j for j in all_jobs if not j.description]
        if remaining:
            print(f"\nFetching {len(remaining)} remaining descriptions online...")
            session = requests.Session()

            online_success = 0
            for i, job in enumerate(remaining, 1):
                print(f"[{i}/{len(remaining)}] {job.title[:40]}...")
                if fetch_description(job, session):
                    online_success += 1
                time.sleep(1)

            print(f"\nFetched {online_success}/{len(remaining)} descriptions online")

        total_success = sum(1 for j in all_jobs if j.description)
        print(f"\nTotal descriptions: {total_success}/{len(all_jobs)}")
    else:
        print("\nNo jobs to process - saving empty result")

    # Save - normalize filename (remove spaces, use underscores)
    OUTPUT_DIR.mkdir(exist_ok=True)
    normalized_name = folder_name.lower().replace(' ', '_').replace('-', '_')
    output_file = OUTPUT_DIR / f"{normalized_name}_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    output_data = {
        "company": company,
        "scraped_at": datetime.now().isoformat(),
        "total_jobs": len(all_jobs),
        "jobs_with_description": sum(1 for j in all_jobs if j.description),
        "jobs": [asdict(j) for j in all_jobs]
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_file}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for job in all_jobs[:10]:
        desc = job.description[:40] + "..." if job.description else "(no description)"
        print(f"- {job.title[:45]}")
        loc_info = job.location or 'No location'
        if job.remote_type:
            loc_info += f" ({job.remote_type})"
        if job.time_type:
            loc_info += f" - {job.time_type}"
        print(f"  {loc_info}")
        print(f"  {desc}")

    if len(all_jobs) > 10:
        print(f"\n... and {len(all_jobs) - 10} more")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generic_scraper.py <folder_name> [company_name]")
        print("\nAvailable folders:")
        for f in sorted(COMPANY_PAGES_DIR.iterdir()):
            if f.is_dir():
                print(f"  - {f.name}")
        sys.exit(1)

    folder = sys.argv[1]
    company = sys.argv[2] if len(sys.argv) > 2 else None
    scrape_company(folder, company)
