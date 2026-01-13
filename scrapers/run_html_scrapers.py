#!/usr/bin/env python3
"""
Run HTML-based Job Scrapers

Runs all scrapers that require saved HTML pages from Company_Pages/.
These are companies without direct API access.

Usage:
    python scrapers/run_html_scrapers.py              # Run all
    python scrapers/run_html_scrapers.py --list       # List available
    python scrapers/run_html_scrapers.py --company stripe  # Run specific
"""

import subprocess
import sys
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
SCRAPERS_DIR = Path(__file__).parent
COMPANY_PAGES_DIR = BASE_DIR / "Company_Pages"

# Company-specific scrapers (have their own scripts)
SPECIFIC_SCRAPERS = {
    "barclays": "barclays_scraper.py",
    "stripe": "stripe_scraper.py",
    "clearbank": "clearbank_scraper.py",
    "hsbc": "hsbc_scraper.py",
    "savanta": "savanta_scraper.py",
    "jlr": "jlr_scraper.py",
}

# Generic scraper companies (use generic_scraper.py with folder name)
GENERIC_COMPANIES = {
    "starling_bank": ("Starling Bank", "Starling Bank"),
    "wise": ("Wise", "Wise"),
    "revolut": ("Revolut", "Revolut"),
    "gocardless": ("GoCardless", "GoCardless"),
    "oaknorth": ("oaknorth", "OakNorth"),
    "rapyd": ("Rapyd", "Rapyd"),
    "thoughtmachine": ("thoughtmachine", "ThoughtMachine"),
    "marqeta": ("Marqeta", "Marqeta"),
    "adyen": ("Adyen", "Adyen"),
    "affirm": ("Affirm", "Affirm"),
    "coinbase": ("Coinbase", "Coinbase"),
    "plaid": ("plaid", "Plaid"),
    "robinhood": ("Robinhood", "Robinhood"),
    "square": ("Square", "Square"),
    "microsoft": ("microsoft", "Microsoft"),
    "amazon": ("amazon", "Amazon"),
    "apple": ("apple", "Apple"),
    "google": ("google", "Google"),
    "salesforce": ("salesforce", "Salesforce"),
    "oracle": ("oracle", "Oracle"),
    "ibm": ("IBM", "IBM"),
    "cisco": ("cisco", "Cisco"),
    "bmwgroup": ("bmwgroup", "BMW Group"),
    "mercedes": ("Mercedes-Benz", "Mercedes-Benz"),
    "waymo": ("withwaymo", "Waymo"),
}


def run_scraper(script: str, args: list = None):
    """Run a scraper script."""
    cmd = [sys.executable, str(SCRAPERS_DIR / script)]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=120)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after 120s")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def run_generic_scraper(folder: str, company_name: str):
    """Run the generic scraper for a company."""
    return run_scraper("generic_scraper.py", [folder, company_name])


def folder_exists(folder_name: str) -> bool:
    """Check if company folder exists in Company_Pages."""
    folder = COMPANY_PAGES_DIR / folder_name
    if not folder.exists():
        return False
    # Check if it has any HTML files
    return any(folder.glob("*.html")) or any(folder.glob("*.htm"))


def list_companies():
    """List all available companies."""
    print("\n=== Company-Specific Scrapers ===")
    for key, script in SPECIFIC_SCRAPERS.items():
        status = "ready" if (SCRAPERS_DIR / script).exists() else "missing"
        print(f"  {key}: {script} [{status}]")

    print("\n=== Generic Scraper Companies ===")
    for key, (folder, name) in GENERIC_COMPANIES.items():
        status = "has HTML" if folder_exists(folder) else "no HTML"
        print(f"  {key}: {name} (folder: {folder}) [{status}]")


def main():
    parser = argparse.ArgumentParser(description="Run HTML-based job scrapers")
    parser.add_argument("--list", action="store_true", help="List available companies")
    parser.add_argument("--company", help="Run specific company only")
    parser.add_argument("--specific-only", action="store_true", help="Run only company-specific scrapers")
    parser.add_argument("--generic-only", action="store_true", help="Run only generic scrapers")
    args = parser.parse_args()

    if args.list:
        list_companies()
        return

    print("=" * 60)
    print("HTML-BASED JOB SCRAPERS")
    print("=" * 60)

    results = {"success": [], "failed": [], "skipped": []}

    # Run specific company if requested
    if args.company:
        company = args.company.lower().replace(" ", "_").replace("-", "_")

        if company in SPECIFIC_SCRAPERS:
            print(f"\nRunning {company} (specific scraper)...")
            if run_scraper(SPECIFIC_SCRAPERS[company]):
                results["success"].append(company)
            else:
                results["failed"].append(company)
        elif company in GENERIC_COMPANIES:
            folder, name = GENERIC_COMPANIES[company]
            if folder_exists(folder):
                print(f"\nRunning {name} (generic scraper)...")
                if run_generic_scraper(folder, name):
                    results["success"].append(company)
                else:
                    results["failed"].append(company)
            else:
                print(f"\n{company}: No HTML files in Company_Pages/{folder}/")
                results["skipped"].append(company)
        else:
            print(f"\nUnknown company: {company}")
            print("Use --list to see available companies")

    else:
        # Run all scrapers

        # Company-specific scrapers
        if not args.generic_only:
            print("\n--- Company-Specific Scrapers ---")
            for key, script in SPECIFIC_SCRAPERS.items():
                print(f"\n[{key}] Running {script}...")
                if run_scraper(script):
                    results["success"].append(key)
                else:
                    results["failed"].append(key)

        # Generic scrapers
        if not args.specific_only:
            print("\n--- Generic Scrapers ---")
            for key, (folder, name) in GENERIC_COMPANIES.items():
                if folder_exists(folder):
                    print(f"\n[{key}] Running generic scraper for {name}...")
                    if run_generic_scraper(folder, name):
                        results["success"].append(key)
                    else:
                        results["failed"].append(key)
                else:
                    results["skipped"].append(key)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Success: {len(results['success'])} - {', '.join(results['success']) or 'none'}")
    print(f"Failed:  {len(results['failed'])} - {', '.join(results['failed']) or 'none'}")
    print(f"Skipped: {len(results['skipped'])} (no HTML files)")


if __name__ == "__main__":
    main()
