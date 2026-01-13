# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Job scraping toolkit that collects listings directly from company career pages. Includes scrapers for 70+ companies, remote job boards, AI-powered job matching, and a Chrome extension.

## Commands

```bash
# Install
pip install -r requirements.txt

# Run ALL scrapers (Workday + Playwright + HTML)
python run_all_scrapers.py --location London

# Workday scraper only (39+ companies - direct API)
python scrapers/workday_scraper.py --all --search London
python scrapers/workday_scraper.py --company nvidia --search UK
python scrapers/workday_scraper.py --list  # Show all companies

# Playwright scrapers (Cisco, Google, IBM, Apple, Meta, Amazon)
python scrapers/playwright_scraper_v2.py --all --location London

# AI job filter (score jobs against CV)
python job_filter_ai.py --claude --claude-model haiku  # Recommended
python job_filter_ai.py --llama-cli                    # Local LLM
python job_filter_ai.py --model qwen2.5:7b             # Ollama

# Export only (no scraping)
python run_all_scrapers.py --export-only
```

## Architecture

```
run_all_scrapers.py          # Master orchestrator - runs all scrapers
job_filter_ai.py             # AI filter using Claude/Ollama/llama-cli
export_to_excel.py           # Excel export with clickable links

scrapers/
├── workday_scraper.py       # Workday API (39+ companies) - primary scraper
├── playwright_scraper_v2.py # Browser automation for big tech
├── remote_jobs_scraper.py   # WeWorkRemotely + RemoteOK
├── generic_scraper.py       # Multi-platform HTML parser
├── hsbc_scraper.py          # Phenom People API
├── barclays_scraper.py      # Custom HTTP scraper
└── run_html_scrapers.py     # Runs HTML-based scrapers

chrome_extension/            # Browser extension for quick job export
N8n/config.json             # AI filter configuration (CV path, models, thresholds)
```

## Adding New Workday Companies

Add to `WORKDAY_COMPANIES` dict in `scrapers/workday_scraper.py`:

```python
"company_key": {
    "name": "Company Name",
    "api_url": "https://company.wd5.myworkdayjobs.com/wday/cxs/company/Site/jobs",
    "careers_url": "https://company.wd5.myworkdayjobs.com/en-US/Site",
    "location_filter": [],
}
```

To find API URL: Open company's Workday careers page → DevTools → Network → XHR → Look for POST to `/wday/cxs/.../jobs`

## Output Format

JSON files saved to `output/` with structure:
```json
{
  "company": "NVIDIA",
  "scraped_at": "2024-12-10T22:00:00",
  "jobs": [{"title": "...", "location": "...", "url": "...", "description": "..."}]
}
```

## API Patterns

- **Workday**: `POST /wday/cxs/{company}/{site}/jobs` with `{"limit": 20, "offset": 0, "searchText": ""}`
- **Phenom (HSBC)**: `GET /api/apply/v2/jobs?domain=hsbc.com&location=X`
- **BambooHR**: `GET /careers/list` (JSON)
- **Greenhouse**: `GET /api/gh/embed/jobs` or HTML from boards.greenhouse.io

## Rate Limiting

All scrapers include delays: Workday 0.3-0.5s, HSBC 0.5s, Generic/Remote 1s
