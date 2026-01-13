#!/usr/bin/env python3
"""
Google Workday Job Scraper
Discovers Workday companies from Google search results and generates scraper configs.

Usage:
    python google_workday_scraper.py                    # Parse local HTML files
    python google_workday_scraper.py --search           # Generate search URLs
    python google_workday_scraper.py --discover         # Auto-discover career paths
    python google_workday_scraper.py --output config    # Output config for workday_scraper.py
"""

import os
import re
import json
import argparse
import requests
import time
from datetime import datetime
from urllib.parse import unquote, quote_plus
from pathlib import Path
from bs4 import BeautifulSoup

# Directory containing downloaded Google search HTML files
SEARCH_DIR = Path(__file__).parent / "Google_workday_scrapper"
OUTPUT_DIR = Path(__file__).parent / "output"

# Request headers to mimic browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

# Workday URL patterns
WD_PATTERNS = [
    r'https?://([^.]+)\.wd(\d+)\.myworkdayjobs\.com[^\s"\'<>]*',
]

# Google search queries for finding Workday career sites with London/UK jobs
SEARCH_QUERIES = [
    # Target different Workday instances
    'site:wd1.myworkdayjobs.com London',
    'site:wd2.myworkdayjobs.com London',
    'site:wd3.myworkdayjobs.com London',
    'site:wd5.myworkdayjobs.com London',
    'site:wd12.myworkdayjobs.com London',
    # Broader searches
    'site:myworkdayjobs.com London UK',
    'site:myworkdayjobs.com "United Kingdom"',
    # Role-specific searches
    'site:myworkdayjobs.com London engineer',
    'site:myworkdayjobs.com London software developer',
    'site:myworkdayjobs.com London data scientist',
    'site:myworkdayjobs.com London finance',
    'site:myworkdayjobs.com London analyst',
    'site:myworkdayjobs.com London product manager',
]


def extract_workday_urls_from_html(html_content):
    """Extract all Workday URLs from HTML content."""
    soup = BeautifulSoup(html_content, 'html.parser')
    results = []
    seen_urls = set()

    # Find all anchor tags
    for link in soup.find_all('a'):
        href = link.get('href', '')

        # Extract actual URL from Google redirect
        if '/url?q=' in href:
            actual_url = unquote(href.split('/url?q=')[1].split('&')[0])
        else:
            actual_url = href

        # Check if it's a Workday URL
        for pattern in WD_PATTERNS:
            match = re.search(pattern, actual_url)
            if match:
                company = match.group(1)
                wd_version = match.group(2)

                # Clean URL - get base career page
                clean_url = actual_url.split('?')[0]

                # Skip duplicates
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                # Get link text for context
                text = link.get_text(strip=True)[:200]

                results.append({
                    'company': company,
                    'wd_version': f'wd{wd_version}',
                    'url': actual_url,
                    'clean_url': clean_url,
                    'text': text
                })

    return results


def parse_local_html_files(search_dir=SEARCH_DIR):
    """Parse all HTML files in the search directory."""
    all_results = []
    companies = {}

    if not search_dir.exists():
        print(f"Directory not found: {search_dir}")
        return all_results, companies

    # Support both .html and .mhtml files
    html_files = list(search_dir.glob("*.html")) + list(search_dir.glob("*.mhtml"))
    print(f"Found {len(html_files)} HTML/MHTML files to parse\n")

    for html_file in html_files:
        print(f"Parsing: {html_file.name}")
        try:
            with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()

            results = extract_workday_urls_from_html(html_content)
            all_results.extend(results)

            # Track unique companies
            for r in results:
                company = r['company']
                if company not in companies:
                    companies[company] = {
                        'name': company,
                        'wd_version': r['wd_version'],
                        'base_url': f"https://{company}.{r['wd_version']}.myworkdayjobs.com",
                        'job_urls': [],
                        'career_paths': set()
                    }
                companies[company]['job_urls'].append(r['url'])

                # Extract career path from URL
                path_match = re.search(r'myworkdayjobs\.com/(?:en-US/)?([^/?\s]+)', r['url'])
                if path_match:
                    path = path_match.group(1)
                    if path not in ['en-US', 'job', 'wday']:
                        companies[company]['career_paths'].add(path)

            print(f"  Found {len(results)} Workday URLs")

        except Exception as e:
            print(f"  Error parsing file: {e}")

    # Convert sets to lists for JSON serialization
    for company in companies:
        companies[company]['career_paths'] = list(companies[company]['career_paths'])

    return all_results, companies


def generate_search_urls():
    """Generate Google search URLs for finding Workday career sites."""
    print("Google Search URLs for finding Workday career sites with London/UK jobs:\n")
    print("Instructions:")
    print("  1. Open each URL in your browser")
    print("  2. Save the page as HTML (Ctrl+S, choose 'Webpage, Complete')")
    print("  3. Save files to: Google_workday_scrapper/")
    print("  4. Re-run this script to parse results\n")
    print("="*60 + "\n")

    urls = []
    for query in SEARCH_QUERIES:
        encoded = quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}&num=100"
        urls.append({'query': query, 'url': url})
        print(f"Query: {query}")
        print(f"  {url}\n")

    return urls


def discover_career_path(company, wd_version, timeout=10):
    """Try to discover the career site path by fetching the base URL."""
    base_domain = f"{company}.{wd_version}.myworkdayjobs.com"
    base_url = f"https://{base_domain}"

    print(f"  Discovering career path for {company}...", end=" ")

    try:
        # First, try to get the base page and follow redirects
        response = requests.get(base_url, headers=HEADERS, timeout=timeout, allow_redirects=True)

        if response.status_code == 200:
            # Check where we landed after redirects
            final_url = response.url

            # Extract career path from final URL
            path_match = re.search(r'myworkdayjobs\.com/(?:en-US/)?([^/?\s]+)', final_url)
            if path_match:
                career_path = path_match.group(1)
                if career_path not in ['en-US', 'wday']:
                    print(f"Found: {career_path}")
                    return career_path

            # Try to find career links in the page
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for common career page patterns
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if '/jobs' in href or '/careers' in href or 'External' in href:
                    path_match = re.search(r'/([^/?\s]+)(?:/jobs)?$', href)
                    if path_match:
                        career_path = path_match.group(1)
                        print(f"Found: {career_path}")
                        return career_path

        print("Not found (using default)")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def test_workday_api(company, wd_version, career_path, timeout=10):
    """Test if the Workday API endpoint works."""
    api_url = f"https://{company}.{wd_version}.myworkdayjobs.com/wday/cxs/{company}/{career_path}/jobs"

    payload = {
        "appliedFacets": {},
        "limit": 5,
        "offset": 0,
        "searchText": ""
    }

    headers = {
        **HEADERS,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            total = data.get('total', 0)
            return True, total
        return False, 0
    except:
        return False, 0


def discover_and_validate(companies):
    """Discover and validate career paths for all companies."""
    print("\n" + "="*60)
    print("DISCOVERING CAREER PATHS")
    print("="*60 + "\n")

    validated = {}

    for company, data in companies.items():
        wd_version = data['wd_version']

        # Try known paths first
        known_paths = list(data.get('career_paths', []))

        # Add common patterns to try
        common_paths = [
            f"{company.title()}ExternalCareerSite",
            f"{company}ExternalCareerSite",
            "External",
            "ExternalCareerSite",
            "Careers",
            "careers",
            f"{company}_Careers",
            f"{company.title()}_Careers",
            "global",
            "jobs",
        ]

        paths_to_try = known_paths + [p for p in common_paths if p not in known_paths]

        found_path = None
        job_count = 0

        for path in paths_to_try[:10]:  # Limit attempts
            success, count = test_workday_api(company, wd_version, path)
            if success:
                found_path = path
                job_count = count
                print(f"  {company}: API works at /{path} ({count} jobs)")
                break

        if not found_path:
            # Try to discover from website
            discovered = discover_career_path(company, wd_version)
            if discovered:
                success, count = test_workday_api(company, wd_version, discovered)
                if success:
                    found_path = discovered
                    job_count = count

        if found_path:
            validated[company] = {
                'name': company.replace('_', ' ').title(),
                'wd_version': wd_version,
                'career_path': found_path,
                'api_url': f"https://{company}.{wd_version}.myworkdayjobs.com/wday/cxs/{company}/{found_path}/jobs",
                'careers_url': f"https://{company}.{wd_version}.myworkdayjobs.com/en-US/{found_path}",
                'job_count': job_count,
                'verified': True
            }
        else:
            print(f"  {company}: Could not validate API endpoint")
            validated[company] = {
                'name': company.replace('_', ' ').title(),
                'wd_version': wd_version,
                'career_path': None,
                'verified': False
            }

        time.sleep(0.5)  # Be nice to servers

    return validated


def generate_scraper_config(validated_companies):
    """Generate configuration for workday_scraper.py"""
    print("\n" + "="*60)
    print("WORKDAY SCRAPER CONFIGURATION")
    print("="*60)
    print("\nAdd these to WORKDAY_COMPANIES in scrapers/workday_scraper.py:\n")

    config_lines = []

    for company, data in sorted(validated_companies.items()):
        if not data.get('verified'):
            continue

        name = data['name']
        api_url = data['api_url']
        careers_url = data['careers_url']

        config = f'''    "{company}": {{
        "name": "{name}",
        "api_url": "{api_url}",
        "careers_url": "{careers_url}",
        "location_filter": [],  # Add UK location filter if needed
    }},'''

        config_lines.append(config)
        print(config)

    return config_lines


def save_results(companies, validated=None, output_file=None):
    """Save discovered companies to JSON."""
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = OUTPUT_DIR / f"google_workday_companies_{timestamp}.json"

    OUTPUT_DIR.mkdir(exist_ok=True)

    output_data = {
        'scraped_at': datetime.now().isoformat(),
        'source': 'google_search_results',
        'total_companies': len(companies),
        'companies': []
    }

    for company, data in companies.items():
        company_data = {
            'name': company,
            'wd_version': data['wd_version'],
            'base_url': data['base_url'],
            'found_urls': data.get('job_urls', [])[:5],  # Limit URLs
        }

        if validated and company in validated:
            company_data.update(validated[company])

        output_data['companies'].append(company_data)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved results to: {output_file}")
    return output_file


def print_summary(companies):
    """Print a summary of discovered companies."""
    print("\n" + "="*60)
    print("DISCOVERED WORKDAY COMPANIES")
    print("="*60)

    # Group by Workday version
    by_version = {}
    for company, data in companies.items():
        version = data['wd_version']
        if version not in by_version:
            by_version[version] = []
        by_version[version].append(company)

    for version in sorted(by_version.keys()):
        print(f"\n{version.upper()}:")
        for company in sorted(by_version[version]):
            data = companies[company]
            paths = ', '.join(data.get('career_paths', [])) or '(unknown)'
            print(f"  - {company}")
            print(f"    Base: {data['base_url']}")
            print(f"    Paths: {paths}")

    print(f"\nTotal unique companies: {len(companies)}")


def main():
    parser = argparse.ArgumentParser(description='Discover Workday companies from Google search results')
    parser.add_argument('--search', action='store_true', help='Generate Google search URLs')
    parser.add_argument('--discover', action='store_true', help='Auto-discover and validate career paths')
    parser.add_argument('--dir', type=str, help='Directory containing HTML files')
    parser.add_argument('--output', choices=['json', 'config', 'both'], default='both',
                       help='Output format: json, config, or both')
    args = parser.parse_args()

    if args.search:
        generate_search_urls()
        return

    # Parse local HTML files
    search_dir = Path(args.dir) if args.dir else SEARCH_DIR
    print(f"Searching for HTML files in: {search_dir}\n")

    all_results, companies = parse_local_html_files(search_dir)

    if not companies:
        print("\nNo Workday companies found in HTML files.")
        print("\nTo find companies with London jobs:")
        print("  1. Run: python google_workday_scraper.py --search")
        print("  2. Open those URLs in browser and save as HTML")
        print("  3. Save files to: Google_workday_scrapper/")
        print("  4. Re-run this script")
        return

    print_summary(companies)

    validated = None
    if args.discover:
        validated = discover_and_validate(companies)

        # Generate scraper config
        if args.output in ['config', 'both']:
            generate_scraper_config(validated)

    # Save results
    if args.output in ['json', 'both']:
        save_results(companies, validated)


if __name__ == "__main__":
    main()
