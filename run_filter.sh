#!/bin/bash
#
# Job Filter Runner - Linux/macOS
# Simple one-click script to filter jobs using AI
#
# Usage: ./run_filter.sh
#

set -e

# ============================================================
# CONFIGURATION - Uncomment/modify the options you want
# ============================================================

# --- AI Backend (choose one) ---
AI_BACKEND="--claude --claude-model haiku"
# AI_BACKEND="--claude --claude-model sonnet"      # More accurate, slower
# AI_BACKEND="--ollama --model qwen2.5:7b"         # Local LLM (requires ollama serve)
# AI_BACKEND="--llama-cli"                          # Local llama.cpp

# --- Location filter ---
LOCATION="-l London"
# LOCATION="-l UK"
# LOCATION="-l Remote"
# LOCATION=""                                       # No location filter (all jobs)

# --- Processing options ---
PARALLEL="--parallel"
# PARALLEL=""                                       # Sequential processing

# --- Limit jobs (useful for testing) ---
# LIMIT="--limit 10"
# LIMIT="--limit 50"
LIMIT=""                                            # Process all jobs

# --- Minimum score to match (1-10) ---
# MIN_SCORE="--min-score 6"
# MIN_SCORE="--min-score 8"
MIN_SCORE=""                                        # Use default (7)

# --- Run scrapers before filtering ---
# Uncomment ONE of these to scrape first, or leave all commented to filter existing jobs
# SCRAPE_CMD="python run_pipeline.py --location London"           # All scrapers
# SCRAPE_CMD="python scrapers/workday_scraper.py --all --search London"  # Workday only
# SCRAPE_CMD="python scrapers/playwright_scraper_v2.py --all --location London"  # Big tech only
SCRAPE_CMD=""

# ============================================================
# SCRIPT START - Don't modify below unless you know what you're doing
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "JOB FILTER RUNNER"
echo "============================================================"
echo ""

# Check we're in the right folder
if [ ! -f "job_filter_ai.py" ]; then
    echo "ERROR: job_filter_ai.py not found!"
    echo "Make sure you're running this from the advanced_job_scraper directory"
    exit 1
fi
echo "[OK] Correct directory: $SCRIPT_DIR"

# Check Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "ERROR: Python not found! Please install Python 3.8+"
    exit 1
fi
PYTHON_CMD=$(command -v python3 || command -v python)
echo "[OK] Python found: $PYTHON_CMD"

# Check/activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "[OK] Virtual environment activated"
else
    echo "WARNING: No venv found. Creating one..."
    $PYTHON_CMD -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    echo "[OK] Virtual environment created and dependencies installed"
fi

# Check Claude CLI (if using Claude backend)
if [[ "$AI_BACKEND" == *"--claude"* ]]; then
    if ! command -v claude &> /dev/null; then
        echo "ERROR: Claude CLI not found!"
        echo "Install with: npm install -g @anthropic-ai/claude-code"
        exit 1
    fi
    echo "[OK] Claude CLI found"
fi

# Check Ollama (if using Ollama backend)
if [[ "$AI_BACKEND" == *"--ollama"* ]]; then
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "ERROR: Ollama not running!"
        echo "Start with: ollama serve"
        exit 1
    fi
    echo "[OK] Ollama running"
fi

# Check CV file
if [ ! -f "N8n/data/joaocv.txt" ] && [ ! -f "N8n/config.json" ]; then
    echo "WARNING: CV file not found at N8n/data/joaocv.txt"
    echo "AI scoring will be less accurate without a CV"
fi

# Check jobs file
if [ ! -f "N8n/fintech_jobs.json" ]; then
    echo "WARNING: No jobs file found. You may need to run scrapers first."
fi

echo ""
echo "============================================================"
echo "CONFIGURATION"
echo "============================================================"
echo "Backend: $AI_BACKEND"
echo "Location: ${LOCATION:-(all)}"
echo "Parallel: ${PARALLEL:-no}"
echo "Limit: ${LIMIT:-(all jobs)}"
echo ""

# Run scrapers if configured
if [ -n "$SCRAPE_CMD" ]; then
    echo "============================================================"
    echo "RUNNING SCRAPERS"
    echo "============================================================"
    echo "Command: $SCRAPE_CMD"
    echo ""
    eval "$SCRAPE_CMD"
    echo ""
fi

# Build and run the filter command
FILTER_CMD="python job_filter_ai.py $AI_BACKEND $LOCATION $PARALLEL $LIMIT $MIN_SCORE"

echo "============================================================"
echo "RUNNING AI FILTER"
echo "============================================================"
echo "Command: $FILTER_CMD"
echo ""

eval "$FILTER_CMD"

echo ""
echo "============================================================"
echo "DONE!"
echo "============================================================"
echo "Check the output/ folder for results (Excel and JSON files)"
