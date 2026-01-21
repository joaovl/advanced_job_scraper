# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Job scraping toolkit that collects listings directly from company career pages. Includes scrapers for 70+ companies (LinkedIn, Workday, etc.), AI-powered job matching with Claude/Ollama, and a web UI for command building.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run all scrapers with sensible defaults (London, 48h, all scrapers)
python run.py

# Analyze jobs with AI (Claude Opus by default)
python analyze.py

# Full pipeline
python run.py && python analyze.py
```

## Architecture

```
job-scraper-clean/
├── run.py                    # Master orchestrator - runs all scrapers
├── analyze.py                # AI analyzer using Claude/Ollama
├── config.json               # Single config file
├── data/
│   └── cv.txt                # Your CV for job matching
├── output/                   # All scraper outputs
│   ├── linkedin_jobs_*.json
│   ├── workday_*.json
│   └── analysis_*.xlsx
├── scrapers/
│   ├── linkedin.py           # LinkedIn scraper (public API)
│   ├── workday_scraper.py    # Workday API (39+ companies)
│   ├── playwright_scraper_v2.py  # Big tech (Cisco, Google, IBM, Apple, Meta)
│   └── run_html_scrapers.py  # HTML-based scrapers
├── ui/
│   └── command_builder.html  # Web UI for command generation
├── chrome_extension/         # Browser extension for quick export
└── archive/                  # Old/deprecated scripts
```

## Commands

### Scraping (run.py)

```bash
# Default: London, 48h, all scrapers
python run.py

# LinkedIn only (fastest)
python run.py --linkedin-only

# Different location
python run.py --location Manchester -g 90009706

# Custom time range
python run.py -t 24h

# Skip certain scrapers
python run.py --skip-workday --skip-playwright

# Export only (no scraping)
python run.py --export-only
```

### Analysis (analyze.py)

```bash
# Default: latest JSON, Claude Opus, parallel
python analyze.py

# Specific file
python analyze.py -i output/linkedin_jobs_20260121.json

# Different model
python analyze.py --model haiku

# Ollama backend (local, free)
python analyze.py --backend ollama --model qwen2.5:7b

# Limit jobs for testing
python analyze.py --limit 10
```

### Other Scrapers

```bash
# Workday only (39+ companies)
python scrapers/workday_scraper.py --all --search London
python scrapers/workday_scraper.py --company nvidia --search UK
python scrapers/workday_scraper.py --list  # Show all companies

# Playwright (big tech)
python scrapers/playwright_scraper_v2.py --all --location London
```

## Sensible Defaults

| Setting | Default | Rationale |
|---------|---------|-----------|
| Location | London | User's primary market |
| GeoId | 90009496 | Greater London Area |
| Time Range | 48h | Recent but not too narrow |
| AI Model | Claude Opus | Best quality matching |
| Min Score | 7 | Reasonable threshold |
| Workers | cpu_count - 2 | Leave headroom for system |
| Scrapers | All | Comprehensive by default |

## Config (config.json)

Single source of truth for all settings:

```json
{
  "cv_file": "data/cv.txt",
  "scraping": {
    "location": "London",
    "geo_id": "90009496",
    "time_range": "48h",
    "job_titles": ["Head of Engineering", "Director of Engineering", ...]
  },
  "analysis": {
    "backend": "claude",
    "model": "opus",
    "min_score": 7
  },
  "filters": {
    "exclude_in_title": ["junior", "intern", ...],
    "exclude_in_description": ["CSCS card", ...],
    "positive_keywords": {"team": 4, "agile": 5, ...},
    "negative_keywords": {"hardware": -5, ...}
  }
}
```

## Analysis Pipeline

The `analyze.py` script uses a multi-stage filtering approach to minimize AI API usage:

### Stage 1: Pre-filtering (no AI cost)
- **Title exclusions**: Word-boundary matching (e.g., "Senior Engineer" excludes IC roles but NOT "Senior Engineering Manager")
- **Description exclusions**: Filter jobs mentioning irrelevant domains
- **Keyword scoring**: Jobs with cumulative negative score ≤ -8 are auto-rejected (e.g., "hardware" + "manufacturing" + "embedded" = -14)

### Stage 2: AI Scoring
- Jobs passing pre-filter are scored 1-10 by AI against your CV
- Score 7+ = Match, below 7 = Reject

### Stage 3: Auto-adjustment
- Detects when AI gives positive reasons but low score (inconsistent)
- Automatically bumps score to 7 if reasons sound positive and no clear negatives
- Tracked in output: `adjusted: true`, `original_score: 5`

### Output Files
- **JSON**: Full data with adjustment tracking (`original_score`, `adjusted` fields)
- **Excel**: Visual report with adjustments shown as "7 (was 5)" in light blue
- **Shortlist JSON**: Matched jobs only for easy review

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

- **LinkedIn**: Public guest API (no auth needed)
- **Workday**: `POST /wday/cxs/{company}/{site}/jobs` with `{"limit": 20, "offset": 0, "searchText": ""}`
- **Phenom (HSBC)**: `GET /api/apply/v2/jobs?domain=hsbc.com&location=X`
- **Greenhouse**: `GET /api/gh/embed/jobs` or HTML from boards.greenhouse.io

## Rate Limiting

All scrapers include delays: LinkedIn 2-4s, Workday 0.3-0.5s, HTML scrapers 1s

## Web UI

Open `ui/command_builder.html` in browser for interactive command building with:
- Scraping tab (location, time range, scraper selection)
- Analysis tab (backend, model, options)
- Quick action buttons for common commands
