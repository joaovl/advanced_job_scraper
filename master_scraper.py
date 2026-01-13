#!/usr/bin/env python3
"""
Master Job Scraper - Unified Pipeline

Runs ALL scrapers and Claude AI analysis in one command:
1. LinkedIn scraper (public guest API)
2. Workday scrapers (46+ companies via API)
3. Company-specific scrapers (Greenhouse, Lever, Ashby, etc.)
4. Remote job boards (WeWorkRemotely, RemoteOK)
5. Consolidates all jobs into one file
6. Runs Claude AI filter to score and match jobs
7. Generates Excel summary report

Usage:
    python master_scraper.py                           # Run everything
    python master_scraper.py --location London         # Specify location
    python master_scraper.py --skip-linkedin           # Skip LinkedIn (if rate limited)
    python master_scraper.py --scrape-only             # Only scrape, no AI filter
    python master_scraper.py --ai-only                 # Only run AI filter on existing data
    python master_scraper.py --claude-model sonnet     # Use Claude Sonnet (default: haiku)
    python master_scraper.py --limit 100               # Limit AI filter to 100 jobs
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
BATCH_DIR = BASE_DIR / "scrap_with_batch"
COMPANY_PAGES_DIR = BASE_DIR / "Company_Pages"


def print_header(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(step: str):
    """Print a step indicator."""
    print(f"\n>>> {step}")


def run_command(cmd: list, description: str, cwd: str = None, timeout: int = 1800) -> tuple:
    """Run a command and return (success, message)."""
    print(f"  Running: {description}...")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode == 0:
            return True, "OK"
        else:
            return False, result.stderr[:200] if result.stderr else "Unknown error"
    except subprocess.TimeoutExpired:
        return False, f"Timeout ({timeout}s)"
    except Exception as e:
        return False, str(e)[:200]


def run_linkedin_scraper(location: str = "London, UK") -> dict:
    """Run LinkedIn scraper from scrap_with_batch."""
    print_step("LinkedIn Scraper")

    script = BATCH_DIR / "linkedin_scraper.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return {"success": False, "jobs": 0, "error": "Script not found"}

    # Run with all job titles from config
    success, msg = run_command(
        [sys.executable, str(script), "-a", "-l", location],
        "Scraping LinkedIn (all job titles)",
        cwd=str(BATCH_DIR),
        timeout=600  # 10 minutes
    )

    # Count jobs from output file
    jobs_count = 0
    today = datetime.now().strftime("%Y%m%d")
    output_file = BATCH_DIR / f"linkedin_jobs_{today}.json"
    if output_file.exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
                jobs_count = len(jobs)
        except:
            pass

    print(f"  Result: {'OK' if success else 'FAILED'} - {jobs_count} jobs")
    return {"success": success, "jobs": jobs_count, "file": str(output_file) if output_file.exists() else None}


def run_workday_scrapers(location: str = "London") -> dict:
    """Run Workday API scrapers for all companies."""
    print_step("Workday Scrapers (46+ companies)")

    script = SCRAPERS_DIR / "workday_scraper.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return {"success": False, "jobs": 0, "error": "Script not found"}

    success, msg = run_command(
        [sys.executable, str(script), "--all", "--search", location],
        "Scraping Workday companies",
        timeout=1800  # 30 minutes
    )

    # Count output files
    workday_files = list(OUTPUT_DIR.glob("*_workday_*.json"))
    today = datetime.now().strftime("%Y%m%d")
    today_files = [f for f in workday_files if today in f.name]

    jobs_count = 0
    for f in today_files:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                data = json.load(file)
                if isinstance(data, list):
                    jobs_count += len(data)
        except:
            pass

    print(f"  Result: {'OK' if success else 'PARTIAL'} - {jobs_count} jobs from {len(today_files)} companies")
    return {"success": success, "jobs": jobs_count, "files": len(today_files)}


def run_company_scrapers() -> dict:
    """Run scrapers for companies in Company_Pages folder."""
    print_step("Company-Specific Scrapers (Greenhouse, Lever, etc.)")

    script = SCRAPERS_DIR / "generic_scraper.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return {"success": False, "jobs": 0, "error": "Script not found"}

    if not COMPANY_PAGES_DIR.exists():
        print(f"  Company_Pages folder not found")
        return {"success": False, "jobs": 0, "error": "Folder not found"}

    # Get list of company folders
    companies = [d.name for d in COMPANY_PAGES_DIR.iterdir() if d.is_dir()]
    print(f"  Found {len(companies)} companies: {', '.join(companies[:10])}{'...' if len(companies) > 10 else ''}")

    total_jobs = 0
    successful = 0

    for company in companies:
        success, msg = run_command(
            [sys.executable, str(script), company],
            f"Scraping {company}",
            timeout=120
        )
        if success:
            successful += 1
            # Count jobs from output
            output_files = list(OUTPUT_DIR.glob(f"{company.lower()}_*.json"))
            for f in output_files:
                try:
                    with open(f, 'r', encoding='utf-8') as file:
                        data = json.load(file)
                        if isinstance(data, list):
                            total_jobs += len(data)
                except:
                    pass

    print(f"  Result: {successful}/{len(companies)} companies scraped - {total_jobs} jobs")
    return {"success": successful > 0, "jobs": total_jobs, "companies": successful}


def run_remote_scrapers() -> dict:
    """Run remote job board scrapers."""
    print_step("Remote Job Boards (WeWorkRemotely, RemoteOK)")

    script = SCRAPERS_DIR / "remote_jobs_scraper.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return {"success": False, "jobs": 0, "error": "Script not found"}

    success, msg = run_command(
        [sys.executable, str(script), "--source", "all"],
        "Scraping remote job boards",
        timeout=300
    )

    # Count output files
    today = datetime.now().strftime("%Y%m%d")
    remote_files = list(OUTPUT_DIR.glob(f"*_remote_{today}*.json"))

    jobs_count = 0
    for f in remote_files:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                data = json.load(file)
                if isinstance(data, list):
                    jobs_count += len(data)
        except:
            pass

    print(f"  Result: {'OK' if success else 'FAILED'} - {jobs_count} jobs")
    return {"success": success, "jobs": jobs_count}


def consolidate_all_jobs(location_filter: str = None) -> dict:
    """Consolidate all scraped jobs into one file."""
    print_step("Consolidating All Jobs")

    all_jobs = []
    seen_urls = set()
    today = datetime.now().strftime("%Y%m%d")

    # Sources to collect from
    sources = {
        "linkedin": BATCH_DIR / f"linkedin_jobs_{today}.json",
        "output_dir": OUTPUT_DIR
    }

    # Load LinkedIn jobs
    linkedin_file = sources["linkedin"]
    if linkedin_file.exists():
        try:
            with open(linkedin_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
                for job in jobs:
                    url = job.get('url', '')
                    if url and url not in seen_urls:
                        # Standardize format
                        all_jobs.append({
                            "title": job.get('title', ''),
                            "company": job.get('company', ''),
                            "url": url,
                            "description": job.get('description', ''),
                            "location": job.get('location', ''),
                            "remote_type": job.get('remote_type', 'Unknown'),
                            "time_type": job.get('time_type', ''),
                            "posted_date": job.get('posted_date', ''),
                            "job_id": job.get('job_id', ''),
                            "department": job.get('department', ''),
                            "source": "LinkedIn"
                        })
                        seen_urls.add(url)
            print(f"  LinkedIn: {len([j for j in all_jobs if j.get('source') == 'LinkedIn'])} jobs")
        except Exception as e:
            print(f"  LinkedIn: Error loading - {e}")

    # Load from output directory
    json_files = list(OUTPUT_DIR.glob("*.json"))
    # Filter to today's files
    today_files = [f for f in json_files if today in f.name and 'ai_filtered' not in f.name and 'all_jobs' not in f.name]

    for json_file in today_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            jobs_list = data if isinstance(data, list) else data.get('jobs', [])
            source = json_file.stem.split('_')[0].title()
            added = 0

            for job in jobs_list:
                url = job.get('url', '')
                if url and url not in seen_urls:
                    all_jobs.append({
                        "title": job.get('title', ''),
                        "company": job.get('company', source),
                        "url": url,
                        "description": job.get('description', ''),
                        "location": job.get('location', ''),
                        "remote_type": job.get('remote_type', 'Unknown'),
                        "time_type": job.get('time_type', ''),
                        "posted_date": job.get('posted_date', ''),
                        "job_id": job.get('job_id', ''),
                        "department": job.get('department', ''),
                        "source": source
                    })
                    seen_urls.add(url)
                    added += 1

            if added > 0:
                print(f"  {json_file.name}: {added} jobs")
        except Exception as e:
            continue

    # Apply location filter
    if location_filter:
        location_lower = location_filter.lower()
        filtered = [j for j in all_jobs if location_lower in j.get('location', '').lower()]
        print(f"  Location filter '{location_filter}': {len(all_jobs)} -> {len(filtered)} jobs")
        all_jobs = filtered

    # Save consolidated file
    output_file = OUTPUT_DIR / f"all_jobs_combined.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_jobs, f, indent=2, ensure_ascii=False)

    print(f"  Total: {len(all_jobs)} unique jobs saved to {output_file.name}")
    return {"success": True, "jobs": len(all_jobs), "file": str(output_file)}


def run_claude_ai_filter(claude_model: str = "haiku", limit: int = None, location: str = None) -> dict:
    """Run Claude AI filter to score and match jobs."""
    print_step(f"Claude AI Analysis (model: {claude_model})")

    script = BASE_DIR / "job_filter_ai.py"
    if not script.exists():
        print(f"  Script not found: {script}")
        return {"success": False, "matched": 0, "error": "Script not found"}

    # First, copy consolidated jobs to N8n/fintech_jobs.json for the AI filter
    all_jobs_file = OUTPUT_DIR / "all_jobs_combined.json"
    n8n_file = BASE_DIR / "N8n" / "fintech_jobs.json"

    if all_jobs_file.exists():
        try:
            with open(all_jobs_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
            n8n_file.parent.mkdir(exist_ok=True)
            with open(n8n_file, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
            print(f"  Copied {len(jobs)} jobs to {n8n_file.name}")
        except Exception as e:
            print(f"  Error copying jobs: {e}")

    # Build command
    cmd = [sys.executable, str(script), "--claude", "--claude-model", claude_model]

    if limit:
        cmd.extend(["--limit", str(limit)])

    if location:
        cmd.extend(["--location", location])

    print(f"  Running Claude AI filter...")
    success, msg = run_command(
        cmd,
        f"AI analysis with Claude {claude_model}",
        timeout=3600  # 1 hour for AI processing
    )

    # Find and count results
    matched = 0
    ai_files = list(OUTPUT_DIR.glob("ai_filtered_*.json"))
    ai_files = [f for f in ai_files if 'shortlist' not in f.name]

    if ai_files:
        latest = max(ai_files, key=lambda f: f.stat().st_mtime)
        try:
            with open(latest, 'r', encoding='utf-8') as f:
                results = json.load(f)
            matched = len([r for r in results if r.get('decision') == 'MATCHED'])
        except:
            pass

    print(f"  Result: {'OK' if success else 'FAILED'} - {matched} matched jobs")
    return {"success": success, "matched": matched}


def get_summary() -> dict:
    """Get summary of latest output files."""
    summary = {}

    # Find latest AI filtered files
    ai_files = list(OUTPUT_DIR.glob("ai_filtered_*.xlsx"))
    if ai_files:
        latest = max(ai_files, key=lambda f: f.stat().st_mtime)
        summary['excel_report'] = str(latest)

    shortlist_files = list(OUTPUT_DIR.glob("ai_filtered_*_shortlist.json"))
    if shortlist_files:
        latest = max(shortlist_files, key=lambda f: f.stat().st_mtime)
        try:
            with open(latest, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
            summary['shortlist'] = {
                'file': str(latest),
                'count': len(jobs)
            }
        except:
            pass

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Master Job Scraper - Run all scrapers and Claude AI analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python master_scraper.py                           # Run everything
    python master_scraper.py --location "London"       # Specify location
    python master_scraper.py --skip-linkedin           # Skip LinkedIn (if rate limited)
    python master_scraper.py --skip-workday            # Skip Workday scrapers
    python master_scraper.py --ai-only                 # Only run AI filter on existing data
    python master_scraper.py --scrape-only             # Only scrape, skip AI filter
    python master_scraper.py --claude-model sonnet     # Use Claude Sonnet model
    python master_scraper.py --quick                   # Skip slow scrapers (LinkedIn, company pages)
        """
    )

    parser.add_argument("--location", "-l", default="London",
                        help="Location to search (default: London)")
    parser.add_argument("--skip-linkedin", action="store_true",
                        help="Skip LinkedIn scraper")
    parser.add_argument("--skip-workday", action="store_true",
                        help="Skip Workday scrapers")
    parser.add_argument("--skip-company", action="store_true",
                        help="Skip company-specific scrapers")
    parser.add_argument("--skip-remote", action="store_true",
                        help="Skip remote job boards")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: skip slow scrapers (LinkedIn, company pages)")
    parser.add_argument("--ai-only", action="store_true",
                        help="Only run AI filter on existing data")
    parser.add_argument("--scrape-only", action="store_true",
                        help="Only run scrapers, skip AI filter")
    parser.add_argument("--claude-model", choices=["haiku", "sonnet", "opus"],
                        default="haiku", help="Claude model (default: haiku - faster/cheaper)")
    parser.add_argument("--limit", "-n", type=int,
                        help="Limit number of jobs to process in AI filter")

    args = parser.parse_args()

    # Quick mode shortcuts
    if args.quick:
        args.skip_linkedin = True
        args.skip_company = True

    OUTPUT_DIR.mkdir(exist_ok=True)

    start_time = datetime.now()

    print_header("MASTER JOB SCRAPER")
    print(f"  Location: {args.location}")
    print(f"  AI Model: Claude {args.claude_model}")
    print(f"  Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # Run scrapers (unless AI-only mode)
    if not args.ai_only:
        print_header("SCRAPING JOBS")

        if not args.skip_linkedin:
            results['linkedin'] = run_linkedin_scraper(f"{args.location}, UK")

        if not args.skip_workday:
            results['workday'] = run_workday_scrapers(args.location)

        if not args.skip_company:
            results['company'] = run_company_scrapers()

        if not args.skip_remote:
            results['remote'] = run_remote_scrapers()

        # Consolidate all jobs
        results['consolidate'] = consolidate_all_jobs(location_filter=args.location)

    # Run AI filter (unless scrape-only mode)
    if not args.scrape_only:
        print_header("AI ANALYSIS")
        results['ai'] = run_claude_ai_filter(
            claude_model=args.claude_model,
            limit=args.limit,
            location=args.location
        )

    # Summary
    end_time = datetime.now()
    duration = end_time - start_time

    print_header("PIPELINE COMPLETE")
    print(f"\n  Duration: {duration}")

    # Print results summary
    print("\n  Results:")
    total_jobs = 0
    for source, result in results.items():
        if isinstance(result, dict):
            jobs = result.get('jobs', result.get('matched', 0))
            status = "OK" if result.get('success', False) else "FAILED"
            print(f"    {source}: {status} ({jobs} jobs)")
            if source != 'ai':
                total_jobs += jobs

    # Show output files
    summary = get_summary()
    if summary:
        print("\n  Output Files:")
        if 'excel_report' in summary:
            print(f"    Excel: {summary['excel_report']}")
        if 'shortlist' in summary:
            print(f"    Shortlist: {summary['shortlist']['count']} matched jobs")
            print(f"    File: {summary['shortlist']['file']}")

    print("\n" + "=" * 70)
    print(f"  Total jobs scraped: {total_jobs}")
    if 'ai' in results:
        print(f"  Jobs matched by AI: {results['ai'].get('matched', 0)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
