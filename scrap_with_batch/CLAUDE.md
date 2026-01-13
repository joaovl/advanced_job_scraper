# Job Scraper Project Context

## Project Overview
A comprehensive job scraping and analysis system for LinkedIn job searches, with a Tkinter GUI and AI-powered job matching using Ollama LLMs.

## Main Files

### `job_gui.py`
Full Tkinter GUI application with tabs:
- **Scraper Tab**: Run LinkedIn scraper with configurable parameters
- **Analyzer Tab**: Run AI analysis on scraped jobs
- **Configuration Tab**: Manage keywords, weights, exclusions, AI model
- **Results Tab**: Browse analyzed jobs, open links, export
- **History Tab**: View command history
- **Debug Tab**: View logs and debug info

### `linkedin_scraper.py`
LinkedIn job scraper using public guest API (no auth needed):
- Searches by job title and location
- Fetches job descriptions via parallel workers
- **Incremental scraping**: Skips jobs already in JSON file
- Rate limit handling with exponential backoff
- Saves to JSON with merge strategy

Key methods:
- `load_existing_jobs()`: Load URLs from existing JSON to skip
- `scrape_jobs()`: Main scraping with duplicate detection
- `save_results()`: Merge new jobs with existing file

### `job_analyzer.py`
AI-powered job analysis using Ollama:
- Reads scraped jobs from JSON
- Sends to LLM for scoring (1-10) and decision
- **Weighted scoring**: Applies keyword adjustments to AI score
- Outputs to Excel with columns: Decision, Score, AI Score, Adjust, Score Details, etc.

Key methods:
- `calculate_score_adjustment()`: Apply positive/negative keyword weights
- `analyze_job()`: Full analysis with LLM + score adjustment

### `job_scraper.py`
CLI wrapper for LinkedIn scraper with augmentation support.

### `config.json`
Configuration file with:
- `job_titles`: List of job titles to search
- `location`: Search location (e.g., "London, UK")
- `time_range`: "24h", "48h", "week", "month"
- `exclude_in_title`: Keywords to skip in job titles
- `exclude_in_description`: Keywords to skip in descriptions
- `flag_for_review`: Keywords that flag jobs for manual review
- `must_have`: Required keywords
- `score_adjustments`: Weighted keywords
  - `positive`: Keywords that add to score (e.g., "team": 4, "agile": 5)
  - `negative`: Keywords that reduce score (e.g., "hardware": -5)
- `ollama_model`: LLM model to use (e.g., "qwen2.5:7b")
- `min_score`: Minimum score threshold

## Usage

### GUI Mode
```bash
python job_gui.py
```

### CLI Mode
```bash
# Scrape jobs
python job_scraper.py

# Analyze with defaults
python job_analyzer.py jobs_YYYYMMDD.json

# Analyze with options
python job_analyzer.py jobs.json --limit 50 --model qwen2.5:7b -o output.xlsx
```

## Weighted Scoring System
The system applies keyword-based score adjustments:
1. AI provides base score (1-10)
2. System scans title + description for keywords
3. Positive keywords add points (e.g., "team" +4)
4. Negative keywords subtract points (e.g., "hardware" -5)
5. Final score clamped to 1-10 range

Example: AI score 7 + "agile"(+5) + "hardware"(-5) = 7

## Data Files
- `data/your_cv.txt`: Your CV for job matching (create this file)
- Output: `jobs_YYYYMMDD.json` (scraped jobs)
- Output: `analysis_YYYYMMDD.xlsx` (analyzed results)

## Known Issues / Notes
- LinkedIn rate limits: Use incremental scraping to avoid re-fetching
- Ollama must be running locally on port 11434
- Archive folder contains old/unused scripts (git ignored)

## Dependencies
- requests
- openpyxl
- tkinter (built-in)
- Ollama running locally
