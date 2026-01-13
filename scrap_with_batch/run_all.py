#!/usr/bin/env python3
"""
Run All - Unified script to scrape jobs and run analysis

This script:
1. Runs LinkedIn scraper for all job titles in config
2. Runs Fintech scraper (if available)
3. Merges results into a unified jobs file
4. Retries fetching descriptions for jobs that are missing them
5. Runs AI analysis on new/unanalyzed jobs
6. Outputs Excel with results

Usage:
    python run_all.py                    # Run everything with defaults
    python run_all.py --scrape-only      # Only scrape, no analysis
    python run_all.py --analyze-only     # Only analyze existing jobs
    python run_all.py --time-range 24h   # Jobs from last 24 hours
    python run_all.py --limit 100        # Limit analysis to 100 jobs
    python run_all.py --retry-only       # Only retry fetching missing descriptions
    python run_all.py --no-retry         # Skip retrying missing descriptions
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Import scraper for retry functionality
from linkedin_scraper import LinkedInScraper, JobData

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# File paths
APP_DIR = Path(__file__).parent
CONFIG_FILE = APP_DIR / "config.json"
OUTPUT_DIR = APP_DIR / "output"

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(exist_ok=True)


def load_config() -> dict:
    """Load configuration from config.json"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Could not load config: {e}")
        return {}


def get_output_filename(prefix: str, ext: str = "json") -> str:
    """Generate dated output filename"""
    date_str = datetime.now().strftime('%Y%m%d')
    return f"{prefix}_{date_str}.{ext}"


def run_linkedin_scraper(config: dict, time_range: str, output_file: str) -> bool:
    """Run LinkedIn scraper for all job titles"""
    logger.info("=" * 60)
    logger.info("RUNNING LINKEDIN SCRAPER")
    logger.info("=" * 60)

    cmd = [
        sys.executable, "linkedin_scraper.py",
        "-a",  # All titles from config
        "-t", time_range,
        "-o", output_file
    ]

    logger.info(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(APP_DIR),
            capture_output=False,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"LinkedIn scraper failed: {e}")
        return False


def run_fintech_scraper(config: dict, output_file: str) -> bool:
    """Run Fintech scraper if available"""
    fintech_script = APP_DIR / "job_scraper.py"
    if not fintech_script.exists():
        logger.info("Fintech scraper not found, skipping")
        return True

    logger.info("=" * 60)
    logger.info("RUNNING FINTECH SCRAPER")
    logger.info("=" * 60)

    cmd = [
        sys.executable, "job_scraper.py",
        "-f",  # Fintech mode
        "-o", output_file
    ]

    logger.info(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(APP_DIR),
            capture_output=False,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Fintech scraper failed: {e}")
        return False


def merge_job_files(files: list, output_file: str) -> int:
    """Merge multiple job JSON files into one, deduplicating by URL"""
    all_jobs = {}

    for file_path in files:
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
                for job in jobs:
                    url = job.get('url', '')
                    if url and url not in all_jobs:
                        all_jobs[url] = job
                    elif url and url in all_jobs:
                        # Update if new job has description and old doesn't
                        old_desc = all_jobs[url].get('description', '')
                        new_desc = job.get('description', '')
                        if new_desc and not old_desc:
                            all_jobs[url] = job
                logger.info(f"Loaded {len(jobs)} jobs from {file_path}")
        except Exception as e:
            logger.warning(f"Could not load {file_path}: {e}")

    # Save merged file
    jobs_list = list(all_jobs.values())
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(jobs_list, f, indent=2, ensure_ascii=False)

    logger.info(f"Merged {len(jobs_list)} unique jobs -> {output_file}")
    return len(jobs_list)


def retry_missing_descriptions(jobs_file: str, max_retries: int = 3) -> int:
    """
    Retry fetching descriptions for jobs that are missing them.
    Uses sequential mode with longer delays to avoid rate limiting.

    Args:
        jobs_file: Path to the JSON file with jobs
        max_retries: Number of retry attempts per job

    Returns:
        Number of jobs that got descriptions after retry
    """
    import time
    import random

    if not os.path.exists(jobs_file):
        logger.warning(f"Jobs file not found: {jobs_file}")
        return 0

    # Load jobs
    try:
        with open(jobs_file, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
    except Exception as e:
        logger.error(f"Could not load jobs file: {e}")
        return 0

    # Find jobs without descriptions
    jobs_without_desc = []
    for i, job in enumerate(jobs):
        desc = job.get('description', '')
        if not desc or len(desc.strip()) < 50:
            jobs_without_desc.append((i, job))

    if not jobs_without_desc:
        logger.info("All jobs have descriptions!")
        return 0

    logger.info("=" * 60)
    logger.info(f"RETRYING DESCRIPTIONS FOR {len(jobs_without_desc)} JOBS")
    logger.info("=" * 60)
    logger.info("Using sequential mode with 4-6s delays to avoid rate limiting...")

    # Create scraper instance - force sequential/API mode for reliability
    scraper = LinkedInScraper(max_workers=1, max_retries=max_retries)
    scraper.use_sequential_mode = True
    scraper.use_api_fallback = True

    success_count = 0
    consecutive_failures = 0
    max_consecutive_failures = 10

    for idx, (original_idx, job_dict) in enumerate(jobs_without_desc):
        # Convert dict to JobData for the scraper
        job_data = JobData(
            title=job_dict.get('title', ''),
            company=job_dict.get('company', ''),
            location=job_dict.get('location', ''),
            url=job_dict.get('url', ''),
            posted_date=job_dict.get('posted_date', ''),
            description='',
            source=job_dict.get('source', 'LinkedIn'),
            scraped_at=job_dict.get('scraped_at', '')
        )

        logger.info(f"[{idx + 1}/{len(jobs_without_desc)}] Retrying: {job_data.title} at {job_data.company}")

        # Try to fetch description
        enriched_job = scraper._fetch_job_description(job_data)

        if enriched_job.description and len(enriched_job.description.strip()) > 50:
            # Update the original job in the list
            jobs[original_idx]['description'] = enriched_job.description
            success_count += 1
            consecutive_failures = 0
            logger.info(f"  SUCCESS - Got description ({len(enriched_job.description)} chars)")
        else:
            consecutive_failures += 1
            logger.info(f"  FAILED - Still no description")

            # If we're getting too many consecutive failures, take a longer break
            if consecutive_failures >= 5:
                logger.warning(f"  {consecutive_failures} consecutive failures - waiting 60s...")
                time.sleep(60)

            if consecutive_failures >= max_consecutive_failures:
                logger.error(f"Too many consecutive failures ({max_consecutive_failures}), stopping retry")
                break

        # Save progress every 20 jobs
        if (idx + 1) % 20 == 0 and success_count > 0:
            with open(jobs_file, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
            logger.info(f"  Progress saved: {success_count} new descriptions so far")

    # Save updated jobs back to file
    if success_count > 0:
        with open(jobs_file, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {success_count} jobs with descriptions -> {jobs_file}")

    # Log final stats
    final_without_desc = sum(1 for j in jobs if not j.get('description') or len(j.get('description', '').strip()) < 50)
    logger.info(f"Jobs still without descriptions: {final_without_desc}")

    return success_count


def get_analyzed_urls(analysis_file: str) -> set:
    """Get URLs that have already been analyzed"""
    analyzed = set()
    if os.path.exists(analysis_file):
        try:
            with open(analysis_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
                for r in results:
                    url = r.get('job_link', '')
                    if url:
                        analyzed.add(url)
        except:
            pass
    return analyzed


def run_analyzer(jobs_file: str, output_xlsx: str, output_json: str,
                 config: dict, limit: int = None, skip_analyzed: str = None) -> bool:
    """Run job analyzer"""
    logger.info("=" * 60)
    logger.info("RUNNING JOB ANALYZER")
    logger.info("=" * 60)

    cmd = [
        sys.executable, "job_analyzer.py",
        jobs_file,
        "-o", output_xlsx,
        "--model", config.get("ollama_model", "qwen2.5:7b")
    ]

    if limit:
        cmd.extend(["--limit", str(limit)])

    if skip_analyzed and os.path.exists(skip_analyzed):
        cmd.extend(["--skip-analyzed", skip_analyzed])

    logger.info(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(APP_DIR),
            capture_output=False,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Analyzer failed: {e}")
        return False


def print_summary(jobs_file: str, analysis_file: str):
    """Print summary of results"""
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    # Count jobs
    total_jobs = 0
    if os.path.exists(jobs_file):
        try:
            with open(jobs_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
                total_jobs = len(jobs)
                with_desc = sum(1 for j in jobs if j.get('description'))
                logger.info(f"Total jobs scraped: {total_jobs}")
                logger.info(f"Jobs with descriptions: {with_desc}")
        except:
            pass

    # Count analysis results
    if os.path.exists(analysis_file):
        try:
            with open(analysis_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
                matched = sum(1 for r in results if r.get('decision') == 'MATCHED')
                rejected = sum(1 for r in results if 'REJECTED' in r.get('decision', ''))
                logger.info(f"Jobs analyzed: {len(results)}")
                logger.info(f"  MATCHED: {matched}")
                logger.info(f"  REJECTED: {rejected}")

                if matched > 0:
                    logger.info("\nTop Matched Jobs:")
                    matched_jobs = [r for r in results if r.get('decision') == 'MATCHED']
                    matched_jobs.sort(key=lambda x: x.get('score', 0), reverse=True)
                    for job in matched_jobs[:5]:
                        logger.info(f"  [{job.get('score', 'N/A')}] {job.get('job_title', 'N/A')} at {job.get('company', 'N/A')}")
        except:
            pass


def main():
    parser = argparse.ArgumentParser(description='Run all scrapers and analysis')
    parser.add_argument('--scrape-only', action='store_true',
                        help='Only run scrapers, no analysis')
    parser.add_argument('--analyze-only', action='store_true',
                        help='Only run analysis on existing jobs')
    parser.add_argument('--linkedin-only', action='store_true',
                        help='Only run LinkedIn scraper')
    parser.add_argument('--fintech-only', action='store_true',
                        help='Only run Fintech scraper')
    parser.add_argument('-t', '--time-range', default='48h',
                        help='Time range for job search (default: 48h)')
    parser.add_argument('-l', '--limit', type=int,
                        help='Limit number of jobs to analyze')
    parser.add_argument('-o', '--output',
                        help='Output prefix for files')
    parser.add_argument('--no-skip', action='store_true',
                        help='Reanalyze all jobs (don\'t skip previously analyzed)')
    parser.add_argument('--retry-only', action='store_true',
                        help='Only retry fetching descriptions for jobs missing them')
    parser.add_argument('--no-retry', action='store_true',
                        help='Skip retrying missing descriptions')

    args = parser.parse_args()
    config = load_config()

    # Generate filenames (all in output folder)
    date_str = datetime.now().strftime('%Y%m%d')
    output_prefix = args.output or f"jobs_{date_str}"

    linkedin_file = str(OUTPUT_DIR / f"linkedin_jobs_{date_str}.json")
    fintech_file = str(OUTPUT_DIR / f"fintech_jobs_{date_str}.json")
    merged_file = str(OUTPUT_DIR / f"{output_prefix}.json")
    analysis_xlsx = str(OUTPUT_DIR / f"analysis_{date_str}.xlsx")
    analysis_json = str(OUTPUT_DIR / f"analysis_{date_str}.json")

    logger.info("=" * 60)
    logger.info(f"JOB SCRAPER & ANALYZER - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 60)
    logger.info(f"Time range: {args.time_range}")
    logger.info(f"Output: {merged_file}, {analysis_xlsx}")

    # Handle --retry-only mode
    if args.retry_only:
        if os.path.exists(merged_file):
            retry_missing_descriptions(merged_file, max_retries=2)
        else:
            logger.error(f"No jobs file found: {merged_file}")
        return

    # Run scrapers
    if not args.analyze_only:
        if not args.fintech_only:
            run_linkedin_scraper(config, args.time_range, linkedin_file)

        if not args.linkedin_only:
            run_fintech_scraper(config, fintech_file)

        # Merge all job files
        job_files = [linkedin_file, fintech_file]
        # Also include any existing merged file
        if os.path.exists(merged_file):
            job_files.append(merged_file)

        merge_job_files(job_files, merged_file)

        # Retry fetching descriptions for jobs that are missing them
        if not args.no_retry:
            retry_missing_descriptions(merged_file, max_retries=2)
        else:
            logger.info("Skipping description retry (--no-retry)")

    # Run analyzer
    if not args.scrape_only:
        if not os.path.exists(merged_file):
            logger.error(f"No jobs file found: {merged_file}")
            return

        skip_file = None if args.no_skip else analysis_json
        run_analyzer(
            merged_file,
            analysis_xlsx,
            analysis_json,
            config,
            limit=args.limit,
            skip_analyzed=skip_file
        )

    # Print summary
    print_summary(merged_file, analysis_json)

    logger.info("=" * 60)
    logger.info("DONE!")
    logger.info(f"Jobs: {merged_file}")
    logger.info(f"Analysis: {analysis_xlsx}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
