#!/usr/bin/env python3
"""
Master Job Pipeline - Runs ALL scrapers and AI filter in one command.

This unified script:
1. Runs Workday scrapers (39+ companies via API)
2. Runs Playwright scrapers (Cisco, Google, IBM, Apple, Meta, Amazon)
3. Runs HTML-based scrapers (Greenhouse, Lever, Ashby, etc.)
4. Runs LinkedIn scraper (public guest API)
5. Runs Remote job boards (WeWorkRemotely, RemoteOK)
6. Consolidates all jobs into N8n/fintech_jobs.json
7. Runs AI filter with Claude to score jobs against your CV
8. Generates Excel and JSON reports

Usage:
    python run_pipeline.py                           # Run everything
    python run_pipeline.py --location London         # Specify location
    python run_pipeline.py --skip-linkedin           # Skip LinkedIn (rate limited)
    python run_pipeline.py --skip-remote             # Skip remote job boards
    python run_pipeline.py --ai-only                 # Only run AI filter on existing data
    python run_pipeline.py --scrape-only             # Only scrape, no AI filter
    python run_pipeline.py --claude-model haiku      # Use haiku (faster/cheaper)
    python run_pipeline.py --limit 100               # Limit AI filter to 100 jobs
"""

import json
import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
SCRAPERS_DIR = BASE_DIR / "scrapers"
N8N_DIR = BASE_DIR / "N8n"
BATCH_DIR = BASE_DIR / "scrap_with_batch"


def print_header(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def run_command(cmd: list, description: str, cwd: str = None) -> bool:
    """Run a command and return success status."""
    print(f"\n{description}...")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or str(BASE_DIR),
            timeout=36000  # 10 hour timeout (can run overnight)
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT: {description}")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def run_workday_scrapers(location: str = "London") -> bool:
    """Run Workday API scrapers for 39+ companies."""
    print_header("WORKDAY SCRAPERS (39+ companies)")

    script = SCRAPERS_DIR / "workday_scraper.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return False

    return run_command(
        [sys.executable, str(script), "--all", "--search", location],
        "Scraping Workday companies"
    )


def run_playwright_scrapers(location: str = "London") -> bool:
    """Run Playwright scrapers for major tech companies."""
    print_header("PLAYWRIGHT SCRAPERS (Cisco, Google, IBM, Apple, Meta, Amazon)")

    script = SCRAPERS_DIR / "playwright_scraper_v2.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return False

    return run_command(
        [sys.executable, str(script), "--all", "--location", location],
        "Scraping with Playwright"
    )


def run_html_scrapers() -> bool:
    """Run HTML-based scrapers (Greenhouse, Lever, Ashby, etc.)."""
    print_header("HTML SCRAPERS (Greenhouse, Lever, Ashby, etc.)")

    script = SCRAPERS_DIR / "run_html_scrapers.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return True  # Not critical

    return run_command(
        [sys.executable, str(script)],
        "Running HTML scrapers"
    )


def run_company_scrapers() -> bool:
    """Run company-specific scrapers (HSBC, Barclays, Stripe, Revolut, etc.)."""
    print_header("COMPANY-SPECIFIC SCRAPERS (HSBC, Barclays, Stripe, Fintech, etc.)")

    script = SCRAPERS_DIR / "run_all.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return True  # Not critical

    return run_command(
        [sys.executable, str(script)],
        "Running company-specific scrapers"
    )


def run_linkedin_scraper(location: str = "London, UK") -> bool:
    """Run LinkedIn scraper (public guest API)."""
    print_header("LINKEDIN SCRAPER")

    script = BATCH_DIR / "linkedin_scraper.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return True  # Not critical

    # Check for config
    config_file = BATCH_DIR / "config.json"
    if not config_file.exists():
        print("  LinkedIn config not found, using default settings")
        # Run with defaults
        return run_command(
            [sys.executable, str(script), "-k", "Engineering Manager", "-l", location, "-n", "50"],
            "Scraping LinkedIn",
            cwd=str(BATCH_DIR)
        )

    # Run with config (all job titles) - explicitly pass location to override config
    print(f"  Location: {location}")
    return run_command(
        [sys.executable, str(script), "-a", "-l", location],
        "Scraping LinkedIn (all job titles from config)",
        cwd=str(BATCH_DIR)
    )


def run_remote_scrapers() -> bool:
    """Run remote job board scrapers (WeWorkRemotely, RemoteOK)."""
    print_header("REMOTE JOB BOARDS (WeWorkRemotely, RemoteOK)")

    script = SCRAPERS_DIR / "remote_jobs_scraper.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return True  # Not critical

    return run_command(
        [sys.executable, str(script), "--source", "all"],
        "Scraping remote job boards"
    )


def consolidate_jobs() -> bool:
    """Consolidate all jobs into N8n/fintech_jobs.json."""
    print_header("CONSOLIDATING ALL JOBS")

    script = BASE_DIR / "export_to_n8n.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return False

    return run_command(
        [sys.executable, str(script), "--latest"],
        "Exporting to N8n format"
    )


def copy_linkedin_jobs_to_n8n() -> int:
    """Copy LinkedIn jobs to the N8n consolidation."""
    linkedin_files = list(BATCH_DIR.glob("linkedin_jobs_*.json"))
    if not linkedin_files:
        return 0

    # Get most recent
    linkedin_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    latest = linkedin_files[0]

    try:
        with open(latest, 'r', encoding='utf-8') as f:
            linkedin_jobs = json.load(f)

        # Read existing N8n jobs
        n8n_file = N8N_DIR / "fintech_jobs.json"
        if n8n_file.exists():
            with open(n8n_file, 'r', encoding='utf-8') as f:
                n8n_jobs = json.load(f)
        else:
            n8n_jobs = []

        # Get existing URLs
        existing_urls = {j.get('url', '') for j in n8n_jobs}

        # Add LinkedIn jobs
        added = 0
        for job in linkedin_jobs:
            url = job.get('url', '')
            if url and url not in existing_urls:
                # Convert to N8n format
                n8n_job = {
                    "title": job.get('title', ''),
                    "company": job.get('company', ''),
                    "url": url,
                    "description": job.get('description', ''),
                    "location": job.get('location', ''),
                    "remote_type": "Unknown",
                    "time_type": "",
                    "posted_date": job.get('posted_date', ''),
                    "job_id": "",
                    "department": "",
                }
                n8n_jobs.append(n8n_job)
                existing_urls.add(url)
                added += 1

        # Save back
        with open(n8n_file, 'w', encoding='utf-8') as f:
            json.dump(n8n_jobs, f, indent=2, ensure_ascii=False)

        print(f"  Added {added} LinkedIn jobs to N8n consolidation")
        return added

    except Exception as e:
        print(f"  Error copying LinkedIn jobs: {e}")
        return 0


def run_ai_filter(claude_model: str = "haiku", limit: int = None, location: str = None) -> bool:
    """Run AI filter with Claude to score jobs."""
    print_header("AI JOB FILTER (Claude)")

    script = BASE_DIR / "job_filter_ai.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return False

    cmd = [sys.executable, str(script), "--claude", "--claude-model", claude_model]

    if limit:
        cmd.extend(["--limit", str(limit)])

    if location:
        cmd.extend(["--location", location])

    return run_command(cmd, f"Running AI filter with Claude {claude_model}")


def get_latest_outputs() -> dict:
    """Get paths to latest output files."""
    outputs = {}

    # Master JSON
    master_files = list(OUTPUT_DIR.glob("master_jobs_*.json"))
    if master_files:
        master_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        outputs['master_json'] = master_files[0]

    # AI filtered
    ai_files = list(OUTPUT_DIR.glob("ai_filtered_*.json"))
    ai_files = [f for f in ai_files if 'shortlist' not in f.name]
    if ai_files:
        ai_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        outputs['ai_filtered_json'] = ai_files[0]

    # AI filtered shortlist
    shortlist_files = list(OUTPUT_DIR.glob("ai_filtered_*_shortlist.json"))
    if shortlist_files:
        shortlist_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        outputs['shortlist_json'] = shortlist_files[0]

    # AI filtered Excel
    excel_files = list(OUTPUT_DIR.glob("ai_filtered_*.xlsx"))
    if excel_files:
        excel_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        outputs['ai_filtered_excel'] = excel_files[0]

    # All jobs Excel
    all_excel = list(OUTPUT_DIR.glob("all_jobs_*.xlsx"))
    if all_excel:
        all_excel.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        outputs['all_jobs_excel'] = all_excel[0]

    return outputs


def count_jobs_in_file(filepath: Path) -> int:
    """Count jobs in a JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return len(data)
        elif isinstance(data, dict):
            return len(data.get('jobs', data.get('results', [])))
    except:
        pass
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Master Job Pipeline - Run all scrapers and AI filter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_pipeline.py                           # Run everything
    python run_pipeline.py --location "London, UK"   # Specify location
    python run_pipeline.py --skip-linkedin           # Skip LinkedIn (if rate limited)
    python run_pipeline.py --ai-only                 # Only run AI filter
    python run_pipeline.py --scrape-only             # Only scrape, skip AI filter
    python run_pipeline.py --quick                   # Skip slow scrapers (LinkedIn, Playwright)
        """
    )

    parser.add_argument("--location", "-l", default="London",
                        help="Location to search (default: London)")
    parser.add_argument("--skip-workday", action="store_true",
                        help="Skip Workday scrapers")
    parser.add_argument("--skip-playwright", action="store_true",
                        help="Skip Playwright scrapers (Cisco, Google, etc.)")
    parser.add_argument("--skip-html", action="store_true",
                        help="Skip HTML-based scrapers")
    parser.add_argument("--skip-linkedin", action="store_true",
                        help="Skip LinkedIn scraper")
    parser.add_argument("--skip-remote", action="store_true",
                        help="Skip remote job boards")
    parser.add_argument("--skip-company", action="store_true",
                        help="Skip company-specific scrapers (HSBC, Barclays, etc.)")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: skip slow scrapers (LinkedIn, Playwright, company)")
    parser.add_argument("--ai-only", action="store_true",
                        help="Only run AI filter on existing data")
    parser.add_argument("--scrape-only", action="store_true",
                        help="Only run scrapers, skip AI filter")
    parser.add_argument("--claude-model", choices=["haiku", "sonnet", "opus"],
                        default="haiku", help="Claude model (default: haiku)")
    parser.add_argument("--limit", "-n", type=int,
                        help="Limit number of jobs to process in AI filter")

    args = parser.parse_args()

    # Quick mode
    if args.quick:
        args.skip_linkedin = True
        args.skip_playwright = True
        args.skip_company = True

    OUTPUT_DIR.mkdir(exist_ok=True)

    start_time = datetime.now()

    print("=" * 70)
    print("MASTER JOB PIPELINE")
    print("=" * 70)
    print(f"Location: {args.location}")
    print(f"AI Model: Claude {args.claude_model}")
    print(f"Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    scraper_results = {}

    if not args.ai_only:
        # Run scrapers
        if not args.skip_workday:
            scraper_results['workday'] = run_workday_scrapers(args.location)

        if not args.skip_playwright:
            scraper_results['playwright'] = run_playwright_scrapers(args.location)

        if not args.skip_html:
            scraper_results['html'] = run_html_scrapers()

        if not args.skip_company:
            scraper_results['company'] = run_company_scrapers()

        if not args.skip_linkedin:
            scraper_results['linkedin'] = run_linkedin_scraper(f"{args.location}, UK")

        if not args.skip_remote:
            scraper_results['remote'] = run_remote_scrapers()

        # Consolidate all jobs (includes output/, Company_Pages/, and LinkedIn)
        consolidate_jobs()

    if not args.scrape_only:
        # Run AI filter
        run_ai_filter(
            claude_model=args.claude_model,
            limit=args.limit,
            location=args.location
        )

    # Summary
    end_time = datetime.now()
    duration = end_time - start_time

    print_header("PIPELINE COMPLETE")

    print(f"\nDuration: {duration}")

    if scraper_results:
        print("\nScraper Results:")
        for scraper, success in scraper_results.items():
            status = "OK" if success else "FAILED"
            print(f"  {scraper}: {status}")

    # Show output files
    outputs = get_latest_outputs()
    if outputs:
        print("\nOutput Files:")
        for name, path in outputs.items():
            jobs = count_jobs_in_file(path)
            size = path.stat().st_size // 1024
            print(f"  {name}: {path.name} ({jobs} jobs, {size}KB)")

    # Show N8n file
    n8n_file = N8N_DIR / "fintech_jobs.json"
    if n8n_file.exists():
        jobs = count_jobs_in_file(n8n_file)
        print(f"\nN8n consolidated: {jobs} total jobs")

    # Highlight the key files
    if 'ai_filtered_excel' in outputs:
        print("\n" + "-" * 70)
        print("REVIEW YOUR JOBS:")
        print(f"  Excel: {outputs['ai_filtered_excel']}")
        if 'shortlist_json' in outputs:
            shortlist_count = count_jobs_in_file(outputs['shortlist_json'])
            print(f"  Shortlist: {shortlist_count} matched jobs in {outputs['shortlist_json'].name}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
