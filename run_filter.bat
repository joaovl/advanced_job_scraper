@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM Job Filter Runner - Windows
REM Simple one-click script to filter jobs using AI
REM
REM Usage: Double-click run_filter.bat or run from command prompt
REM ============================================================

REM ============================================================
REM CONFIGURATION - Uncomment/modify the options you want
REM ============================================================

REM --- AI Backend (choose one) ---
set "AI_BACKEND=--claude --claude-model haiku"
REM set "AI_BACKEND=--claude --claude-model sonnet"
REM set "AI_BACKEND=--ollama --model qwen2.5:7b"
REM set "AI_BACKEND=--llama-cli"

REM --- Location filter ---
set "LOCATION=-l London"
REM set "LOCATION=-l UK"
REM set "LOCATION=-l Remote"
REM set "LOCATION="

REM --- Processing options ---
set "PARALLEL=--parallel"
REM set "PARALLEL="

REM --- Limit jobs (useful for testing) ---
REM set "LIMIT=--limit 10"
REM set "LIMIT=--limit 50"
set "LIMIT="

REM --- Minimum score to match (1-10) ---
REM set "MIN_SCORE=--min-score 6"
REM set "MIN_SCORE=--min-score 8"
set "MIN_SCORE="

REM --- Run scrapers before filtering ---
REM Uncomment ONE of these to scrape first
REM set "SCRAPE_CMD=python run_pipeline.py --location London"
REM set "SCRAPE_CMD=python scrapers\workday_scraper.py --all --search London"
REM set "SCRAPE_CMD=python scrapers\playwright_scraper_v2.py --all --location London"
set "SCRAPE_CMD="

REM ============================================================
REM SCRIPT START - Don't modify below unless you know what you're doing
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo JOB FILTER RUNNER
echo ============================================================
echo.

REM Check we're in the right folder
if not exist "job_filter_ai.py" (
    echo ERROR: job_filter_ai.py not found!
    echo Make sure you're running this from the advanced_job_scraper directory
    pause
    exit /b 1
)
echo [OK] Correct directory: %CD%

REM Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found! Please install Python 3.8+
    pause
    exit /b 1
)
echo [OK] Python found

REM Check/activate virtual environment
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Virtual environment activated
) else (
    echo WARNING: No venv found. Creating one...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    echo [OK] Virtual environment created and dependencies installed
)

REM Check Claude CLI (if using Claude backend)
echo %AI_BACKEND% | findstr /C:"--claude" >nul
if not errorlevel 1 (
    where claude >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Claude CLI not found!
        echo Install with: npm install -g @anthropic-ai/claude-code
        pause
        exit /b 1
    )
    echo [OK] Claude CLI found
)

REM Check CV file
if not exist "N8n\data\joaocv.txt" (
    if not exist "N8n\config.json" (
        echo WARNING: CV file not found at N8n\data\joaocv.txt
        echo AI scoring will be less accurate without a CV
    )
)

REM Check jobs file
if not exist "N8n\fintech_jobs.json" (
    echo WARNING: No jobs file found. You may need to run scrapers first.
)

echo.
echo ============================================================
echo CONFIGURATION
echo ============================================================
echo Backend: %AI_BACKEND%
if defined LOCATION (echo Location: %LOCATION%) else (echo Location: ^(all^))
if defined PARALLEL (echo Parallel: yes) else (echo Parallel: no)
if defined LIMIT (echo Limit: %LIMIT%) else (echo Limit: ^(all jobs^))
echo.

REM Run scrapers if configured
if defined SCRAPE_CMD (
    echo ============================================================
    echo RUNNING SCRAPERS
    echo ============================================================
    echo Command: %SCRAPE_CMD%
    echo.
    %SCRAPE_CMD%
    echo.
)

REM Build and run the filter command
set "FILTER_CMD=python job_filter_ai.py %AI_BACKEND% %LOCATION% %PARALLEL% %LIMIT% %MIN_SCORE%"

echo ============================================================
echo RUNNING AI FILTER
echo ============================================================
echo Command: %FILTER_CMD%
echo.

%FILTER_CMD%

echo.
echo ============================================================
echo DONE!
echo ============================================================
echo Check the output\ folder for results (Excel and JSON files)
echo.
pause
