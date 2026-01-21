#!/usr/bin/env python3
"""
LinkedIn Job Scraper

Scrapes jobs from LinkedIn's public guest API (no authentication needed).
Outputs jobs in the same JSON format as job_scraper.py for unified analysis.

Features:
- Skips jobs that already exist in output file (incremental scraping)
- Rate limit handling with exponential backoff
- Parallel description fetching with configurable workers

Usage:
    # Scrape with default settings from config.json
    python linkedin_scraper.py -a

    # Scrape with custom keywords
    python linkedin_scraper.py -k "Engineering Manager" -l "London, UK" -n 50

    # Scrape without fetching descriptions (faster)
    python linkedin_scraper.py --no-description

    # Use time range filter
    python linkedin_scraper.py -t 48h
"""

import argparse
import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_relative_date(relative_str: str) -> str:
    """Convert relative date like '2 hours ago' to ISO timestamp."""
    if not relative_str or relative_str == "N/A":
        return ""

    now = datetime.now()
    relative_str = relative_str.lower().strip()

    # Match patterns like "2 hours ago", "1 day ago", "3 weeks ago"
    match = re.match(r'(\d+)\s*(second|minute|hour|day|week|month)s?\s*ago', relative_str)
    if match:
        value = int(match.group(1))
        unit = match.group(2)

        if unit == 'second':
            delta = timedelta(seconds=value)
        elif unit == 'minute':
            delta = timedelta(minutes=value)
        elif unit == 'hour':
            delta = timedelta(hours=value)
        elif unit == 'day':
            delta = timedelta(days=value)
        elif unit == 'week':
            delta = timedelta(weeks=value)
        elif unit == 'month':
            delta = timedelta(days=value * 30)  # Approximate
        else:
            return ""

        posted_time = now - delta
        return posted_time.isoformat()

    return ""


@dataclass
class JobData:
    """Job data matching the format from job_scraper.py"""
    title: str
    company: str
    location: str
    url: str
    posted_date: str
    description: str = ""
    source: str = "LinkedIn"
    scraped_at: str = ""
    posted_timestamp: str = ""  # ISO timestamp calculated from posted_date

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LinkedInConfig:
    """Configuration for LinkedIn scraper"""
    BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    # API endpoint for job details (less rate limited)
    JOB_DETAIL_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    JOBS_PER_PAGE = 10  # LinkedIn returns 10 jobs per page

    # Rate limiting - VERY conservative settings to avoid 429s
    MIN_DELAY = 2.0           # Minimum delay between description fetches
    MAX_DELAY = 4.0           # Maximum delay between description fetches
    RATE_LIMIT_DELAY = 90     # Wait time after hitting rate limit
    BATCH_DELAY = 5.0         # Delay between batches
    SEARCH_DELAY = 8.0        # Delay between different keyword searches
    SEQUENTIAL_DELAY = 3.0    # Delay when in sequential mode (after rate limit)

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
        "Cache-Control": "no-cache",
    }


class LinkedInScraper:
    """LinkedIn job scraper using public guest API"""

    def __init__(self, max_workers: int = 2, max_retries: int = 3):
        self.session = self._setup_session()
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.lock = threading.Lock()
        self.existing_urls: Set[str] = set()
        self.use_api_fallback = False  # Switch to API after rate limit
        self.use_sequential_mode = False  # Process one at a time after rate limit
        self.rate_limit_count = 0  # Track how many times we've been rate limited

    def _setup_session(self) -> requests.Session:
        """Setup session with retry logic"""
        session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504]  # Don't auto-retry 429
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        return session

    def load_existing_jobs(self, output_file: str) -> Set[str]:
        """Load existing job URLs from output file to skip duplicates"""
        existing = set()
        if os.path.exists(output_file):
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    jobs = json.load(f)
                    for job in jobs:
                        url = job.get('url', '')
                        if url:
                            existing.add(url)
                    logger.info(f"Loaded {len(existing)} existing jobs from {output_file}")
            except Exception as e:
                logger.warning(f"Could not load existing jobs: {e}")
        return existing

    def _build_search_url(self, keywords: str, start: int = 0,
                          time_range_seconds: Optional[int] = None,
                          geo_id: Optional[str] = None,
                          location: Optional[str] = None,
                          easy_apply: bool = False) -> str:
        """Build LinkedIn search URL.

        Args:
            keywords: Job search keywords
            start: Pagination offset
            time_range_seconds: Time filter in seconds (e.g., 172800 for 48h)
            geo_id: LinkedIn geoId for location (preferred)
                Common geoIds:
                - Greater London Area: 90009496
                - London (city): 102257491
                - United Kingdom: 101165590
            location: Text location (deprecated, use geo_id instead)
            easy_apply: Filter for Easy Apply jobs only (f_EA=true)
        """
        params = {"keywords": keywords, "start": start}

        # Prefer geoId over text location
        if geo_id:
            params["geoId"] = geo_id
        elif location:
            params["location"] = location  # Fallback (deprecated)

        base = f"{LinkedInConfig.BASE_URL}?{'&'.join(f'{k}={quote(str(v))}' for k, v in params.items())}"

        if time_range_seconds and int(time_range_seconds) > 0:
            base = base + f"&f_TPR=r{int(time_range_seconds)}"

        # Easy Apply filter
        if easy_apply:
            base = base + "&f_AL=true"

        return base

    def _clean_job_url(self, url: str) -> str:
        """Clean job URL by removing query parameters"""
        return url.split("?")[0] if "?" in url else url

    def _extract_job_id(self, url: str) -> Optional[str]:
        """Extract job ID from LinkedIn job URL"""
        # URLs look like: https://www.linkedin.com/jobs/view/1234567890
        # or: https://uk.linkedin.com/jobs/view/1234567890-job-title
        match = re.search(r'/jobs/view/(\d+)', url)
        if match:
            return match.group(1)
        return None

    def _extract_job_data(self, job_card: BeautifulSoup, skip_promoted: bool = True) -> Optional[JobData]:
        """Extract job data from a job card HTML"""
        try:
            # Check if job is promoted/sponsored - skip these if requested
            if skip_promoted:
                # Check footer for "Promoted" text
                footer = job_card.find("footer")
                if footer:
                    footer_text = footer.get_text(strip=True).lower()
                    if "promoted" in footer_text:
                        return None

                # Also check for promoted badge/label anywhere in the card
                promoted_span = job_card.find("span", string=re.compile(r"promoted", re.IGNORECASE))
                if promoted_span:
                    return None

                # Check for any element with "promoted" in class name
                promoted_el = job_card.find(class_=re.compile(r"promoted", re.IGNORECASE))
                if promoted_el:
                    return None

            title = job_card.find("h3", class_="base-search-card__title").text.strip()
            company = job_card.find("h4", class_="base-search-card__subtitle").text.strip()
            location = job_card.find("span", class_="job-search-card__location").text.strip()
            job_link = self._clean_job_url(
                job_card.find("a", class_="base-card__full-link")["href"]
            )
            posted_date = job_card.find("time", class_="job-search-card__listdate")
            posted_date = posted_date.text.strip() if posted_date else "N/A"

            return JobData(
                title=title,
                company=company,
                location=location,
                url=job_link,
                posted_date=posted_date,
                scraped_at=datetime.now().isoformat(),
                posted_timestamp=parse_relative_date(posted_date)
            )
        except Exception as e:
            logger.debug(f"Failed to extract job data: {e}")
            return None

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a page and return BeautifulSoup object"""
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    delay = (2 ** attempt) + random.uniform(1, 3)
                    logger.info(f"  Retry {attempt + 1}/{self.max_retries}, waiting {delay:.1f}s...")
                    time.sleep(delay)

                response = self.session.get(url, headers=LinkedInConfig.HEADERS, timeout=30)

                if response.status_code == 429:
                    logger.warning(f"Rate limited! Waiting {LinkedInConfig.RATE_LIMIT_DELAY}s...")
                    time.sleep(LinkedInConfig.RATE_LIMIT_DELAY)
                    continue

                if response.status_code != 200:
                    logger.warning(f"Got status {response.status_code}")
                    continue

                return BeautifulSoup(response.text, "html.parser")

            except requests.Timeout:
                logger.warning(f"Timeout fetching page")
            except requests.RequestException as e:
                logger.warning(f"Request error: {e}")

        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job description from job detail page"""
        # Try JSON-LD first (most reliable)
        try:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, dict) and "description" in data:
                        desc = data.get("description")
                        if desc:
                            return desc.strip()
                except:
                    continue
        except:
            pass

        # Try common selectors
        selectors = [
            "div.show-more-less-html__markup",
            "div.description__text",
            "div.job-description__content",
            "div.jobs-description__container",
            "section.description",
            "div.job-description",
            "div.description",
            "div#job-details",
            "article",
        ]
        for sel in selectors:
            try:
                node = soup.select_one(sel)
                if node:
                    text = node.get_text(separator="\n").strip()
                    if text and len(text) > 50:
                        return text
            except:
                continue

        # Try meta tags
        for attr in [("name", "description"), ("property", "og:description")]:
            meta = soup.find("meta", attrs={attr[0]: attr[1]})
            if meta and meta.get("content"):
                desc = meta.get("content").strip()
                if len(desc) > 50:
                    return desc

        return None

    def _fetch_description_via_api(self, job_id: str, attempt: int = 0) -> Optional[str]:
        """Fetch job description using LinkedIn's job posting API (fallback method)"""
        api_url = LinkedInConfig.JOB_DETAIL_API.format(job_id=job_id)

        for retry in range(self.max_retries):
            try:
                # Longer delay in sequential/fallback mode
                delay = LinkedInConfig.SEQUENTIAL_DELAY + random.uniform(1, 3)
                if retry > 0:
                    delay = delay * (2 ** retry)  # Exponential backoff
                time.sleep(delay)

                response = self.session.get(
                    api_url,
                    headers=LinkedInConfig.HEADERS,
                    timeout=20
                )

                if response.status_code == 429:
                    logger.debug(f"API rate limited for job {job_id}, attempt {retry + 1}")
                    time.sleep(LinkedInConfig.RATE_LIMIT_DELAY)
                    continue

                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    # The API returns HTML with the job description
                    desc_div = soup.find("div", class_="show-more-less-html__markup")
                    if desc_div:
                        return str(desc_div)

                    # Try alternative selector
                    desc_div = soup.find("div", class_="description__text")
                    if desc_div:
                        return str(desc_div)

                    # Try to extract from the full HTML
                    description = self._extract_description(soup)
                    if description:
                        return description

                elif response.status_code != 200:
                    logger.debug(f"API returned {response.status_code} for job {job_id}")

            except Exception as e:
                logger.debug(f"API fetch error for job {job_id}: {e}")

        return None

    def _fetch_description_direct(self, job: JobData) -> Optional[str]:
        """Fetch job description by directly accessing job URL (faster but rate limited)"""
        for attempt in range(self.max_retries):
            try:
                # Add delay before request
                if attempt > 0:
                    delay = (2 ** attempt) + random.uniform(0.5, 1.5)
                    time.sleep(delay)
                else:
                    time.sleep(random.uniform(
                        LinkedInConfig.MIN_DELAY,
                        LinkedInConfig.MAX_DELAY
                    ))

                response = self.session.get(
                    job.url,
                    headers=LinkedInConfig.HEADERS,
                    timeout=15
                )

                if response.status_code == 429:
                    # Rate limited - signal to switch to API method
                    return "RATE_LIMITED"

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                description = self._extract_description(soup)

                if description and len(description) > 30:
                    return description

            except requests.Timeout:
                logger.debug(f"Timeout for {job.company}")
            except Exception as e:
                logger.debug(f"Error fetching {job.url}: {e}")

        return None

    def _fetch_job_description(self, job: JobData) -> JobData:
        """Fetch full job description - uses direct method first, API fallback after rate limit"""
        if not job.url:
            return job

        # Skip if already has description
        if job.description and len(job.description) > 50:
            return job

        # Check if we should use API fallback (after rate limit was hit)
        if self.use_api_fallback or self.use_sequential_mode:
            job_id = self._extract_job_id(job.url)
            if job_id:
                description = self._fetch_description_via_api(job_id)
                if description and len(description) > 30:
                    job.description = description
            return job

        # Try direct URL method first (faster)
        description = self._fetch_description_direct(job)

        if description == "RATE_LIMITED":
            # Switch to sequential/API fallback mode
            with self.lock:
                self.rate_limit_count += 1
                if not self.use_sequential_mode:
                    logger.warning(f"Rate limited! Waiting {LinkedInConfig.RATE_LIMIT_DELAY}s then switching to sequential mode...")
                    self.use_sequential_mode = True
                    self.use_api_fallback = True

            # Wait before retrying
            time.sleep(LinkedInConfig.RATE_LIMIT_DELAY)

            # Try API for this job
            job_id = self._extract_job_id(job.url)
            if job_id:
                description = self._fetch_description_via_api(job_id)
                if description and len(description) > 30:
                    job.description = description
        elif description and len(description) > 30:
            job.description = description

        return job

    def _fetch_page_jobs(self, keywords: str, start: int,
                         time_range_seconds: Optional[int] = None,
                         geo_id: Optional[str] = None,
                         location: Optional[str] = None,
                         easy_apply: bool = False,
                         skip_promoted: bool = True) -> tuple[List[JobData], int]:
        """Fetch jobs from a single search page. Returns (jobs, promoted_count)."""
        url = self._build_search_url(keywords, start, time_range_seconds, geo_id, location, easy_apply)
        soup = self._fetch_page(url)

        if not soup:
            return [], 0

        job_cards = soup.find_all("div", class_="base-card")

        jobs = []
        promoted_count = 0
        for card in job_cards:
            job = self._extract_job_data(card, skip_promoted=skip_promoted)
            if job:
                jobs.append(job)
            elif skip_promoted:
                # Job was skipped (likely promoted)
                promoted_count += 1
        return jobs, promoted_count

    def scrape_jobs(self, keywords: str,
                    geo_id: Optional[str] = None,
                    location: Optional[str] = None,
                    max_jobs: Optional[int] = None,
                    fetch_description: bool = True,
                    time_range_seconds: Optional[int] = None,
                    existing_urls: Optional[Set[str]] = None,
                    skip_promoted: bool = True,
                    easy_apply: bool = False) -> List[JobData]:
        """
        Scrape LinkedIn jobs matching criteria.

        Args:
            keywords: Job search keywords
            geo_id: LinkedIn geoId for location (preferred)
                Common geoIds:
                - Greater London Area: 90009496
                - London (city): 102257491
                - United Kingdom: 101165590
            location: Text location (deprecated, use geo_id instead)
            max_jobs: Maximum jobs to fetch (None or 0 = unlimited)
            fetch_description: Whether to fetch full descriptions
            time_range_seconds: Only jobs posted within this time range
            existing_urls: Set of URLs to skip (already scraped)
            skip_promoted: Whether to skip promoted/sponsored job listings
            easy_apply: Filter for Easy Apply jobs only

        Returns:
            List of JobData objects
        """
        all_jobs = []
        seen_urls = existing_urls.copy() if existing_urls else set()
        skipped_count = 0
        total_promoted_skipped = 0

        # None or 0 means unlimited
        target = max_jobs if max_jobs else None
        consecutive_empty = 0
        max_consecutive_empty = 3

        location_str = f"geoId={geo_id}" if geo_id else location or "unspecified"
        logger.info(f"Searching LinkedIn for: {keywords} in {location_str}")
        logger.info(f"Target: {max_jobs if max_jobs else 'UNLIMITED'} jobs")
        logger.info(f"Skip promoted: {skip_promoted}, Easy Apply: {easy_apply}")
        if existing_urls:
            logger.info(f"Will skip {len(existing_urls)} existing jobs")

        page_idx = 0

        # Sequential page fetching with delays
        while consecutive_empty < max_consecutive_empty:
            # Check if we've reached the target (if set)
            if target and len(all_jobs) >= target:
                break

            start = page_idx * LinkedInConfig.JOBS_PER_PAGE

            # Add delay between pages
            if page_idx > 0:
                delay = random.uniform(0.5, 1.5)
                time.sleep(delay)

            page_jobs, promoted_count = self._fetch_page_jobs(
                keywords, start, time_range_seconds, geo_id, location, easy_apply, skip_promoted
            )
            total_promoted_skipped += promoted_count

            if page_jobs:
                new_jobs = 0
                for job in page_jobs:
                    if job.url and job.url not in seen_urls:
                        seen_urls.add(job.url)
                        all_jobs.append(job)
                        new_jobs += 1
                    elif job.url in seen_urls:
                        skipped_count += 1

                promoted_msg = f", {promoted_count} promoted" if promoted_count > 0 else ""
                logger.info(f"Page {page_idx + 1}: {len(page_jobs)} jobs, {new_jobs} new, {skipped_count} skipped{promoted_msg} (total: {len(all_jobs)})")

                if new_jobs == 0:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0
            else:
                logger.info(f"Page {page_idx + 1}: empty or error")
                consecutive_empty += 1

            page_idx += 1

            if max_jobs and len(all_jobs) >= max_jobs:
                break

            # Batch delay every 5 pages
            if page_idx % 5 == 0:
                logger.info(f"  Pausing {LinkedInConfig.BATCH_DELAY}s...")
                time.sleep(LinkedInConfig.BATCH_DELAY)

        promoted_msg = f", {total_promoted_skipped} promoted" if total_promoted_skipped > 0 else ""
        logger.info(f"Found {len(all_jobs)} new unique jobs (skipped {skipped_count} existing{promoted_msg})")

        # Fetch descriptions with parallel workers (switches to sequential if rate limited)
        if fetch_description and all_jobs:
            # Filter jobs that need descriptions
            jobs_needing_desc = [j for j in all_jobs if not j.description or len(j.description) < 50]
            logger.info(f"Fetching descriptions for {len(jobs_needing_desc)} jobs ({self.max_workers} workers)...")

            enriched = []
            batch_size = 5  # Smaller batches to be more conservative

            for i in range(0, len(jobs_needing_desc), batch_size):
                batch = jobs_needing_desc[i:i + batch_size]

                # Check if we should switch to sequential mode
                if self.use_sequential_mode:
                    # Process remaining jobs one at a time
                    logger.info(f"Processing remaining {len(jobs_needing_desc) - i} jobs sequentially...")
                    for j, job in enumerate(jobs_needing_desc[i:]):
                        try:
                            enriched_job = self._fetch_job_description(job)
                            enriched.append(enriched_job)

                            # Progress update every 10 jobs
                            if (j + 1) % 10 == 0:
                                with_desc = sum(1 for jb in enriched if jb.description)
                                logger.info(f"Sequential progress: {len(enriched)}/{len(jobs_needing_desc)} jobs, {with_desc} with descriptions")
                        except Exception as e:
                            logger.error(f"Error enriching: {e}")
                            enriched.append(job)
                    break  # Exit the batch loop since we processed everything sequentially
                else:
                    # Parallel processing with limited workers
                    with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        futures = {
                            executor.submit(self._fetch_job_description, job): job
                            for job in batch
                        }

                        for future in as_completed(futures):
                            try:
                                enriched.append(future.result())
                            except Exception as e:
                                logger.error(f"Error enriching: {e}")

                # Progress update
                completed = len(enriched)
                if completed % 10 == 0 or completed == len(jobs_needing_desc):
                    with_desc = sum(1 for j in enriched if j.description)
                    logger.info(f"Progress: {completed}/{len(jobs_needing_desc)} jobs, {with_desc} with descriptions")

                # Pause between batches (longer pause to avoid rate limiting)
                if i + batch_size < len(jobs_needing_desc) and not self.use_sequential_mode:
                    pause = random.uniform(LinkedInConfig.BATCH_DELAY, LinkedInConfig.BATCH_DELAY + 3)
                    logger.debug(f"Pausing {pause:.1f}s between batches...")
                    time.sleep(pause)

            # Merge enriched jobs back
            enriched_map = {j.url: j for j in enriched}
            for i, job in enumerate(all_jobs):
                if job.url in enriched_map:
                    all_jobs[i] = enriched_map[job.url]

            with_desc = sum(1 for j in all_jobs if j.description)
            without_desc = len(all_jobs) - with_desc
            logger.info(f"Descriptions: {with_desc}/{len(all_jobs)} fetched successfully")
            if without_desc > 0:
                logger.warning(f"{without_desc} jobs still missing descriptions - will retry in run_all.py")

        return all_jobs

    def save_results(self, jobs: List[JobData], filename: str, merge_existing: bool = True) -> None:
        """Save jobs to JSON file, optionally merging with existing"""
        existing_jobs = []
        if merge_existing and os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    existing_jobs = json.load(f)
                logger.info(f"Merging with {len(existing_jobs)} existing jobs")
            except Exception as e:
                logger.warning(f"Could not load existing file: {e}")

        # Create map of existing jobs by URL
        existing_map = {j.get('url', ''): j for j in existing_jobs if j.get('url')}

        # Add/update with new jobs
        for job in jobs:
            job_dict = job.to_dict()
            url = job_dict.get('url', '')
            if url:
                # Update existing or add new
                if url in existing_map:
                    # Only update if new job has description and old doesn't
                    old_desc = existing_map[url].get('description', '')
                    new_desc = job_dict.get('description', '')
                    if new_desc and not old_desc:
                        existing_map[url] = job_dict
                else:
                    existing_map[url] = job_dict

        # Convert back to list
        all_jobs = list(existing_map.values())

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_jobs, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(all_jobs)} total jobs to {filename}")


def parse_time_range(time_str: str) -> Optional[int]:
    """Parse time range string to seconds"""
    if not time_str:
        return None
    time_str = time_str.lower().strip()
    if time_str.endswith('h'):
        return int(time_str[:-1]) * 3600
    elif time_str.endswith('d'):
        return int(time_str[:-1]) * 86400
    elif time_str.endswith('w'):
        return int(time_str[:-1]) * 604800
    return None


def load_config() -> Dict:
    """Load configuration from config.json"""
    config_path = Path(__file__).parent / "config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load config: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description="LinkedIn Job Scraper")
    parser.add_argument("-k", "--keywords", help="Search keywords")
    parser.add_argument("-g", "--geo-id",
                        help="LinkedIn geoId for location (e.g., 90009496 for Greater London)")
    parser.add_argument("-l", "--location",
                        help="Text location - DEPRECATED, use --geo-id instead")
    parser.add_argument("-n", "--max-jobs", type=int, default=0,
                        help="Max jobs per search (0 = unlimited, scrape all)")
    parser.add_argument("-t", "--time-range", help="Time filter: 2h, 6h, 24h, 48h, 7d, 30d")
    parser.add_argument("--max-age", help="Local filter: only keep jobs posted within this time (e.g., 2h, 6h, 12h)")
    parser.add_argument("-a", "--all-titles", action="store_true",
                        help="Search all job titles from config")
    parser.add_argument("-nd", "--no-description", action="store_true",
                        help="Don't fetch job descriptions (faster)")
    parser.add_argument("-w", "--workers", type=int, default=2,
                        help="Parallel workers for descriptions (default: 2, use 1 for safest)")
    parser.add_argument("-o", "--output", help="Output filename")
    parser.add_argument("--no-merge", action="store_true",
                        help="Don't merge with existing file (overwrite)")
    parser.add_argument("--include-promoted", action="store_true",
                        help="Include promoted/sponsored job listings (excluded by default)")
    parser.add_argument("--easy-apply", action="store_true",
                        help="Only Easy Apply jobs (typically fewer applicants)")

    args = parser.parse_args()
    config = load_config()

    # Setup scraper
    scraper = LinkedInScraper(max_workers=args.workers)

    # Determine output file
    output_file = args.output or f"linkedin_jobs_{datetime.now().strftime('%Y%m%d')}.json"

    # Load existing jobs to skip
    existing_urls = scraper.load_existing_jobs(output_file)

    # Get settings - prefer geo_id over location
    geo_id = args.geo_id or config.get("geo_id")
    location = args.location or config.get("location", "London, UK")

    # Warn about deprecated --location if used without --geo-id
    if args.location and not args.geo_id:
        logger.warning("--location is deprecated. Use --geo-id instead (e.g., -g 90009496 for Greater London)")

    time_range = args.time_range or config.get("time_range", "48h")
    time_range_seconds = parse_time_range(time_range)

    # 0 means unlimited (None)
    max_jobs = args.max_jobs if args.max_jobs > 0 else config.get("max_jobs_per_title", 0)
    if max_jobs == 0:
        max_jobs = None  # Truly unlimited

    easy_apply = args.easy_apply or config.get("easy_apply", False)

    all_jobs = []

    if args.all_titles:
        # Search all job titles from config
        job_titles = config.get("job_titles", ["Engineering Manager"])
        logger.info(f"Searching {len(job_titles)} job titles...")

        for i, title in enumerate(job_titles):
            logger.info(f"\n=== [{i+1}/{len(job_titles)}] Searching: {title} ===")

            jobs = scraper.scrape_jobs(
                keywords=title,
                geo_id=geo_id,
                location=location if not geo_id else None,
                max_jobs=max_jobs,
                fetch_description=not args.no_description,
                time_range_seconds=time_range_seconds,
                existing_urls=existing_urls,
                skip_promoted=not args.include_promoted,
                easy_apply=easy_apply
            )

            all_jobs.extend(jobs)

            # Update existing URLs to avoid duplicates in next search
            for job in jobs:
                if job.url:
                    existing_urls.add(job.url)

            # Delay between different searches
            if i < len(job_titles) - 1:
                delay = random.uniform(3, 6)
                logger.info(f"Waiting {delay:.1f}s before next search...")
                time.sleep(delay)

    elif args.keywords:
        # Single keyword search
        all_jobs = scraper.scrape_jobs(
            keywords=args.keywords,
            geo_id=geo_id,
            location=location if not geo_id else None,
            max_jobs=max_jobs,
            fetch_description=not args.no_description,
            time_range_seconds=time_range_seconds,
            existing_urls=existing_urls,
            skip_promoted=not args.include_promoted,
            easy_apply=easy_apply
        )
    else:
        logger.error("Please specify --keywords or --all-titles")
        return

    # Apply local max-age filter if specified
    if args.max_age and all_jobs:
        max_age_seconds = parse_time_range(args.max_age)
        if max_age_seconds:
            cutoff_time = datetime.now() - timedelta(seconds=max_age_seconds)
            original_count = len(all_jobs)
            filtered_jobs = []
            for job in all_jobs:
                job_dict = job.to_dict() if hasattr(job, 'to_dict') else job
                posted_ts = job_dict.get('posted_timestamp', '')
                if posted_ts:
                    try:
                        posted_dt = datetime.fromisoformat(posted_ts)
                        if posted_dt >= cutoff_time:
                            filtered_jobs.append(job)
                    except:
                        filtered_jobs.append(job)  # Keep if can't parse
                else:
                    # No timestamp, check posted_date for recent indicators
                    posted_date = job_dict.get('posted_date', '').lower()
                    if 'hour' in posted_date or 'minute' in posted_date or 'second' in posted_date:
                        filtered_jobs.append(job)
            all_jobs = filtered_jobs
            logger.info(f"Max-age filter ({args.max_age}): {original_count} -> {len(all_jobs)} jobs")

    # Save results
    if all_jobs:
        scraper.save_results(all_jobs, output_file, merge_existing=not args.no_merge)
        logger.info(f"\nDone! Scraped {len(all_jobs)} new jobs -> {output_file}")
    else:
        logger.info("No new jobs found")


if __name__ == "__main__":
    main()
