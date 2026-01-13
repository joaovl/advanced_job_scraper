# Job Scraper & Analyzer

A unified job search system with LinkedIn and Fintech scrapers, AI-powered analysis, and a GUI.

## Quick Start

### Run Everything (Recommended)
```bash
# Scrape all sources + analyze (jobs from last 48 hours)
python run_all.py

# Jobs from last 24 hours
python run_all.py --time-range 24h
```

### Start Ollama (required for analysis)
```bash
ollama serve
```
Or open the Ollama app from Windows Start menu.

---

## run_all.py - Unified Script

The easiest way to run everything. Scrapes LinkedIn + Fintech, merges results, and runs AI analysis.

### Basic Usage
```bash
# Run everything with defaults (48h, all job titles)
python run_all.py

# Jobs from last 24 hours
python run_all.py --time-range 24h

# Jobs from last week
python run_all.py --time-range 7d
```

### Scrape Only (No Analysis)
```bash
# Just scrape, don't analyze
python run_all.py --scrape-only

# Only LinkedIn scraper
python run_all.py --scrape-only --linkedin-only

# Only Fintech scraper
python run_all.py --scrape-only --fintech-only
```

### Analyze Only (Existing Jobs)
```bash
# Analyze jobs already scraped
python run_all.py --analyze-only

# Limit analysis to 50 jobs
python run_all.py --analyze-only --limit 50

# Reanalyze all (don't skip previously analyzed)
python run_all.py --analyze-only --no-skip
```

### Retry Missing Descriptions
```bash
# Only retry fetching descriptions for jobs missing them
python run_all.py --retry-only

# Skip retry step (go straight to analysis)
python run_all.py --no-retry
```

### All Options
| Option | Description |
|--------|-------------|
| `--scrape-only` | Only run scrapers, no analysis |
| `--analyze-only` | Only analyze existing jobs |
| `--linkedin-only` | Only run LinkedIn scraper |
| `--fintech-only` | Only run Fintech scraper |
| `-t, --time-range` | Time filter: 24h, 48h, 7d, 30d (default: 48h) |
| `-l, --limit` | Limit jobs to analyze |
| `-o, --output` | Output filename prefix |
| `--no-skip` | Reanalyze all jobs |
| `--retry-only` | Only retry fetching missing descriptions |
| `--no-retry` | Skip retrying missing descriptions |

### Output Files
All output goes to the `output/` folder:
```
output/
├── linkedin_jobs_20251209.json    # LinkedIn scrape results
├── fintech_jobs_20251209.json     # Fintech scrape results
├── jobs_20251209.json             # Merged jobs (all sources)
├── analysis_20251209.xlsx         # Analysis Excel file
└── analysis_20251209.json         # Analysis JSON (for GUI)
```

---

## GUI - job_gui.py

Graphical interface for managing scrapers and viewing results.

```bash
python job_gui.py
```

### Features
- **Scraper Tab**: Configure and run LinkedIn/Fintech scrapers
- **Analyzer Tab**: Run AI analysis with options
- **Configuration Tab**: Edit keywords, weights, exclusions
- **Results Tab**: Browse jobs, view details, open URLs
- **History Tab**: View command history
- **Debug Tab**: View logs

---

## Individual Scrapers

### LinkedIn Scraper
```bash
# All job titles from config
python linkedin_scraper.py -a

# Specific keywords
python linkedin_scraper.py -k "Engineering Manager" -l "London, UK"

# With options
python linkedin_scraper.py -k "Head of QA" -n 100 -t 24h

# Skip fetching descriptions (faster)
python linkedin_scraper.py -a --no-description
```

#### Options
| Option | Description |
|--------|-------------|
| `-k, --keywords` | Search keywords |
| `-l, --location` | Location (default: from config) |
| `-n, --max-jobs` | Max jobs per search (0 = all) |
| `-t, --time-range` | Time filter: 24h, 48h, 7d |
| `-a, --all-titles` | Search all titles from config |
| `-nd, --no-description` | Skip descriptions (faster) |
| `-w, --workers` | Parallel threads (default: 2, use 1 for safest) |
| `-o, --output` | Output filename |
| `--no-merge` | Don't merge with existing file |

### Fintech Scraper
```bash
# Scrape all fintech companies
python job_scraper.py -f

# Specific company
python job_scraper.py -f --company Wise

# Augment existing file (fetch missing descriptions)
python job_scraper.py --augment jobs_20251209.json
```

#### Companies Scraped
- **Banks**: NatWest, HSBC, Barclays
- **Neobanks**: Revolut, Monzo, Starling Bank
- **Payments**: Stripe, Checkout.com, SumUp, GoCardless
- **Money Transfer**: Wise
- **Job Aggregator**: eFinancialCareers

---

## Job Analyzer

```bash
# Basic analysis
python job_analyzer.py output/jobs_20251209.json -o output/analysis.xlsx

# Limit to 50 jobs
python job_analyzer.py jobs.json --limit 50 -o analysis.xlsx

# Use specific model
python job_analyzer.py jobs.json --model llama3.1:8b -o analysis.xlsx

# Skip already analyzed jobs
python job_analyzer.py jobs.json --skip-analyzed previous.json -o analysis.xlsx

# Only show matches in output
python job_analyzer.py jobs.json --matched-only -o matched.xlsx
```

### Options
| Option | Description |
|--------|-------------|
| `--limit N` | Analyze first N jobs |
| `--company X` | Filter to specific company |
| `--model X` | Ollama model (default: qwen2.5:7b) |
| `--timeout N` | API timeout seconds (default: 180) |
| `--skip-analyzed FILE` | Skip jobs in previous analysis |
| `--matched-only` | Only output matched jobs |
| `-o, --output` | Output Excel file |
| `--json FILE` | Also save JSON results |

### Filtering Pipeline
Jobs are filtered in this order (saves AI calls):
1. **Title Exclusion** - Rejects if title contains excluded keywords
2. **Description Exclusion** - Rejects if description contains excluded keywords
3. **Must-Have Check** - Requires at least one must-have keyword
4. **AI Analysis** - Only called for jobs passing all filters

---

## Configuration (config.json)

```json
{
  "job_titles": ["Engineering Manager", "Head of Engineering", ...],
  "location": "London, UK",
  "time_range": "48h",
  "max_jobs_per_title": 50,
  "exclude_in_title": ["junior", "intern", ...],
  "exclude_in_description": ["CSCS card", ...],
  "must_have": ["team", "lead", "people management"],
  "min_score": 7,
  "ollama_model": "qwen2.5:7b",
  "ollama_url": "http://localhost:11434",
  "score_adjustments": {
    "positive": {"team": 4, "agile": 5, "leadership": 4},
    "negative": {"hardware": -5, "hands-on coding": -1}
  }
}
```

### Score Adjustments
Keywords in job descriptions adjust the AI score:
- **Positive**: Add points (e.g., "agile" +5, "team" +4)
- **Negative**: Subtract points (e.g., "hardware" -5)

Final score = AI score + adjustments (clamped to 1-10)

---

## Typical Workflows

### Daily Job Search
```bash
# Morning: Run everything for last 24 hours
python run_all.py --time-range 24h

# Open Excel to review matches
# output/analysis_YYYYMMDD.xlsx
```

### Weekly Deep Search
```bash
# Full week of jobs
python run_all.py --time-range 7d

# Or run scrape + analyze separately
python run_all.py --scrape-only --time-range 7d
python run_all.py --analyze-only --limit 200
```

### Use GUI for Browsing
```bash
# After running analysis
python job_gui.py
# Go to Results tab, load analysis_YYYYMMDD.json
```

---

## Troubleshooting

### Ollama Connection Refused
```bash
ollama serve
# Or open Ollama app from Start Menu
```

### LinkedIn Rate Limiting
The scraper uses conservative delays (2-4s between requests) and automatically:
1. Switches to sequential mode after rate limit (one job at a time)
2. Uses API endpoint which is less rate-limited
3. Retries missing descriptions via `run_all.py`

```bash
# If still hitting limits, use single worker
python linkedin_scraper.py -w 1 -a

# Retry missing descriptions after scraping
python run_all.py --retry-only
```

### Timeout Errors
```bash
python job_analyzer.py jobs.json --timeout 300 --model qwen2.5:7b
```

### Missing Descriptions
```bash
python job_scraper.py --augment jobs.json --force
```

---

## File Structure

```
.
├── run_all.py               # Unified scraper + analyzer script
├── job_gui.py               # GUI application
├── linkedin_scraper.py      # LinkedIn job scraper
├── job_scraper.py           # Fintech company scraper
├── job_analyzer.py          # AI job analyzer
├── config.json              # Configuration
├── CLAUDE.md                # Context for Claude Code
├── README.md                # This file
├── data/                    # CV and documents
│   └── your_cv.txt          # Add your CV here
├── output/                  # All output files
│   ├── linkedin_jobs_*.json
│   ├── jobs_*.json
│   ├── analysis_*.xlsx
│   └── analysis_*.json
└── archive/                 # Old/unused files
```

## Available Ollama Models

Recommended for job analysis:
- `qwen2.5:7b` - Default, good balance of speed/quality
- `llama3.1:8b` - Alternative
- `gemma2:9b` - Google model

Avoid for text-only analysis:
- `qwen3-vl:*` - Vision models (slow for text)
