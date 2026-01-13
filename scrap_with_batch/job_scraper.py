#!/usr/bin/env python3
"""
Job scraper script to extract job listings and descriptions from career portals.
Saves results to JSON format with job title, description, URL, and date.
"""

import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class JobScraper:
    def __init__(self, output_file: str = None):
        """
        Initialize the job scraper.
        
        Args:
            output_file: Path to save JSON output (default: jobs_YYYYMMDD.json)
        """
        if output_file is None:
            date_str = datetime.now().strftime("%Y%m%d")
            output_file = f"jobs_{date_str}.json"
        
        self.output_file = output_file
        self.jobs = []
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_page(self, url: str) -> BeautifulSoup:
        """Fetch and parse a webpage."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _is_valid_job_title(self, title: str) -> bool:
        """Check if title looks like a real job title."""
        # Explicitly reject footer/navigation/social links
        reject_patterns = [
            'privacy', 'cookie', 'sitemap', 'linkedin', 'instagram', 'facebook',
            'twitter', 'youtube', 'our teams', 'students', 'graduates', 'life at',
            'talent network', 'view all', 'accessibility', 'learn more', 'about',
            'inclusion', 'wellbeing', 'benefits', 'explore', 'overview', 'interns',
            'apprenticeships', 'discovery', 'americas', 'stories', 'careers',
            'contact', 'search', 'filter', 'sort', 'helpdesk', 'account',
            'sign in', 'sign up', 'menu', 'skip', 'next', 'prev', 'go',
            'clear all', 'policy', 'terms', 'conditions', 'notice', 'recruitment scams'
        ]
        
        title_lower = title.lower().strip()
        
        # Reject if matches reject patterns
        for pattern in reject_patterns:
            if pattern in title_lower:
                return False
        
        # Job titles usually contain role keywords - MUST have at least one
        job_keywords = [
            'engineer', 'developer', 'manager', 'architect', 'analyst', 'lead',
            'specialist', 'officer', 'consultant', 'designer', 'scientist',
            'administrator', 'coordinator', 'associate', 'senior', 'junior',
            'principal', 'director', 'head of', 'platform', 'sre', 'devops',
            'data', 'ml', 'ai', 'security', 'cloud', 'infrastructure', 'network',
            'sales', 'support', 'engineer', 'ops', 'solutions', 'business',
            'product', 'quality', 'test', 'qa', 'scrum', 'agile', 'tech',
            'ciso', 'cto', 'cfo', 'coo', 'vp ', 'vice president', 'executive',
            'partner', 'advisor', 'fcr', 'talent', 'fund', 'admin', 'agent'
        ]
        
        # Must be reasonably long and contain at least one job keyword
        if len(title) < 8:
            return False
        
        has_job_keyword = any(keyword in title_lower for keyword in job_keywords)
        if not has_job_keyword:
            return False
        
        # Additional checks - reject very short titles (likely navigation)
        # and titles that are just single generic words
        words = title.split()
        if len(words) == 1 and len(title) < 15:
            return False
        
        return True
    
    def _is_valid_job_url(self, url: str) -> bool:
        """Check if URL looks like a job listing link."""
        url_lower = url.lower()
        
        # Reject footer/policy/social links
        reject_patterns = [
            'privacy', 'cookie', 'sitemap', 'policy', 'terms', 'conditions',
            'linkedin.com', 'instagram.com', 'facebook.com', 'twitter.com',
            'youtube.com', 'accessibility', 'contact', 'about',
            '//www.', 'social', 'media'
        ]
        
        for pattern in reject_patterns:
            if pattern in url_lower:
                return False
        
        # Should contain /job or /jobs or similar job-related paths
        job_patterns = ['/job/', '/jobs/', 'jobid', 'job-id', '/opening/', 'vacancy']
        has_job_pattern = any(pattern in url_lower for pattern in job_patterns)
        
        return has_job_pattern
    
    def _normalize_url(self, href: str, base_domain: str = '') -> str:
        """Normalize relative URLs to absolute URLs."""
        if href.startswith('http'):
            return href
        elif href.startswith('/'):
            return base_domain + href if base_domain else href
        else:
            return href
    
    def fetch_job_description(self, job_url: str, company: str, source: str = None) -> str:
        """Fetch full job description from job detail page."""
        try:
            # For eFinancialCareers, use Selenium to load JavaScript content
            if source == 'eFinancialCareers' or 'efinancialcareers' in job_url.lower():
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    from selenium.webdriver.support.ui import WebDriverWait
                    from selenium.webdriver.support import expected_conditions as EC
                    from selenium.webdriver.common.by import By
                    import time

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)

                    # Wait for job description to load
                    try:
                        wait = WebDriverWait(driver, 10)
                        wait.until(EC.presence_of_element_located((By.TAG_NAME, "efc-job-description")))
                    except:
                        time.sleep(3)

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()

                    # Extract job description using the selector provided
                    desc_elem = soup.find('efc-job-description')
                    if desc_elem:
                        return desc_elem.get_text(separator='\n', strip=True)

                    # Fallback: try CSS selector
                    desc_elem = soup.select_one('efc-job-details-page div.col-lg-8 efc-job-description')
                    if desc_elem:
                        return desc_elem.get_text(separator='\n', strip=True)

                    return ''

                except Exception as e:
                    logger.warning(f"Selenium failed for eFinancialCareers {job_url}: {e}")
                    return ''

            # For Wise jobs (wise.jobs), fetch description from job detail page
            if company == 'Wise' and 'wise.jobs' in job_url.lower():
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    import time

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)
                    time.sleep(3)

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()

                    # Wise job descriptions are in attrax-vacancy-details-section
                    desc_elem = soup.find('div', class_='attrax-vacancy-details-section')
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    # Fallback: try job-description class
                    desc_elem = soup.find('div', class_=lambda x: x and 'job-description' in x.lower() if x else False)
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    return ''

                except Exception as e:
                    logger.warning(f"Selenium failed for Wise {job_url}: {e}")
                    return ''

            # For Checkout.com (Workday), use Selenium
            if company == 'Checkout.com' or 'myworkdayjobs.com' in job_url.lower():
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    import time

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)
                    time.sleep(3)

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()

                    # Workday job descriptions are in data-automation-id="jobPostingDescription"
                    desc_elem = soup.find('div', {'data-automation-id': 'jobPostingDescription'})
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    # Fallback: try class containing 'description'
                    desc_elem = soup.find('div', class_=lambda x: x and 'description' in x.lower() if x else False)
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    return ''

                except Exception as e:
                    logger.warning(f"Selenium failed for Checkout.com {job_url}: {e}")
                    return ''

            # For Monzo (Greenhouse), fetch from greenhouse job page
            if company == 'Monzo' or 'greenhouse.io/monzo' in job_url.lower():
                try:
                    soup = self.fetch_page(job_url)
                    if soup:
                        # Greenhouse has #content div with job description
                        desc_elem = soup.find('div', id='content')
                        if desc_elem:
                            return desc_elem.decode_contents().strip()
                    return ''
                except Exception as e:
                    logger.warning(f"Failed to fetch Monzo description {job_url}: {e}")
                    return ''

            # For Starling Bank (Workable), fetch from workable job page
            if company == 'Starling Bank' or 'workable.com' in job_url.lower():
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    import time

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)
                    time.sleep(3)

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()

                    # Workable job descriptions are in data-ui="job-description"
                    desc_elem = soup.find('div', {'data-ui': 'job-description'})
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    # Fallback: try section with class containing description
                    desc_elem = soup.find('section', class_=lambda x: x and 'description' in str(x).lower() if x else False)
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    return ''

                except Exception as e:
                    logger.warning(f"Selenium failed for Starling {job_url}: {e}")
                    return ''

            # For Stripe, use Selenium
            if company == 'Stripe' or 'stripe.com/jobs' in job_url.lower():
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    import time

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)
                    time.sleep(3)

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()

                    # Stripe job descriptions - try to find main content
                    desc_elem = soup.find('div', class_=lambda x: x and 'JobDescription' in str(x) if x else False)
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    # Fallback: find article or main element
                    desc_elem = soup.find('article') or soup.find('main')
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    return ''

                except Exception as e:
                    logger.warning(f"Selenium failed for Stripe {job_url}: {e}")
                    return ''

            # For Revolut, use Selenium (site blocks regular requests)
            if company == 'Revolut' or 'revolut.com/careers' in job_url.lower():
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    import time

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)
                    time.sleep(3)

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()

                    # Revolut job description
                    desc_elem = soup.find('div', class_=lambda x: x and 'job-description' in str(x).lower() if x else False)
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    # Fallback: main content
                    desc_elem = soup.find('main')
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    return ''

                except Exception as e:
                    logger.warning(f"Selenium failed for Revolut {job_url}: {e}")
                    return ''

            # For GoCardless (Greenhouse), fetch from greenhouse job page
            if company == 'GoCardless' or 'greenhouse.io/gocardless' in job_url.lower():
                try:
                    soup = self.fetch_page(job_url)
                    if soup:
                        desc_elem = soup.find('div', id='content')
                        if desc_elem:
                            return desc_elem.decode_contents().strip()
                    return ''
                except Exception as e:
                    logger.warning(f"Failed to fetch GoCardless description {job_url}: {e}")
                    return ''

            # For NatWest, use Selenium (site blocks regular requests with 403)
            if company == 'NatWest':
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    from selenium.webdriver.support.ui import WebDriverWait
                    from selenium.webdriver.support import expected_conditions as EC
                    from selenium.webdriver.common.by import By
                    import time

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)
                    time.sleep(3)

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()

                    # Primary: Look for #job-description div (the actual job description content)
                    desc_elem = soup.find('div', id='job-description')
                    if desc_elem:
                        # Return inner HTML to preserve formatting
                        return desc_elem.decode_contents().strip()

                    # Fallback: Try cms class div that contains job description
                    desc_elem = soup.find('div', class_='cms')
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    # Fallback: Try ats-description
                    desc_elem = soup.find('div', class_='ats-description')
                    if desc_elem:
                        return desc_elem.decode_contents().strip()

                    return ''

                except Exception as e:
                    logger.warning(f"Selenium failed for NatWest {job_url}: {e}")
                    return ''

            # For HSBC, use Selenium to ensure JavaScript content is loaded
            if company == 'HSBC':
                try:
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    from selenium.webdriver.support.ui import WebDriverWait
                    from selenium.webdriver.support import expected_conditions as EC
                    from selenium.webdriver.common.by import By
                    import time
                    
                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                    
                    driver = webdriver.Chrome(options=chrome_options)
                    driver.get(job_url)
                    
                    # Wait briefly for page to load
                    time.sleep(2)
                    
                    # Parse the rendered page
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    driver.quit()
                    
                    # Try meta tags first (most reliable)
                    meta_desc = soup.find('meta', {'name': 'description'})
                    if meta_desc and meta_desc.get('content'):
                        return meta_desc.get('content').strip()
                    
                    og_desc = soup.find('meta', {'property': 'og:description'})
                    if og_desc and og_desc.get('content'):
                        return og_desc.get('content').strip()
                    
                except Exception as e:
                    logger.warning(f"Selenium failed for HSBC {job_url}: {e}, falling back to requests")
            
            # Fallback: use regular requests
            soup = self.fetch_page(job_url)
            if not soup:
                return ''
            # We'll try to capture the inner HTML of the job details area so
            # descriptions are preserved (formatting, lists, paragraphs).
            description_html = ''

            if company == 'Barclays':
                # Prefer the section with id/anchor job overview or class job-description
                desc_elem = soup.find('section', id=lambda v: v and 'anchor-job-overview' in v) or \
                            soup.find('section', class_='job-description') or \
                            soup.find('div', class_='job-details-wrapper')
                if desc_elem:
                    # use decode_contents to get inner HTML without surrounding tag
                    try:
                        description_html = desc_elem.decode_contents()
                    except Exception:
                        description_html = str(desc_elem)

                # fallback to ats-description div
                if not description_html:
                    ats = soup.find('div', class_='ats-description')
                    if ats:
                        description_html = ats.decode_contents() if hasattr(ats, 'decode_contents') else str(ats)

            elif company == 'NatWest':
                desc_elem = soup.find('div', class_='job-description') or \
                            soup.find('section', class_='job-description') or \
                            soup.find('div', {'class': lambda x: x and 'description' in x.lower()})
                if desc_elem:
                    description_html = desc_elem.decode_contents() if hasattr(desc_elem, 'decode_contents') else str(desc_elem)

            elif company == 'HSBC':
                # HSBC job descriptions are in meta tags on the detail page
                # First try meta description tag
                meta_desc = soup.find('meta', {'name': 'description'})
                if meta_desc and meta_desc.get('content'):
                    description_html = meta_desc.get('content').strip()
                
                # Fallback to og:description
                if not description_html:
                    og_desc = soup.find('meta', {'property': 'og:description'})
                    if og_desc and og_desc.get('content'):
                        description_html = og_desc.get('content').strip()
                
                # Final fallback: use the specific CSS selector if meta tags fail
                if not description_html:
                    try:
                        selector = "#pcs-body-container > div:nth-child(2) > div.search-results-main-container > div > div.inline-block.mobile-hide.position-top-container.map-enabled > div > div > div.position-details > div.row > div.col-md-8.position-job-description-column"
                        desc_elem = soup.select_one(selector)
                        if desc_elem:
                            description_html = desc_elem.decode_contents() if hasattr(desc_elem, 'decode_contents') else str(desc_elem)
                    except Exception:
                        pass

            # Generic fallback: look for a job-details-wrapper or any element with ats-description
            if not description_html:
                generic = soup.find('section', class_='job-details-wrapper') or soup.find('div', class_='job-details-wrapper') or soup.find('div', class_='ats-description')
                if generic:
                    description_html = generic.decode_contents() if hasattr(generic, 'decode_contents') else str(generic)

            # Strip leading/trailing whitespace
            if description_html:
                return description_html.strip()

            return ''
        
        except Exception as e:
            logger.warning(f"Error fetching job description from {job_url}: {e}")
            return ''
    
    def extract_jobs_from_natwest(self, url: str) -> List[Dict]:
        """Extract jobs from NatWest careers page with pagination support using Selenium."""
        all_jobs = []
        base_url = 'https://jobs.natwestgroup.com'
        page_num = 1
        max_pages = 20

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)

            while page_num <= max_pages:
                # Build URL with page parameter
                if page_num == 1:
                    current_url = url
                else:
                    # Add page parameter to URL
                    if '?' in url:
                        current_url = f"{url}&page={page_num}"
                    else:
                        current_url = f"{url}?page={page_num}"

                logger.info(f"Scraping NatWest page {page_num}: {current_url}")
                driver.get(current_url)
                time.sleep(3)

                html_content = driver.page_source
                soup = BeautifulSoup(html_content, 'html.parser')

                # Find job listings using a.job class
                # Structure: <a class="job" href="/jobs/17091608-engineering-manager">
                #   <div class="job__details">
                #     <p class="job__title">Engineering Manager</p>
                #     <p class="job__location">London, United Kingdom</p>
                #   </div>
                #   <div class="job__meta">
                #     <p class="job__reference">R-00269415</p>
                #     <p class="job__posted-date">Posted 9 days ago</p>
                #   </div>
                # </a>
                job_links = soup.find_all('a', class_='job')

                if not job_links:
                    logger.info(f"No jobs found on page {page_num}, stopping pagination")
                    break

                jobs = []
                for link in job_links:
                    try:
                        href = link.get('href', '').strip()
                        if not href:
                            continue

                        # Get job title from p.job__title
                        title_elem = link.find('p', class_='job__title')
                        job_title = title_elem.get_text(strip=True) if title_elem else ''

                        if not job_title or len(job_title) < 5:
                            continue

                        job_url = href if href.startswith('http') else base_url + href

                        # Get location from p.job__location
                        location = ''
                        location_elem = link.find('p', class_='job__location')
                        if location_elem:
                            location = location_elem.get_text(strip=True)

                        # Get reference number from p.job__reference
                        reference = ''
                        ref_elem = link.find('p', class_='job__reference')
                        if ref_elem:
                            reference = ref_elem.get_text(strip=True)

                        # Get posted date from p.job__posted-date
                        posted_date = ''
                        date_elem = link.find('p', class_='job__posted-date')
                        if date_elem:
                            posted_date = date_elem.get_text(strip=True)

                        # Avoid duplicates
                        if any(j['url'] == job_url for j in all_jobs):
                            continue

                        jobs.append({
                            'title': job_title,
                            'url': job_url,
                            'location': location,
                            'reference': reference,
                            'posted_date': posted_date,
                            'description': '',
                            'company': 'NatWest',
                            'date_scraped': datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing NatWest job element: {e}")

                all_jobs.extend(jobs)
                logger.info(f"Found {len(jobs)} jobs on page {page_num}")

                # Check if there's a next page link
                pagination = soup.find('div', class_='pagination')
                if pagination:
                    next_link = pagination.find('a', class_='next_page')
                    if not next_link:
                        logger.info("No next page link found, stopping pagination")
                        break
                else:
                    # No pagination div means single page
                    break

                page_num += 1

            driver.quit()

        except Exception as e:
            logger.error(f"Error extracting NatWest jobs: {e}")

        logger.info(f"Total NatWest jobs found: {len(all_jobs)}")
        return all_jobs
    
    def extract_jobs_from_hsbc(self, url: str) -> List[Dict]:
        """Extract jobs from HSBC careers page using job-card-container elements."""
        import re
        all_jobs = []
        current_url = url
        page_num = 1
        max_pages = 10
        
        while page_num <= max_pages:
            logger.info(f"Scraping HSBC page {page_num}")
            jobs = []
            
            # Use Selenium for HSBC since it requires JavaScript rendering
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                from selenium.webdriver.common.by import By
                import time
                
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                
                driver = webdriver.Chrome(options=chrome_options)
                driver.get(current_url)
                
                # Wait for job cards to load
                logger.info("Waiting for job cards to load...")
                wait = WebDriverWait(driver, 15)
                try:
                    wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, "job-card-container")))
                except:
                    logger.info("Timeout waiting for job cards, continuing anyway")
                    time.sleep(3)
                
                html_content = driver.page_source
                driver.quit()
            except Exception as e:
                logger.warning(f"Selenium failed, falling back to requests: {e}")
                response = self.session.get(current_url, timeout=10)
                if response.status_code != 200:
                    break
                html_content = response.text
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract positions data from the page JSON first
            positions_by_name = {}
            try:
                match = re.search(r'"positions":\s*\[(.*?)\](?=,\s*"debug")', html_content, re.DOTALL)
                if match:
                    positions_str = '[' + match.group(1) + ']'
                    positions = json.loads(positions_str)
                    for pos in positions:
                        name = pos.get('name', '')
                        url_str = pos.get('canonicalPositionUrl', '')
                        if name and url_str:
                            positions_by_name[name] = url_str
            except Exception as e:
                logger.debug(f"Could not extract positions data: {e}")
            
            # Find job cards using the job-card-container class structure
            card_containers = soup.find_all('div', class_=lambda x: x and 'job-card-container' in x)
            if not card_containers:
                logger.info("No job-card-container elements found")
                break
            
            for container in card_containers:
                try:
                    # Extract title from h3.job-card-title
                    title_elem = container.find('h3', class_='job-card-title')
                    if not title_elem:
                        continue
                    job_title = title_elem.get_text(strip=True)
                    
                    if not self._is_valid_job_title(job_title):
                        continue
                    
                    # Try to get URL from positions JSON first (most reliable)
                    job_url = positions_by_name.get(job_title, '')
                    
                    # Fallback: try to find URL from container
                    if not job_url:
                        a = container.find('a', href=True)
                        if a and a.get('href'):
                            job_url = a.get('href').strip()
                        else:
                            # Try data attributes that might contain URL
                            for attr in ('data-href', 'data-url', 'data-apply-url', 'data-redirect'):
                                if container.get(attr):
                                    job_url = container.get(attr).strip()
                                    break
                    
                    if job_url:
                        job_url = self._normalize_url(job_url, 'https://portal.careers.hsbc.com')
                    
                    # Extract location from field-label elements
                    location = ''
                    fld_labels = container.find_all('p', class_='field-label')
                    for p in fld_labels:
                        txt = p.get_text(strip=True)
                        # Heuristic: locations have comma or country names
                        if ',' in txt or any(word in txt.lower() for word in ('united', 'vietnam', 'india', 'china', 'egypt', 'uk')):
                            location = txt
                            break
                    
                    jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location,
                        'description': '',
                        'company': 'HSBC',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.warning(f"Error parsing HSBC job container: {e}")
            
            all_jobs.extend(jobs)
            logger.info(f"Found {len(jobs)} jobs on page {page_num}")
            
            # Check for 'Show more opportunities' button
            show_more_btn = soup.find('button', class_=lambda x: x and 'show-more-positions' in x)
            if show_more_btn:
                logger.info("HSBC page has 'Show more opportunities' button - additional jobs may require JavaScript to load")
                # Try to find a next page URL or data endpoint
                next_url = self._find_next_page_url(soup, current_url)
                if next_url and next_url != current_url:
                    current_url = next_url
                    page_num += 1
                    continue
                else:
                    logger.info("No automatic pagination discovered - may need JavaScript to load more jobs")
                    break
            
            # Standard pagination lookup
            next_url = self._find_next_page_url(soup, current_url)
            if not next_url or next_url == current_url:
                break
            
            current_url = next_url
            page_num += 1
        
        return all_jobs
    
    def extract_jobs_from_barclays(self, url: str) -> List[Dict]:
        """Extract jobs from Barclays careers page with pagination support."""
        all_jobs = []
        current_url = url
        page_num = 1
        max_pages = 10  # Limit to prevent infinite loops
        
        while page_num <= max_pages:
            logger.info(f"Scraping Barclays page {page_num}: {current_url}")
            jobs = []
            soup = self.fetch_page(current_url)
            if not soup:
                break
            
            # Look for job result containers - Barclays has specific structure
            # Jobs are typically in divs or list items with specific patterns
            job_containers = soup.find_all(['div', 'li'], class_=lambda x: x and ('job' in x.lower() or 'result' in x.lower()))
            
            # If no containers found, look for links that match job patterns
            if not job_containers:
                job_links = soup.find_all('a', href=lambda x: x and '/job/' in str(x).lower())
                
                for link in job_links:
                    try:
                        href = link.get('href', '').strip()
                        job_title = link.get_text(strip=True)
                        
                        # Validate both title and URL
                        if not self._is_valid_job_title(job_title):
                            continue
                        if not self._is_valid_job_url(href):
                            continue
                        
                        job_url = self._normalize_url(href, 'https://search.jobs.barclays')
                        
                        jobs.append({
                            'title': job_title,
                            'url': job_url,
                            'location': '',
                            'description': '',
                            'company': 'Barclays',
                            'date_scraped': datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing Barclays job: {e}")
            else:
                # Parse job containers
                for container in job_containers:
                    try:
                        link = container.find('a', href=True)
                        if not link:
                            continue
                        
                        job_title = link.get_text(strip=True)
                        if not self._is_valid_job_title(job_title):
                            continue
                        
                        href = link.get('href', '').strip()
                        if not self._is_valid_job_url(href):
                            continue
                        
                        job_url = self._normalize_url(href, 'https://search.jobs.barclays')
                        
                        # Extract location
                        location = ''
                        location_elem = container.find(string=lambda x: x and ('United Kingdom' in str(x) or 'England' in str(x)))
                        if location_elem:
                            location = str(location_elem).strip()
                        
                        jobs.append({
                            'title': job_title,
                            'url': job_url,
                            'location': location,
                            'description': '',
                            'company': 'Barclays',
                            'date_scraped': datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing Barclays container: {e}")
            
            all_jobs.extend(jobs)
            logger.info(f"Found {len(jobs)} jobs on page {page_num}")
            
            # Look for next page link
            next_url = self._find_next_page_url(soup, current_url)
            if not next_url:
                logger.info("No more pages found")
                break
            
            current_url = next_url
            page_num += 1
        
        return all_jobs
    
    def _find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> str:
        """Find the next page URL from pagination controls."""
        try:
            # Look for next button or page link
            next_link = soup.find('a', string=lambda x: x and 'next' in x.lower())
            if next_link and next_link.get('href'):
                href = next_link.get('href')
                if href.startswith('http'):
                    return href
                elif href.startswith('/'):
                    base = '/'.join(current_url.split('/')[:3])
                    return base + href
                else:
                    return current_url.rstrip('/') + '/' + href
            
            # Look for page number pattern in URL and increment
            import re
            # Try to find page parameter (e.g., ?page=2 or /page/2)
            page_match = re.search(r'[?&]page=(\d+)', current_url)
            if page_match:
                current_page = int(page_match.group(1))
                next_page_url = re.sub(r'([?&]page=)\d+', f'\\g<1>{current_page + 1}', current_url)
                return next_page_url
            
            # Check for pagination button form (with Go button)
            go_button = soup.find('button', class_='pagination-page-jump')
            if go_button:
                # Find the input field near the button
                parent = go_button.parent
                if parent:
                    page_input = parent.find('input', type='text')
                    if page_input:
                        # Try to extract current page and increment
                        try:
                            current_page = int(page_input.get('value', '1'))
                            next_page_url = re.sub(r'([?&]page=)\d+', f'\\g<1>{current_page + 1}', current_url)
                            if next_page_url != current_url:
                                return next_page_url
                        except:
                            pass
            
            return ''
        
        except Exception as e:
            logger.warning(f"Error finding next page URL: {e}")
            return ''
    
    def extract_jobs_from_klarna(self, url: str) -> List[Dict]:
        """Extract jobs from Klarna via Deel job board. Uses Selenium for JS rendering."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            import time
            
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            
            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading Klarna page with Selenium...")
            driver.get(url)
            
            # Wait for job listings to load
            try:
                wait = WebDriverWait(driver, 15)
                wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "a")))
            except:
                logger.info("Timeout waiting for jobs, continuing anyway")
                time.sleep(3)
            
            html_content = driver.page_source
            driver.quit()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find job links using the Deel/Klarna specific selector
            # Look for links with job-details pattern
            job_links = soup.find_all('a', class_='MuiLink-root', href=lambda x: x and '/job-details/' in x.lower())
            
            if not job_links:
                logger.info("No job links found on Klarna page")
                return all_jobs
            
            for link in job_links:
                try:
                    # Extract title from the h4 element inside
                    title_elem = link.find('p', class_=lambda x: x and 'MuiTypography-h4' in str(x))
                    if not title_elem:
                        continue
                    
                    job_title = title_elem.get_text(strip=True)
                    if not self._is_valid_job_title(job_title):
                        continue
                    
                    job_url = link.get('href', '').strip()
                    if not job_url.startswith('http'):
                        job_url = 'https://jobs.deel.com' + job_url if job_url.startswith('/') else 'https://jobs.deel.com/' + job_url
                    
                    if not self._is_valid_job_url(job_url):
                        continue
                    
                    # Extract location and salary from the secondary text
                    location = ''
                    location_elem = link.find('p', class_=lambda x: x and 'MuiListItemText-secondary' in str(x))
                    if location_elem:
                        text = location_elem.get_text(strip=True)
                        # Parse location (usually after first separator)
                        parts = text.split('·')
                        if len(parts) >= 2:
                            location = parts[1].strip()
                    
                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location,
                        'description': '',
                        'company': 'Klarna',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing Klarna job: {e}")
            
            logger.info(f"Found {len(all_jobs)} Klarna jobs")
        
        except Exception as e:
            logger.error(f"Error extracting Klarna jobs: {e}")
            # Fallback to regular scraper
            return self._fallback_extract_klarna(url)
        
        return all_jobs
    
    def _fallback_extract_klarna(self, url: str) -> List[Dict]:
        """Fallback method for Klarna if Selenium fails."""
        soup = self.fetch_page(url)
        if not soup:
            return []
        
        all_jobs = []
        job_links = soup.find_all('a', href=lambda x: x and '/job/' in x.lower() if x else False)
        
        for link in job_links:
            try:
                job_title = link.get_text(strip=True)
                if not self._is_valid_job_title(job_title):
                    continue
                
                job_url = link.get('href', '').strip()
                if not job_url.startswith('http'):
                    job_url = 'https://jobs.deel.com' + job_url if job_url.startswith('/') else 'https://jobs.deel.com/' + job_url
                
                if not self._is_valid_job_url(job_url):
                    continue
                
                all_jobs.append({
                    'title': job_title,
                    'url': job_url,
                    'location': '',
                    'description': '',
                    'company': 'Klarna',
                    'date_scraped': datetime.now().isoformat()
                })
            except Exception as e:
                logger.debug(f"Error parsing Klarna job: {e}")
        
        return all_jobs
    
    def extract_jobs_from_wise(self, url: str) -> List[Dict]:
        """Extract jobs from Wise careers portal using Selenium with pagination."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            import time
            
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            
            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading Wise page with Selenium...")
            driver.get(url)
            
            # Wait for job listings to load
            try:
                wait = WebDriverWait(driver, 15)
                wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, "attrax-vacancy-tile")))
            except:
                logger.info("Timeout waiting for jobs, continuing anyway")
                time.sleep(5)
            
            # Get all jobs across pages by using pagination
            page_num = 1
            max_pages = 15
            
            while page_num <= max_pages:
                # Scroll to load jobs on current page
                for _ in range(3):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                
                html_content = driver.page_source
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Find job tiles using the Wise/Attrax specific class
                job_tiles = soup.find_all('div', class_='attrax-vacancy-tile')
                
                if not job_tiles and page_num == 1:
                    logger.info("No job tiles found on Wise page")
                    break
                
                for tile in job_tiles:
                    try:
                        # Find the title link
                        title_link = tile.find('a', class_='attrax-vacancy-tile__title')
                        if not title_link:
                            continue
                        
                        job_title = title_link.get_text(strip=True)
                        if not self._is_valid_job_title(job_title):
                            continue
                        
                        job_url = title_link.get('href', '').strip()
                        if not job_url:
                            continue
                        
                        if not job_url.startswith('http'):
                            job_url = 'https://wise.jobs' + job_url if job_url.startswith('/') else job_url
                        
                        if not self._is_valid_job_url(job_url):
                            continue
                        
                        # Extract location from the location div
                        location = ''
                        location_div = tile.find('div', class_='attrax-vacancy-tile__location-freetext')
                        if location_div:
                            location_value = location_div.find('p', class_='attrax-vacancy-tile__item-value')
                            if location_value:
                                location = location_value.get_text(strip=True)
                        
                        # Avoid duplicates
                        if not any(j['url'] == job_url for j in all_jobs):
                            all_jobs.append({
                                'title': job_title,
                                'url': job_url,
                                'location': location,
                                'description': '',
                                'company': 'Wise',
                                'date_scraped': datetime.now().isoformat()
                            })
                    except Exception as e:
                        logger.debug(f"Error parsing Wise job: {e}")
                
                # Try to click next page button
                try:
                    pagination_links = soup.find_all('a', class_='attrax-pagination__page-item')
                    next_page_link = None
                    
                    for link in pagination_links:
                        link_text = link.get_text(strip=True)
                        if link_text == str(page_num + 1):
                            next_page_link = link
                            break
                    
                    if not next_page_link:
                        # Try to find via JavaScript pagination call
                        try:
                            driver.execute_script(f"pagination({page_num + 1})")
                            time.sleep(2)
                            page_num += 1
                            continue
                        except:
                            break
                    
                    # Click next page
                    driver.execute_script("arguments[0].scrollIntoView(true);", next_page_link)
                    time.sleep(1)
                    next_page_link.click()
                    time.sleep(2)
                    page_num += 1
                except:
                    break
            
            driver.quit()
            logger.info(f"Found {len(all_jobs)} Wise jobs")
        
        except Exception as e:
            logger.error(f"Error extracting Wise jobs: {e}")
        
        return all_jobs
    
    def extract_jobs_from_efinancialcareers(self, url: str) -> List[Dict]:
        """Extract jobs from eFinancialCareers portal using Selenium."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading eFinancialCareers page with Selenium...")
            driver.get(url)

            # Wait for job cards to load
            try:
                wait = WebDriverWait(driver, 15)
                wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "efc-job-card")))
                time.sleep(2)  # Extra wait for page to stabilize
            except:
                logger.info("Timeout waiting for jobs, continuing anyway")
                time.sleep(5)

            # Click "Show more" button repeatedly to load all jobs
            max_clicks = 20
            prev_job_count = 0

            for click_count in range(max_clicks):
                try:
                    # Wait a moment for DOM to be stable
                    time.sleep(1)

                    # Find the Show More button fresh each iteration
                    show_more_buttons = driver.find_elements(By.CSS_SELECTOR, "button[data-gtm-trackable='Show More']")

                    if not show_more_buttons:
                        # Try XPath as fallback
                        show_more_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Show more')]")

                    if not show_more_buttons:
                        current_cards = driver.find_elements(By.TAG_NAME, "efc-job-card")
                        logger.info(f"No more 'Show more' button found after {click_count} clicks, {len(current_cards)} jobs loaded")
                        break

                    # Count jobs before click
                    current_cards = driver.find_elements(By.TAG_NAME, "efc-job-card")
                    current_count = len(current_cards)

                    # Click using JavaScript (more reliable)
                    driver.execute_script("""
                        var btn = document.querySelector("button[data-gtm-trackable='Show More']");
                        if (btn) {
                            btn.scrollIntoView({block: 'center'});
                            btn.click();
                        }
                    """)
                    logger.info(f"Clicked 'Show more' button ({click_count + 1}), currently {current_count} jobs")

                    # Wait for new content to load
                    time.sleep(3)

                    # Check if we got more jobs
                    new_cards = driver.find_elements(By.TAG_NAME, "efc-job-card")
                    new_count = len(new_cards)

                    if new_count <= current_count:
                        logger.info(f"No new jobs loaded ({new_count} <= {current_count}), stopping")
                        break

                    prev_job_count = new_count

                except Exception as e:
                    logger.info(f"Show more button click stopped after {click_count} clicks: {type(e).__name__}")
                    break

            html_content = driver.page_source
            driver.quit()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Find job cards using efc-job-card custom element
            job_cards = soup.find_all('efc-job-card')

            if not job_cards:
                logger.info("No job cards found on eFinancialCareers page")
                return all_jobs

            for card in job_cards:
                try:
                    # Find the job title link - has class 'job-title' and href with /jobs-
                    job_link = card.find('a', class_=lambda x: x and 'job-title' in x if x else False)
                    if not job_link:
                        # Fallback: find link with /jobs- in href
                        all_links = card.find_all('a')
                        for link in all_links:
                            href = link.get('href', '')
                            text = link.get_text(strip=True)
                            # Skip "Apply now" links and empty text
                            if '/jobs-' in href and text and 'apply' not in text.lower():
                                job_link = link
                                break

                    if not job_link:
                        continue

                    job_title = job_link.get_text(strip=True)
                    if not job_title or len(job_title) < 5:
                        continue

                    job_url = job_link.get('href', '').strip()
                    if not job_url:
                        continue

                    if not job_url.startswith('http'):
                        job_url = 'https://www.efinancialcareers.co.uk' + job_url if job_url.startswith('/') else job_url

                    # Extract company name from div with class 'company'
                    company_name = 'Unknown'
                    company_div = card.find('div', class_='company')
                    if company_div:
                        company_name = company_div.get_text(strip=True)

                    # Extract location from span with dot-divider class
                    location = ''
                    location_span = card.find('span', class_='dot-divider')
                    if location_span:
                        location = location_span.get_text(strip=True)

                    # Avoid duplicates
                    if any(j['url'] == job_url for j in all_jobs):
                        continue

                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location,
                        'description': '',
                        'company': company_name,
                        'source': 'eFinancialCareers',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing eFinancialCareers job: {e}")

            logger.info(f"Found {len(all_jobs)} eFinancialCareers jobs")

        except Exception as e:
            logger.error(f"Error extracting eFinancialCareers jobs: {e}")

        return all_jobs

    def extract_jobs_from_revolut(self, url: str) -> List[Dict]:
        """Extract jobs from Revolut careers page with Show More button."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading Revolut careers page with Selenium...")
            driver.get(url)
            time.sleep(3)

            # Click "Show more" button repeatedly to load all jobs
            max_clicks = 20
            for click_count in range(max_clicks):
                try:
                    time.sleep(1)
                    # Find Show more button
                    show_more_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Show more')]")
                    if not show_more_buttons:
                        show_more_buttons = driver.find_elements(By.XPATH, "//span[contains(text(), 'Show more')]/parent::button")

                    if not show_more_buttons:
                        logger.info(f"No more 'Show more' button found after {click_count} clicks")
                        break

                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", show_more_buttons[0])
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", show_more_buttons[0])
                    logger.info(f"Clicked 'Show more' button ({click_count + 1})")
                    time.sleep(2)

                except Exception as e:
                    logger.info(f"Show more stopped: {type(e).__name__}")
                    break

            html_content = driver.page_source
            driver.quit()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Find job links with /careers/position/ pattern
            job_links = soup.find_all('a', href=lambda x: x and '/careers/position/' in x)

            for link in job_links:
                try:
                    href = link.get('href', '').strip()
                    if not href:
                        continue

                    # Extract job title - it's in the link text before "Office:" or "Remote:"
                    full_text = link.get_text(strip=True)
                    # Split on Office: or Remote: to get just the title
                    job_title = full_text.split('Office:')[0].split('Remote:')[0].strip()

                    if not job_title or len(job_title) < 5:
                        continue

                    job_url = href if href.startswith('http') else 'https://www.revolut.com' + href

                    # Extract location from the text
                    location = ''
                    if 'London' in full_text:
                        location = 'London'
                    elif 'Office:' in full_text:
                        location = full_text.split('Office:')[1].split('Remote:')[0].strip()

                    # Avoid duplicates
                    if any(j['url'] == job_url for j in all_jobs):
                        continue

                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location,
                        'description': '',
                        'company': 'Revolut',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing Revolut job: {e}")

            logger.info(f"Found {len(all_jobs)} Revolut jobs")

        except Exception as e:
            logger.error(f"Error extracting Revolut jobs: {e}")

        return all_jobs

    def extract_jobs_from_monzo(self, url: str) -> List[Dict]:
        """Extract jobs from Monzo careers page."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading Monzo careers page with Selenium...")
            driver.get(url)
            time.sleep(5)

            html_content = driver.page_source
            driver.quit()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Find job cards using Card_cardWrapper class that links to greenhouse
            # Structure: <a class="Card_cardWrapper__TTeTI" href="https://job-boards.greenhouse.io/monzo/jobs/...">
            #   <h3 class="Card_title__2ya4E">Job Title</h3>
            #   <div class="Text_text__CSJ_O"><p>Location</p></div>
            # </a>
            job_cards = soup.find_all('a', class_=lambda x: x and 'Card_cardWrapper' in x)

            # If not found by class, try finding links to greenhouse
            if not job_cards:
                job_cards = soup.find_all('a', href=lambda x: x and 'greenhouse.io/monzo' in x)

            for card in job_cards:
                try:
                    href = card.get('href', '').strip()
                    if not href or 'greenhouse' not in href:
                        continue

                    # Get job title from h3 with Card_title class
                    title_elem = card.find('h3', class_=lambda x: x and 'Card_title' in x if x else False)
                    if not title_elem:
                        # Fallback: find any h3
                        title_elem = card.find('h3')

                    job_title = title_elem.get_text(strip=True) if title_elem else ''

                    if not job_title or len(job_title) < 5:
                        continue

                    job_url = href

                    # Get location from Text_text div
                    location = 'London'
                    text_div = card.find('div', class_=lambda x: x and 'Text_text' in x if x else False)
                    if text_div:
                        location_p = text_div.find('p')
                        if location_p:
                            location = location_p.get_text(strip=True)

                    # Avoid duplicates
                    if any(j['url'] == job_url for j in all_jobs):
                        continue

                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location,
                        'description': '',
                        'company': 'Monzo',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing Monzo job: {e}")

            logger.info(f"Found {len(all_jobs)} Monzo jobs")

        except Exception as e:
            logger.error(f"Error extracting Monzo jobs: {e}")

        return all_jobs

    def extract_jobs_from_starling(self, url: str) -> List[Dict]:
        """Extract jobs from Starling Bank careers page with London filter."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading Starling Bank careers page with Selenium...")
            driver.get(url)
            time.sleep(3)

            # Click London checkbox filter using input#london
            # Structure: <input id="london" name="London" type="checkbox">
            try:
                london_checkbox = driver.find_element(By.CSS_SELECTOR, "input#london")
                driver.execute_script("arguments[0].click();", london_checkbox)
                logger.info("Clicked London checkbox filter")
                time.sleep(2)
            except Exception as e:
                logger.warning(f"Could not click London checkbox: {e}")
                # Try alternative: click the label for the checkbox
                try:
                    london_label = driver.find_element(By.CSS_SELECTOR, "label[for='london']")
                    driver.execute_script("arguments[0].click();", london_label)
                    logger.info("Clicked London label instead")
                    time.sleep(2)
                except:
                    pass

            html_content = driver.page_source
            driver.quit()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Find job cards using xhntxq2 class (li elements)
            # Structure: <li class="xhntxq2">
            #   <h3>Job Title</h3>
            #   <a href="https://apply.workable.com/j/..."><span>Location</span></a>
            # </li>
            job_items = soup.find_all('li', class_=lambda x: x and 'xhntxq2' in x if x else False)

            # Fallback: also try finding workable links directly
            if not job_items:
                workable_links = soup.find_all('a', href=lambda x: x and 'workable.com' in x)
                for link in workable_links:
                    try:
                        href = link.get('href', '').strip()
                        if not href:
                            continue

                        # Try to find the job title from parent or sibling h3
                        parent = link.find_parent('li')
                        title_elem = parent.find('h3') if parent else None
                        job_title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)

                        if not job_title or len(job_title) < 5:
                            continue

                        if any(j['url'] == href for j in all_jobs):
                            continue

                        all_jobs.append({
                            'title': job_title,
                            'url': href,
                            'location': 'London',
                            'description': '',
                            'company': 'Starling Bank',
                            'date_scraped': datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.debug(f"Error parsing Starling workable link: {e}")
            else:
                for item in job_items:
                    try:
                        # Get job title from h3
                        title_elem = item.find('h3')
                        job_title = title_elem.get_text(strip=True) if title_elem else ''

                        if not job_title or len(job_title) < 5:
                            continue

                        # Get URL from workable link
                        job_link = item.find('a', href=lambda x: x and 'workable.com' in x)
                        if not job_link:
                            # Try any link in the item
                            job_link = item.find('a', href=True)

                        href = job_link.get('href', '').strip() if job_link else ''
                        if not href:
                            continue

                        # Get location from span inside link
                        location = 'London'
                        if job_link:
                            location_span = job_link.find('span')
                            if location_span:
                                location = location_span.get_text(strip=True)

                        # Avoid duplicates
                        if any(j['url'] == href for j in all_jobs):
                            continue

                        all_jobs.append({
                            'title': job_title,
                            'url': href,
                            'location': location,
                            'description': '',
                            'company': 'Starling Bank',
                            'date_scraped': datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.debug(f"Error parsing Starling job: {e}")

            logger.info(f"Found {len(all_jobs)} Starling Bank jobs")

        except Exception as e:
            logger.error(f"Error extracting Starling Bank jobs: {e}")

        return all_jobs

    def extract_jobs_from_stripe(self, url: str) -> List[Dict]:
        """Extract jobs from Stripe careers page."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading Stripe careers page with Selenium...")
            driver.get(url)
            time.sleep(5)

            html_content = driver.page_source
            driver.quit()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Find job links - Stripe uses /jobs/ pattern
            job_links = soup.find_all('a', href=lambda x: x and '/jobs/' in x and '/jobs/search' not in x)

            for link in job_links:
                try:
                    href = link.get('href', '').strip()
                    if not href or '/jobs/search' in href:
                        continue

                    job_title = link.get_text(strip=True)
                    if not job_title or len(job_title) < 5:
                        continue

                    job_url = href if href.startswith('http') else 'https://stripe.com' + href

                    # Avoid duplicates
                    if any(j['url'] == job_url for j in all_jobs):
                        continue

                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': 'London',
                        'description': '',
                        'company': 'Stripe',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing Stripe job: {e}")

            logger.info(f"Found {len(all_jobs)} Stripe jobs")

        except Exception as e:
            logger.error(f"Error extracting Stripe jobs: {e}")

        return all_jobs

    def extract_jobs_from_checkout(self, url: str) -> List[Dict]:
        """Extract jobs from Checkout.com careers page."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading Checkout.com careers page with Selenium...")
            driver.get(url)
            time.sleep(5)

            html_content = driver.page_source
            driver.quit()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Find job items using careers-table-item class
            # Structure: <a class="careers-table-item" href="https://checkout.wd3.myworkdayjobs.com/...">
            #   <div class="rb-careers-item-link">Job Title</div>
            #   <div class="rb-label-pill-small">Team</div>
            #   <div class="rb-paragraph-regular">Location</div>
            # </a>
            job_items = soup.find_all('a', class_='careers-table-item')

            for item in job_items:
                try:
                    href = item.get('href', '').strip()
                    if not href:
                        continue

                    # Get job title from rb-careers-item-link div
                    title_div = item.find('div', class_='rb-careers-item-link')
                    job_title = title_div.get_text(strip=True) if title_div else ''

                    if not job_title or len(job_title) < 5:
                        continue

                    # URL is already absolute (points to workday)
                    job_url = href

                    # Get team/department from rb-label-pill-small
                    team = ''
                    team_div = item.find('div', class_='rb-label-pill-small')
                    if team_div:
                        team = team_div.get_text(strip=True)

                    # Get location from rb-paragraph-regular
                    location = 'London'
                    location_div = item.find('div', class_='rb-paragraph-regular')
                    if location_div:
                        location = location_div.get_text(strip=True)

                    # Avoid duplicates
                    if any(j['url'] == job_url for j in all_jobs):
                        continue

                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location,
                        'team': team,
                        'description': '',
                        'company': 'Checkout.com',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing Checkout.com job: {e}")

            logger.info(f"Found {len(all_jobs)} Checkout.com jobs")

        except Exception as e:
            logger.error(f"Error extracting Checkout.com jobs: {e}")

        return all_jobs

    def extract_jobs_from_sumup(self, url: str) -> List[Dict]:
        """Extract jobs from SumUp careers page."""
        all_jobs = []
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Loading SumUp careers page with Selenium...")
            driver.get(url)
            time.sleep(5)

            html_content = driver.page_source
            driver.quit()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Find job links using the data-selector attribute
            job_links = soup.find_all('a', {'data-selector': 'department_position@careers'})

            for link in job_links:
                try:
                    href = link.get('href', '').strip()
                    if not href:
                        continue

                    # Get job title from p element
                    title_elem = link.find('p', class_=lambda x: x and 'body' in str(x))
                    job_title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)

                    if not job_title or len(job_title) < 5:
                        continue

                    job_url = href if href.startswith('http') else 'https://www.sumup.com' + href

                    # Get location from badge
                    location = ''
                    location_badge = link.find('div', {'data-selector': 'location-badge@careers'})
                    if location_badge:
                        location = location_badge.get_text(strip=True)

                    # Avoid duplicates
                    if any(j['url'] == job_url for j in all_jobs):
                        continue

                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location if location else 'London',
                        'description': '',
                        'company': 'SumUp',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing SumUp job: {e}")

            logger.info(f"Found {len(all_jobs)} SumUp jobs")

        except Exception as e:
            logger.error(f"Error extracting SumUp jobs: {e}")

        return all_jobs

    def extract_jobs_from_gocardless(self, url: str) -> List[Dict]:
        """Extract jobs from GoCardless Greenhouse board."""
        all_jobs = []
        try:
            soup = self.fetch_page(url)
            if not soup:
                return all_jobs

            # Find job rows in the table structure
            job_rows = soup.find_all('tr', class_='job-post')

            for row in job_rows:
                try:
                    link = row.find('a', href=True)
                    if not link:
                        continue

                    href = link.get('href', '').strip()

                    # Get job title from p.body--medium
                    title_elem = link.find('p', class_='body--medium')
                    job_title = title_elem.get_text(strip=True) if title_elem else ''

                    if not job_title or len(job_title) < 5:
                        continue

                    job_url = href if href.startswith('http') else 'https://job-boards.greenhouse.io' + href

                    # Get location from p.body__secondary
                    location = ''
                    location_elem = link.find('p', class_='body__secondary')
                    if location_elem:
                        location = location_elem.get_text(strip=True)

                    # Avoid duplicates
                    if any(j['url'] == job_url for j in all_jobs):
                        continue

                    all_jobs.append({
                        'title': job_title,
                        'url': job_url,
                        'location': location if location else 'London',
                        'description': '',
                        'company': 'GoCardless',
                        'date_scraped': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing GoCardless job: {e}")

            logger.info(f"Found {len(all_jobs)} GoCardless jobs")

        except Exception as e:
            logger.error(f"Error extracting GoCardless jobs: {e}")

        return all_jobs

    def load_existing_jobs(self) -> Dict[str, Dict]:
        """Load existing jobs from output file and return as URL-keyed dict."""
        existing = {}
        try:
            with open(self.output_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
                for job in jobs:
                    url = job.get('url', '')
                    if url:
                        existing[url] = job
            logger.info(f"Loaded {len(existing)} existing jobs from {self.output_file}")
        except FileNotFoundError:
            logger.info(f"No existing file {self.output_file}, starting fresh")
        except Exception as e:
            logger.warning(f"Could not load existing jobs: {e}")
        return existing

    def scrape_all_sources(self, fetch_descriptions: bool = False, companies: List[str] = None, incremental: bool = True) -> None:
        """
        Scrape configured job sources.

        Args:
            fetch_descriptions: If True, fetch full job descriptions from detail pages
            companies: List of company names to scrape. If None, scrape all.
            incremental: If True, load existing jobs and only fetch descriptions for new ones
        """
        # Load existing jobs for incremental mode
        existing_jobs = {}
        if incremental:
            existing_jobs = self.load_existing_jobs()
        sources = [
            # Banks
            ('NatWest', 'https://jobs.natwestgroup.com/search/software-engineering/jobs/in/london',
             self.extract_jobs_from_natwest),
            ('HSBC', 'https://portal.careers.hsbc.com/careers?location=London%2C%20United%20Kingdom&department=Technology&department=Engineering&pid=563774601794204&domain=hsbc.com&sort_by=relevance&triggerGoButton=true',
             self.extract_jobs_from_hsbc),
            ('Barclays', 'https://search.jobs.barclays/search-jobs/engineering/London%2C%20England/13015/1/4/2635167-6269131-2648110-2643743/51x50852966308594/-0x12574000656604767/50/2',
             self.extract_jobs_from_barclays),
            # Fintech - Money Transfer
            ('Wise', 'https://wise.jobs/jobs?options=343&page=1',
             self.extract_jobs_from_wise),
            # Fintech - Neobanks
            ('Revolut', 'https://www.revolut.com/careers/?team=Engineering&city=London',
             self.extract_jobs_from_revolut),
            ('Monzo', 'https://monzo.com/careers/',
             self.extract_jobs_from_monzo),
            ('Starling', 'https://www.starlingbank.com/careers/',
             self.extract_jobs_from_starling),
            # Fintech - Payments
            ('Stripe', 'https://stripe.com/jobs/search?office_locations=London',
             self.extract_jobs_from_stripe),
            ('Checkout.com', 'https://www.checkout.com/jobs/?location=London&team=Technology',
             self.extract_jobs_from_checkout),
            ('SumUp', 'https://www.sumup.com/careers/positions/?city=United%20Kingdom&department=Engineering',
             self.extract_jobs_from_sumup),
            ('GoCardless', 'https://job-boards.greenhouse.io/gocardless?offices%5B%5D=85095&departments%5B%5D=38957',
             self.extract_jobs_from_gocardless),
            # Job Aggregator
            ('eFinancialCareers', 'https://www.efinancialcareers.co.uk/jobs/senior-engineering-manager/in-london%2C-uk?q=senior+engineering+manager&location=London%2C+UK&latitude=51.50721&longitude=-0.12758&countryCode=GB&locationPrecision=City&radius=40&radiusUnit=km&pageSize=15&currencyCode=GBP&language=en&includeUnspecifiedSalary=true&enableVectorSearch=true',
             self.extract_jobs_from_efinancialcareers),
        ]
        
        for company_name, url, extract_func in sources:
            # Skip if specific companies list provided and this company not in it
            if companies and company_name not in companies:
                logger.info(f"Skipping {company_name} (not in filter list)")
                continue
            
            logger.info(f"Scraping {company_name}: {url}")
            jobs = extract_func(url)
            
            # Optionally fetch full descriptions
            if fetch_descriptions:
                for job in jobs:
                    if job.get('url'):
                        job_url = job['url']
                        # Check if job already exists with description (incremental mode)
                        if incremental and job_url in existing_jobs:
                            existing_desc = existing_jobs[job_url].get('description', '')
                            if existing_desc and len(existing_desc.strip()) > 50:
                                logger.info(f"Skipping (existing description): {job['title']}")
                                job['description'] = existing_desc
                                continue
                        logger.info(f"Fetching description for: {job['title']}")
                        source = job.get('source', company_name)
                        job['description'] = self.fetch_job_description(job['url'], job['company'], source)
            
            self.jobs.extend(jobs)
            logger.info(f"Found {len(jobs)} {company_name} jobs")
    
    def save_to_json(self) -> None:
        """Save scraped jobs to JSON file."""
        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(self.jobs, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(self.jobs)} jobs to {self.output_file}")
        except Exception as e:
            logger.error(f"Error saving to JSON: {e}")
    
    def display_summary(self) -> None:
        """Display summary of scraped jobs."""
        if not self.jobs:
            logger.warning("No jobs were scraped")
            return
        
        companies = {}
        for job in self.jobs:
            company = job.get('company', 'Unknown')
            companies[company] = companies.get(company, 0) + 1
        
        logger.info("=" * 50)
        logger.info(f"Total jobs scraped: {len(self.jobs)}")
        for company, count in companies.items():
            logger.info(f"  {company}: {count} jobs")
        logger.info("=" * 50)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Job scraper and JSON augmenter')
    parser.add_argument('--augment', '-a', metavar='FILE', help='Path to existing jobs JSON to augment descriptions')
    parser.add_argument('--fetch-descriptions', '-f', action='store_true', help='When scraping, fetch full job descriptions')
    parser.add_argument('--force', action='store_true', help='Force refresh descriptions even when present in the JSON')
    parser.add_argument('--no-incremental', action='store_true', help='Disable incremental mode (re-fetch all descriptions)')
    parser.add_argument('--company', '-c', help='Scrape only specific company (NatWest, HSBC, Barclays, Klarna, Wise, or eFinancialCareers)')
    args = parser.parse_args()

    logger.info("Starting job scraper...")

    scraper = JobScraper()

    if args.augment:
        # Augment an existing JSON file: load entries and fetch descriptions for each job
        json_path = args.augment
        try:
            with open(json_path, 'r', encoding='utf-8') as jf:
                jobs = json.load(jf)
        except Exception as e:
            logger.error(f"Failed to load JSON file {json_path}: {e}")
            return

        updated = 0
        for i, job in enumerate(jobs):
            url = job.get('url')
            company = job.get('company', 'Unknown')
            # Only augment if URL present
            if not url:
                continue
            # Skip if description already present unless force flag set
            if job.get('description') and not args.force:
                continue

            logger.info(f"Fetching description for ({i+1}/{len(jobs)}): {job.get('title')} - {url}")
            desc = scraper.fetch_job_description(url, company)
            if desc:
                job['description'] = desc
                updated += 1

        try:
            with open(json_path, 'w', encoding='utf-8') as jf:
                json.dump(jobs, jf, indent=2, ensure_ascii=False)
            logger.info(f"Augmented {updated} job descriptions and saved to {json_path}")
        except Exception as e:
            logger.error(f"Failed to save augmented JSON to {json_path}: {e}")

        return

    # Default behavior: scrape configured sources
    fetch_descriptions = bool(args.fetch_descriptions)
    companies_filter = [args.company] if args.company else None
    incremental = not args.no_incremental

    scraper.scrape_all_sources(fetch_descriptions=fetch_descriptions, companies=companies_filter, incremental=incremental)
    scraper.save_to_json()
    scraper.display_summary()

    logger.info("Job scraping completed!")
    logger.info(f"Results saved to: {scraper.output_file}")


if __name__ == "__main__":
    main()
