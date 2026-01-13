# Job Scraper - Direct from Company Websites

A comprehensive job scraping toolkit that collects job listings directly from company career pages. Includes Python scrapers for 90+ companies, remote job boards, AI-powered job matching, and a Chrome extension for quick exports.

## Features

- **Workday API Scraper**: Direct API access to 87+ major companies (NVIDIA, Netflix, HSBC, FCA, etc.)
- **Playwright Scrapers**: Browser automation for Cisco, Google, IBM, Apple, Meta, Amazon
- **Company-Specific Scrapers**: Custom scrapers for HSBC, Barclays, Stripe, Revolut, Wise, etc.
- **Remote Job Boards**: WeWorkRemotely + RemoteOK aggregators
- **LinkedIn Scraper**: Public API scraper with date filtering
- **Generic HTML Scraper**: Parse saved career pages from 20+ platforms
- **Chrome Extension**: Detect and export job listings from any careers page
- **AI Job Filtering**: Score jobs against your CV using Claude, Ollama, or llama-cli
- **Excel Export**: Generate Excel reports with clickable links and color-coded results

## Quick Start - Full Pipeline

```bash
# Install dependencies
pip install -r requirements.txt

# Run EVERYTHING: scrape all companies + AI filter + Excel report
python run_pipeline.py --location London --claude-model haiku

# Quick mode (skip slow scrapers)
python run_pipeline.py --location London --quick

# Only run AI filter on existing data
python run_pipeline.py --ai-only --location London --claude-model haiku

# Only scrape, no AI filter
python run_pipeline.py --scrape-only --location London
```

### Pipeline Options

```bash
python run_pipeline.py [OPTIONS]

Options:
  --location, -l      Location to search (default: London)
  --claude-model      Claude model: haiku (fast), sonnet, opus
  --limit, -n         Limit jobs for AI filter
  --ai-only           Only run AI filter on existing data
  --scrape-only       Only scrape, skip AI filter
  --quick             Skip slow scrapers (LinkedIn, Playwright, company)
  --skip-workday      Skip Workday scrapers
  --skip-playwright   Skip Playwright scrapers
  --skip-company      Skip company-specific scrapers (HSBC, Barclays, etc.)
  --skip-linkedin     Skip LinkedIn scraper
  --skip-remote       Skip remote job boards
```

### Pipeline Output

```
output/ai_filtered_claude_haiku_TIMESTAMP.xlsx   # Excel with scored jobs
output/ai_filtered_claude_haiku_TIMESTAMP.json   # Full results JSON
output/ai_filtered_*_shortlist.json              # Matched jobs only
```

## AI Job Filter

Score and filter jobs against your CV using AI. Output files include model name for easy comparison.

### Backends

```bash
# Claude (cloud) - recommended, fast & accurate
python job_filter_ai.py --claude --claude-model haiku -l London
python job_filter_ai.py --claude --claude-model sonnet -l London

# Ollama (local) - requires: ollama serve
python job_filter_ai.py --ollama --model llama3.2 -l London
python job_filter_ai.py --ollama --model qwen2.5:7b -l London

# llama.cpp (local) - requires: llama-cli in PATH
python job_filter_ai.py --llama-cli -l London
```

### Compare Models

Run the same jobs through different models and compare Excel outputs:

```bash
# Run with Claude
python job_filter_ai.py --claude --claude-model haiku -l London
# Output: ai_filtered_claude_haiku_*.xlsx

# Run with Ollama
ollama serve  # Start server first
python job_filter_ai.py --ollama --model llama3.2 -l London
# Output: ai_filtered_ollama_llama3_2_*.xlsx
```

### AI Backend Comparison

| Backend | Command | Cost | Speed | Quality |
|---------|---------|------|-------|---------|
| Claude Haiku | `--claude --claude-model haiku` | $ | Fast | Good |
| Claude Sonnet | `--claude --claude-model sonnet` | $$ | Medium | Better |
| Ollama | `--ollama --model llama3.2` | Free | Medium | Good |
| Ollama | `--ollama --model qwen2.5:7b` | Free | Slower | Good |
| llama.cpp | `--llama-cli` | Free | Varies | Good |

### Excel Report Sheets

- **All Jobs** - All processed jobs sorted by score
- **Matched** - Recommended jobs (score >= 6) with green highlighting
- **AI Rejected** - Reviewed by AI but didn't match
- **Quick Filtered** - Keyword-filtered (title/description exclusions)
- **Summary** - Stats by company

## Scrapers

### Workday API Scraper (87+ Companies)

Direct API access - no HTML saving needed!

```bash
python scrapers/workday_scraper.py --list              # Show all 87 companies
python scrapers/workday_scraper.py --all --search London  # All companies
python scrapers/workday_scraper.py --company nvidia --search UK
python scrapers/workday_scraper.py --test fca          # Test API endpoint
```

**UK-Focused Companies Include:**
- Regulators: FCA, PSR, Ofcom, ICO
- Banks: Lloyds Tech, Hargreaves Lansdown, Baillie Gifford, Lloyd's of London
- Insurance: Hiscox, Direct Line, First Central
- Tech: NCC Group, AVEVA, AstraZeneca, GSK
- Fintech: FNZ, abrdn, Equiniti, NewDay, Planet Payments
- Energy: Centrica, E.ON Next
- Retail: John Lewis Partnership
- And 60+ more...

### Company-Specific Scrapers

Run all company scrapers (HSBC, Barclays, Stripe, Revolut, Wise, etc.):

```bash
python scrapers/run_all.py              # Run ALL company scrapers
python scrapers/run_all.py --status     # Show status
python scrapers/run_all.py --company hsbc  # Specific company
```

Includes: HSBC, Barclays, Stripe, GoCardless, Marqeta, OakNorth, Rapyd, Revolut, Wise, Starling Bank, Coinbase, Plaid, Affirm, Adyen, and more.

### LinkedIn Scraper

```bash
cd scrap_with_batch
python linkedin_scraper.py -a -l "London, UK"           # All job titles from config
python linkedin_scraper.py -k "Engineering Manager" -l "London, UK" -n 50
python linkedin_scraper.py -t 48h                       # Last 48 hours only
```

Configure job titles and filters in `scrap_with_batch/config.json`.

### Remote Job Boards

```bash
python scrapers/remote_jobs_scraper.py                    # All sources
python scrapers/remote_jobs_scraper.py --source wwr       # WeWorkRemotely only
python scrapers/remote_jobs_scraper.py --source remoteok  # RemoteOK only
```

### Playwright Scrapers

Browser automation for sites that need JavaScript rendering:

```bash
python scrapers/playwright_scraper_v2.py --all --location London
```

Supports: Cisco, Google, IBM, Apple, Meta, Amazon, Microsoft, BMW, Mercedes-Benz, etc.

## Chrome Extension

Quickly detect and export job listings from any careers page.

### Installation

1. Open Chrome -> `chrome://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked" -> Select `chrome_extension/` folder

### Usage

- **Alt+J**: Open popup to scan current page
- **Alt+Shift+J**: Quick export (no popup)
- Exports to `Company_Pages/<CompanyName>/jobs_export.json`

## Configuration

### AI Filter Config (`N8n/config.json`)

```json
{
  "cv_file": "N8n/data/Your_CV.txt",
  "min_score": 6,
  "exclude_in_title": ["junior", "intern", "sales", "marketing"],
  "exclude_in_description": ["CSCS card", "construction"],
  "ollama_model": "qwen2.5:7b",
  "claude_model": "haiku"
}
```

### Adding New Workday Companies

Add to `scrapers/workday_scraper.py`:

```python
"company_key": {
    "name": "Company Name",
    "api_url": "https://company.wd5.myworkdayjobs.com/wday/cxs/company/Site/jobs",
    "careers_url": "https://company.wd5.myworkdayjobs.com/en-US/Site",
    "location_filter": [],
}
```

To find the API URL:
1. Go to company's Workday careers page
2. Open DevTools -> Network -> XHR
3. Look for POST request to `/wday/cxs/.../jobs`

## Directory Structure

```
job-scraper/
├── run_pipeline.py          # MAIN SCRIPT - runs everything
├── job_filter_ai.py         # AI job filter (Claude/Ollama/llama-cli)
├── export_to_n8n.py         # Consolidate jobs from all sources
├── scrapers/
│   ├── workday_scraper.py   # Workday API (87+ companies)
│   ├── run_all.py           # Run all company scrapers
│   ├── playwright_scraper_v2.py
│   ├── remote_jobs_scraper.py
│   ├── generic_scraper.py
│   ├── hsbc_scraper.py, barclays_scraper.py, etc.
├── scrap_with_batch/
│   ├── linkedin_scraper.py  # LinkedIn public API
│   └── config.json          # LinkedIn config
├── chrome_extension/
├── N8n/
│   ├── config.json          # AI filter configuration
│   ├── data/                # CV files
│   └── fintech_jobs.json    # Consolidated jobs
├── Company_Pages/           # Chrome extension exports
├── output/                  # JSON/Excel output files
└── requirements.txt
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    run_pipeline.py                          │
├─────────────────────────────────────────────────────────────┤
│  1. Workday Scraper (87 companies)                          │
│  2. Playwright Scraper (Cisco, Google, IBM, etc.)          │
│  3. Company Scrapers (HSBC, Barclays, Stripe, etc.)        │
│  4. LinkedIn Scraper                                        │
│  5. Remote Job Boards                                       │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  export_to_n8n.py                           │
│  Consolidates from:                                         │
│  - output/*.json                                            │
│  - Company_Pages/**/*.json (Chrome extension)              │
│  - scrap_with_batch/linkedin_jobs_*.json                   │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   N8n/fintech_jobs.json                     │
│                  (All jobs consolidated)                    │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   job_filter_ai.py                          │
│  - Score each job against CV                                │
│  - Claude / Ollama / llama-cli                              │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                      OUTPUT                                 │
│  - ai_filtered_MODEL_TIMESTAMP.xlsx                        │
│  - ai_filtered_MODEL_TIMESTAMP_shortlist.json              │
└─────────────────────────────────────────────────────────────┘
```

## Requirements

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/job-scraper.git
cd job-scraper

# 2. Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers (required for some scrapers)
playwright install chromium
```

### Python Dependencies

```
requests>=2.28.0
beautifulsoup4>=4.11.0
lxml>=4.9.0
openpyxl>=3.1.0
playwright>=1.40.0  # For browser automation
```

### For AI Filtering

Choose one of these backends:

- **Claude CLI** (recommended): `npm install -g @anthropic-ai/claude-code`
- **Ollama** (local): https://ollama.ai + `ollama pull llama3.2`
- **llama.cpp** (local): https://github.com/ggerganov/llama.cpp

### Platform Notes

**Linux:**
- May need `python3-tk` for GUI: `sudo apt install python3-tk`
- Playwright may need additional dependencies: `playwright install-deps`

**Mac:**
- Homebrew Python recommended: `brew install python`

**Windows:**
- Works out of the box with Python from python.org

### CV Setup (for AI filtering)

Place your CV in plain text format:
```bash
# Create the data directory
mkdir -p N8n/data

# Add your CV (plain text works best for AI matching)
cp ~/your_cv.txt N8n/data/your_cv.txt
```

## Troubleshooting

**Pipeline timeout:**
- Default timeout is 10 hours (for overnight runs)
- Use `--quick` to skip slow scrapers

**No jobs found:**
- Check if API endpoint is working: `python scrapers/workday_scraper.py --test company`
- Some sites need JavaScript - use Chrome extension

**AI filter slow:**
- Use `--limit 100` to test with fewer jobs first
- Claude Haiku is fastest, Ollama varies by hardware

## License

MIT License
