#!/usr/bin/env python3
"""
Master Job Scraper Runner

Runs company-specific scrapers.

Usage:
    python scrapers/run_all.py              # Run ALL scrapers
    python scrapers/run_all.py --new        # Only run scrapers with new/changed files
    python scrapers/run_all.py --status     # Show status of all folders
    python scrapers/run_all.py --company barclays  # Run specific company only
"""

import json
import hashlib
import subprocess
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Import Workday companies to avoid duplication
from workday_scraper import WORKDAY_COMPANIES

BASE_DIR = Path(__file__).parent.parent
SCRAPERS_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
COMPANY_PAGES_DIR = BASE_DIR / "Company_Pages"
STATE_FILE = SCRAPERS_DIR / ".scraper_state.json"

# Scraper configuration - maps company key to scraper details
# folder can be exact name or will be matched case-insensitively
SCRAPERS = {
    "barclays": {
        "script": "barclays_scraper.py",
        "type": "html",
        "folder": "Barclays",
    },
    "hsbc": {
        "script": "hsbc_scraper.py",
        "type": "api",
        "folder": "HSBC",
    },
    "savanta": {
        "script": "savanta_scraper.py",
        "type": "html",
        "folder": "Savanta",
    },
    "jlr": {
        "script": "jlr_scraper.py",
        "type": "html",
        "folder": "JLR",
    },
    "stripe": {
        "script": "stripe_scraper.py",
        "type": "html",
        "folder": "stripe",
    },
    "clearbank": {
        "script": "clearbank_scraper.py",
        "type": "html",
        "folder": "clear_bank",
    },
    "gocardless": {
        "script": "generic_scraper.py GoCardless GoCardless",
        "type": "html",
        "folder": "GoCardless",
    },
    "marqeta": {
        "script": "generic_scraper.py Marqeta Marqeta",
        "type": "html",
        "folder": "Marqeta",
    },
    "oaknorth": {
        "script": "generic_scraper.py oaknorth OakNorth",
        "type": "html",
        "folder": "oaknorth",
    },
    "rapyd": {
        "script": "generic_scraper.py Rapyd Rapyd",
        "type": "html",
        "folder": "Rapyd",
    },
    "thoughtmachine": {
        "script": "generic_scraper.py thoughtmachine 'Thought Machine'",
        "type": "html",
        "folder": "thoughtmachine",
    },
    "adyen": {
        "script": "generic_scraper.py Adyen Adyen",
        "type": "html",
        "folder": "Adyen",
    },
    "affirm": {
        "script": "generic_scraper.py Affirm Affirm",
        "type": "html",
        "folder": "Affirm",
    },
    "coinbase": {
        "script": "generic_scraper.py Coinbase Coinbase",
        "type": "html",
        "folder": "Coinbase",
    },
    "plaid": {
        "script": "generic_scraper.py plaid Plaid",
        "type": "html",
        "folder": "plaid",
    },
    "revolut": {
        "script": "generic_scraper.py Revolut Revolut",
        "type": "html",
        "folder": "Revolut",
    },
    "robinhood": {
        "script": "generic_scraper.py Robinhood Robinhood",
        "type": "html",
        "folder": "Robinhood",
    },
    "square": {
        "script": "generic_scraper.py Square Square",
        "type": "html",
        "folder": "Square",
    },
    "starling_bank": {
        "script": "generic_scraper.py 'Starling Bank' 'Starling Bank'",
        "type": "html",
        "folder": "Starling Bank",
    },
    "wise": {
        "script": "generic_scraper.py Wise Wise",
        "type": "html",
        "folder": "Wise",
    },
    "microsoft": {
        "script": "generic_scraper.py microsoft Microsoft",
        "type": "html",
        "folder": "microsoft",
    },
    "amazon": {
        "script": "generic_scraper.py amazon Amazon",
        "type": "html",
        "folder": "amazon",
    },
    "apple": {
        "script": "generic_scraper.py apple Apple",
        "type": "html",
        "folder": "apple",
    },
    "bmwgroup": {
        "script": "generic_scraper.py bmwgroup 'BMW Group'",
        "type": "html",
        "folder": "bmwgroup",
    },
    "cisco": {
        "script": "generic_scraper.py cisco Cisco",
        "type": "html",
        "folder": "cisco",
    },
    "google": {
        "script": "generic_scraper.py google Google",
        "type": "html",
        "folder": "google",
    },
    "ibm": {
        "script": "generic_scraper.py IBM IBM",
        "type": "html",
        "folder": "IBM",
    },
    "mercedes": {
        "script": "generic_scraper.py Mercedes-Benz 'Mercedes-Benz'",
        "type": "html",
        "folder": "Mercedes-Benz",
    },
    "netflix": {
        "script": "generic_scraper.py Netflix Netflix",
        "type": "html",
        "folder": "Netflix",
    },
    "oracle": {
        "script": "generic_scraper.py oracle Oracle",
        "type": "html",
        "folder": "oracle",
    },
    "salesforce": {
        "script": "generic_scraper.py salesforce Salesforce",
        "type": "html",
        "folder": "salesforce",
    },
    "waymo": {
        "script": "generic_scraper.py withwaymo Waymo",
        "type": "html",
        "folder": "withwaymo",
    },
}

# Dynamically add all Workday companies from workday_scraper.py
for key, config in WORKDAY_COMPANIES.items():
    # Avoid double _wd suffix (e.g., barclays_wd -> barclays_wd, not barclays_wd_wd)
    scraper_key = key if key.endswith("_wd") else f"{key}_wd"
    SCRAPERS[scraper_key] = {
        "script": f"workday_scraper.py --company {key} --search UK --no-desc",
        "type": "workday_api",
        "folder": None,
    }


def find_folder_for_company(company: str, config: dict) -> Path:
    """Find the actual folder path, handling case differences."""
    exact_path = COMPANY_PAGES_DIR / config["folder"]
    if exact_path.exists():
        return exact_path

    # Try case-insensitive match (only if directory exists)
    if not COMPANY_PAGES_DIR.exists():
        return exact_path

    target = config["folder"].lower().replace("_", "").replace("-", "").replace(" ", "")
    for folder in COMPANY_PAGES_DIR.iterdir():
        if folder.is_dir():
            normalized = folder.name.lower().replace("_", "").replace("-", "").replace(" ", "")
            if normalized == target:
                return folder

    return exact_path  # Return original even if not found


def detect_new_folders() -> list[str]:
    """Detect folders in Company_Pages that don't have scrapers configured."""
    if not COMPANY_PAGES_DIR.exists():
        return []

    # Get all configured folder names (normalized)
    configured = set()
    for config in SCRAPERS.values():
        if config["folder"]:  # Skip None folders (API-only scrapers)
            normalized = config["folder"].lower().replace("_", "").replace("-", "").replace(" ", "")
            configured.add(normalized)

    # Find folders without scrapers
    new_folders = []
    for folder in COMPANY_PAGES_DIR.iterdir():
        if folder.is_dir():
            normalized = folder.name.lower().replace("_", "").replace("-", "").replace(" ", "")
            if normalized not in configured:
                new_folders.append(folder.name)

    return new_folders


def calculate_folder_hash(folder: Path) -> str:
    """Calculate combined hash of all HTML/TXT files in folder."""
    if not folder.exists():
        return ""

    files = sorted(list(folder.glob("*.html")) + list(folder.glob("*.txt")))
    if not files:
        return ""

    combined = hashlib.sha256()
    for f in files:
        combined.update(f.name.encode())
        combined.update(f.read_bytes())

    return combined.hexdigest()[:16]


def load_state() -> dict:
    """Load previous scraper state."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"hashes": {}, "last_run": {}}


def save_state(state: dict):
    """Save scraper state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def check_for_changes(company: str, config: dict, state: dict) -> tuple[bool, str]:
    """Check if folder has changes. Returns (has_changes, reason)."""
    # API scrapers - always considered "changed" (fresh data)
    if config["type"] == "api":
        return True, "API (always fresh)"

    # Workday API scrapers - always run (fresh data from API)
    if config["type"] == "workday_api":
        return True, "Workday API (always fresh)"

    folder = find_folder_for_company(company, config)
    current_hash = calculate_folder_hash(folder)
    previous_hash = state.get("hashes", {}).get(company, "")

    if not current_hash:
        return False, "no HTML files"

    if current_hash != previous_hash:
        return True, "files changed" if previous_hash else "new files"

    last_run = state.get("last_run", {}).get(company, "never")
    return False, f"unchanged (last: {last_run})"


def run_scraper(scraper_name: str) -> tuple[bool, str]:
    """Run a single scraper. Returns (success, output)."""
    import shlex
    # Handle script with arguments (e.g., "generic_scraper.py folder 'Company Name'")
    parts = shlex.split(scraper_name)
    script = parts[0]
    args = parts[1:] if len(parts) > 1 else []

    scraper_path = SCRAPERS_DIR / script
    if not scraper_path.exists():
        return False, f"Scraper not found: {script}"

    try:
        cmd = [sys.executable, str(scraper_path)] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr

    except subprocess.TimeoutExpired:
        return False, "Timeout (5 min)"
    except Exception as e:
        return False, str(e)


def combine_results() -> dict:
    """Combine all output JSON files."""
    all_jobs = []
    companies_processed = []

    for company in SCRAPERS.keys():
        patterns = [f"{company}_full_*.json", f"{company}_london_*.json", f"{company}_all_*.json"]
        files = []
        for pattern in patterns:
            files.extend(OUTPUT_DIR.glob(pattern))
        files = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)

        if files:
            latest_file = files[0]
            print(f"  Reading {latest_file.name}")

            with open(latest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                jobs = data.get('jobs', [])
                all_jobs.extend(jobs)
                companies_processed.append({
                    'company': company.upper(),
                    'file': latest_file.name,
                    'total_jobs': len(jobs),
                    'with_description': sum(1 for j in jobs if j.get('description'))
                })

    combined_output = {
        "generated_at": datetime.now().isoformat(),
        "total_jobs": len(all_jobs),
        "jobs_with_description": sum(1 for j in all_jobs if j.get('description')),
        "companies": companies_processed,
        "jobs": all_jobs
    }

    output_path = OUTPUT_DIR / "all_jobs_combined.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(combined_output, f, indent=2, ensure_ascii=False)

    print(f"\nCombined output saved to {output_path}")
    return combined_output


def main():
    parser = argparse.ArgumentParser(description="Run job scrapers")
    parser.add_argument('--new', '-n', action='store_true',
                        help='Only run scrapers with new/changed files')
    parser.add_argument('--status', '-s', action='store_true',
                        help='Show status of all folders (no scraping)')
    parser.add_argument('--company', '-c', type=str,
                        help='Run specific company only (e.g., barclays, hsbc)')
    args = parser.parse_args()

    print("=" * 70)
    print("MASTER JOB SCRAPER")
    print("=" * 70)

    OUTPUT_DIR.mkdir(exist_ok=True)
    state = load_state()

    # Check for new folders without scrapers
    new_folders = detect_new_folders()
    if new_folders:
        print("\n*** WARNING: New folders detected without scrapers ***")
        for folder in new_folders:
            print(f"  - {folder}")
        print("Add scrapers for these folders to process them.\n")

    # Status check mode
    if args.status:
        print("\nFolder status:")
        for company, config in SCRAPERS.items():
            has_changes, reason = check_for_changes(company, config, state)
            status = "CHANGED" if has_changes else "OK"
            print(f"  {company.upper():12} [{status}] - {reason}")
        return

    # Determine which scrapers to run
    to_run = []

    if args.company:
        # Run specific company
        company = args.company.lower()
        if company not in SCRAPERS:
            print(f"Unknown company: {company}")
            print(f"Available: {', '.join(SCRAPERS.keys())}")
            return
        to_run = [(company, SCRAPERS[company])]
        print(f"\nRunning {company.upper()} only")

    elif args.new:
        # Only run changed/new
        print("\nChecking for changes:")
        for company, config in SCRAPERS.items():
            has_changes, reason = check_for_changes(company, config, state)
            status = "RUN" if has_changes else "SKIP"
            print(f"  {company.upper():10} [{status}] - {reason}")
            if has_changes:
                to_run.append((company, config))

        if not to_run:
            print("\nNo new/changed files. Nothing to run.")
            print("Use without --new to run all scrapers.")
            return

    else:
        # Default: run ALL scrapers
        to_run = list(SCRAPERS.items())
        print(f"\nRunning all {len(to_run)} scrapers...")

    # Run scrapers
    results = {}
    for company, config in to_run:
        print(f"\n{'='*70}")
        print(f"Running {company.upper()} scraper...")
        print("=" * 70)

        success, output = run_scraper(config["script"])
        results[company] = success

        if success:
            print(output)
            # Update state (skip folder hash for API-only scrapers)
            if config["folder"]:
                folder = find_folder_for_company(company, config)
                state.setdefault("hashes", {})[company] = calculate_folder_hash(folder)
            state.setdefault("last_run", {})[company] = datetime.now().strftime("%Y-%m-%d %H:%M")
        else:
            print(f"  ERROR: {output}")

    # Save state
    save_state(state)

    # Combine results
    print("\n" + "=" * 70)
    print("COMBINING RESULTS")
    print("=" * 70)
    combined = combine_results()

    # Summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    print(f"\nScrapers executed: {len(results)}")
    for company, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {company.upper()}: {status}")

    print(f"\nJobs collected:")
    for company_info in combined.get('companies', []):
        print(f"  {company_info['company']}: {company_info['total_jobs']} jobs "
              f"({company_info['with_description']} with descriptions)")

    print(f"\nTotal: {combined['total_jobs']} jobs, "
          f"{combined['jobs_with_description']} with descriptions")

    # Report companies with 0 jobs that may need attention
    zero_job_companies = [c['company'] for c in combined.get('companies', []) if c['total_jobs'] == 0]
    if zero_job_companies:
        print("\n" + "=" * 70)
        print("ATTENTION: Companies with 0 jobs found")
        print("=" * 70)
        for company in zero_job_companies:
            print(f"  - {company}")
        print("\nPossible causes:")
        print("  1. Company has no current openings (check their careers page)")
        print("  2. Site uses JavaScript rendering - save page after it fully loads")
        print("  3. HTML structure changed - scraper may need updating")
        print("\nTo investigate, run: python scrapers/generic_scraper.py <folder>")


if __name__ == "__main__":
    main()
