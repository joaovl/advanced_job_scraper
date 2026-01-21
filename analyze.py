#!/usr/bin/env python3
"""
AI Job Analyzer - Score jobs against your CV using AI.

This script reads scraped jobs and uses AI (Claude or Ollama) to
score and filter them against your CV/preferences.

Usage:
    # Analyze latest with defaults (Claude Opus, parallel)
    python analyze.py

    # Specific file
    python analyze.py --input output/linkedin_jobs_20260121.json

    # Different model
    python analyze.py --model haiku

    # Ollama backend
    python analyze.py --backend ollama --model qwen2.5:7b
"""

import json
import argparse
import requests
import sys
import subprocess
import os
import re
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any

# Check required dependencies upfront
def check_dependencies():
    """Check that all required Python packages are installed."""
    missing = []

    try:
        import openpyxl
    except ImportError:
        missing.append("openpyxl")

    try:
        import requests
    except ImportError:
        missing.append("requests")

    if missing:
        print("=" * 60)
        print("ERROR: Missing required Python packages")
        print("=" * 60)
        print(f"\nMissing packages: {', '.join(missing)}")
        print("\nTo install:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)

check_dependencies()

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

# Sensible defaults
DEFAULT_BACKEND = "claude"
DEFAULT_MODEL = "opus"  # Best quality for job matching
DEFAULT_MIN_SCORE = 7
DEFAULT_WORKERS = max(1, (os.cpu_count() or 4) - 2)
DEFAULT_CV_PATH = BASE_DIR / "data" / "cv.txt"


def load_config() -> dict:
    """Load config from config.json or use defaults."""
    config_path = BASE_DIR / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load config.json: {e}")
    return {}


def load_cv(cv_path: Path = None) -> str:
    """Load CV content from file."""
    paths_to_try = [
        cv_path,
        DEFAULT_CV_PATH,
        BASE_DIR / "N8n" / "data" / "your_cv.txt",  # Legacy path
    ]

    for path in paths_to_try:
        if path and path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        print(f"CV: Loaded from {path} ({len(content)} chars)")
                        return content
            except:
                pass

    print("Warning: Could not load CV file. AI scoring will be less accurate.")
    print(f"Expected location: {DEFAULT_CV_PATH}")
    return ""


def get_latest_jobs_file() -> Path:
    """Find most recent jobs JSON in output/"""
    if not OUTPUT_DIR.exists():
        raise FileNotFoundError(f"Output directory not found: {OUTPUT_DIR}")

    # Look for job files (not analysis files)
    json_files = []
    for f in OUTPUT_DIR.glob("*.json"):
        name = f.name.lower()
        if "analysis" in name or "filtered" in name or "shortlist" in name:
            continue
        if "master_jobs" in name or "linkedin_jobs" in name or name.endswith("_jobs.json"):
            json_files.append(f)

    # Also check for any JSON that contains job data
    if not json_files:
        for f in OUTPUT_DIR.glob("*.json"):
            if "analysis" not in f.name.lower():
                json_files.append(f)

    if not json_files:
        raise FileNotFoundError(f"No job files found in {OUTPUT_DIR}")

    return max(json_files, key=lambda f: f.stat().st_mtime)


def normalize_jobs(data: Any) -> List[Dict]:
    """Normalize any scraper output to common format."""
    # Handle nested Workday format
    if isinstance(data, dict):
        if "jobs" in data:
            jobs = data["jobs"]
        else:
            # Single job dict
            jobs = [data]
    else:
        jobs = data

    normalized = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        normalized.append({
            "title": job.get("title", "Unknown"),
            "company": job.get("company", "Unknown"),
            "location": job.get("location", ""),
            "url": job.get("url", job.get("apply_link", "")),
            "description": job.get("description", ""),
            "source": job.get("source", "Unknown"),
        })
    return normalized


def load_jobs(input_file: Path = None) -> List[Dict]:
    """Load jobs from JSON file."""
    if input_file is None:
        input_file = get_latest_jobs_file()

    print(f"Loading jobs from: {input_file}")

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    jobs = normalize_jobs(data)
    print(f"Loaded {len(jobs)} jobs")
    return jobs


def check_claude() -> bool:
    """Check if Claude CLI is available."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"Claude CLI: {result.stdout.strip()}")
            return True
        return False
    except FileNotFoundError:
        print("Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code")
        return False
    except Exception as e:
        print(f"Claude CLI check error: {e}")
        return False


def check_ollama(url: str, model: str) -> bool:
    """Check if Ollama is running and model is available."""
    try:
        response = requests.get(f"{url}/api/tags", timeout=5)
        if response.status_code == 200:
            models = [m['name'] for m in response.json().get('models', [])]
            if model in models or any(model in m for m in models):
                print(f"Ollama: OK (model: {model})")
                return True
            print(f"Model '{model}' not found. Available: {', '.join(models[:5])}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Cannot connect to Ollama at {url}")
        print("Start Ollama with: ollama serve")
        return False
    except Exception as e:
        print(f"Ollama error: {e}")
        return False


def quick_filter(job: dict, config: dict) -> tuple:
    """Quick keyword-based filtering before AI.

    Uses three filtering mechanisms:
    1. Exact exclusion keywords in title
    2. Exact exclusion keywords in description
    3. Keyword scoring (positive/negative) - reject if score is very negative
    """
    filters = config.get("filters", {})
    exclude_title = filters.get("exclude_in_title", [])
    exclude_desc = filters.get("exclude_in_description", [])
    positive_keywords = filters.get("positive_keywords", {})
    negative_keywords = filters.get("negative_keywords", {})

    title_lower = job.get('title', '').lower()
    desc_lower = job.get('description', '').lower()
    full_text = f"{title_lower} {desc_lower}"

    # Step 1: Check exclusion keywords in title (using word boundaries)
    # Word boundaries prevent "Senior Engineer" from matching "Senior Engineering Manager"
    for kw in exclude_title:
        kw_lower = kw.lower()
        # Use word boundary matching for all keywords
        pattern = r'\b' + re.escape(kw_lower) + r'\b'
        if re.search(pattern, title_lower):
            return False, f"Title contains: {kw}"

    # Step 2: Check exclusion keywords in description (using word boundaries)
    for kw in exclude_desc:
        kw_lower = kw.lower()
        pattern = r'\b' + re.escape(kw_lower) + r'\b'
        if re.search(pattern, desc_lower):
            return False, f"Description contains: {kw}"

    # Step 3: Keyword scoring - reject jobs with very negative scores
    # This catches jobs that have multiple red flags even if no single exclusion keyword
    keyword_score = 0
    negative_matches = []
    positive_matches = []

    for kw, score in negative_keywords.items():
        kw_lower = kw.lower()
        if kw_lower in full_text:
            keyword_score += score
            if score <= -3:  # Track significant negatives
                negative_matches.append(f"{kw}({score})")

    for kw, score in positive_keywords.items():
        kw_lower = kw.lower()
        if kw_lower in full_text:
            keyword_score += score
            if score >= 3:  # Track significant positives
                positive_matches.append(f"{kw}(+{score})")

    # Reject if keyword score is very negative (threshold: -8)
    # This catches jobs with multiple red flags like "hardware" + "manufacturing" + "embedded"
    REJECT_THRESHOLD = -8
    if keyword_score <= REJECT_THRESHOLD:
        return False, f"Keyword score {keyword_score}: {', '.join(negative_matches[:3])}"

    return True, ""


def build_prompt(job: dict, cv: str, min_score: int) -> str:
    """Build the AI scoring prompt."""
    return f"""You are a job matching expert. Analyze if this job matches the candidate's target role criteria.

TARGET ROLES:
- Titles: Head of Engineering, Director of Engineering, VP Engineering, Head of Software Engineering, Director of Software Engineering, Senior Engineering Manager, Engineering Manager
- Scope: Any people management role in software engineering - single team is fine, manager-of-managers is a bonus
- Reports to: VP, CTO, CEO, C-level, or senior leadership
- Focus: People leadership, team building, hiring, delivery, stakeholder management, engineering culture

POSITIVE SIGNALS (score 7+ if title matches and has these):
- People management, team leadership, hiring responsibility
- Software product development, SaaS, platform engineering
- CI/CD, DevOps, release management, SDLC ownership
- Agile, scrum, engineering process improvement
- Cross-functional collaboration with Product, Design, Delivery
- Manager of managers, multiple teams (bonus - score 9-10)
- Large team (25+ engineers) (bonus - score 9-10)
- Distributed/global engineering teams (bonus)

HARD REJECT (automatic score 1-4):
- "Hands-on coding required", "player-coach", "contributing code daily", "50%+ coding"
- Titles: Team Lead, Tech Lead, Staff Engineer, Principal Engineer, IC roles
- Non-software: QA Operations, IT Support, Unified Communications, ITIL, ServiceNow
- Non-software: Pharma validation, medical device, Network Security, Infrastructure (non-cloud)
- Contract, interim, or freelance roles (NOT permanent)
- IR35 mentioned, day rate instead of salary
- Part-time roles
- Wrong domain entirely: hospitality, construction, mechanical, civil engineering

SOFT CONCERNS (note in reasons but still score 7 if title matches):
- Team size unclear or not mentioned - STILL SCORE 7 if title is good
- Scope unclear - STILL SCORE 7 if title and company look relevant
- Small team (5-15 engineers) - STILL SCORE 7, single team management is acceptable
- "Hands-on" mentioned casually without coding requirement - STILL SCORE 7, note concern
- Early-stage startup (10-50 employees) - STILL SCORE 7 unless clearly IC role
- Consumer scale / "millions of users" - STILL SCORE 7, note as soft concern (candidate prefers B2B but consumer is acceptable)

CANDIDATE BACKGROUND:
{cv if cv else "No CV provided - use general engineering manager criteria"}

JOB TO ANALYZE:
Title: {job.get('title', 'Unknown')}
Company: {job.get('company', 'Unknown')}
Location: {job.get('location', 'Unknown')}
Description: {job.get('description', '')[:2500]}

SCORING GUIDE:
- 9-10: Perfect - leadership title + large scope + manager-of-managers + no concerns
- 7-8: Good match - leadership title + people management + software domain. DEFAULT TO 7 if title is good.
- 5-6: ONLY if specific concern exists. You MUST state what the concern is.
- 1-4: Hard reject - wrong domain entirely, contract role, IC role, or requires relocation

CRITICAL RULES:
1. "Hands-on" alone is NOT a rejection. Only reject if it says "hands-on CODING", "writing code", "50% coding", or similar.
   - "Hands-on leader" = OK (score 7) - means involved, not coding
   - "Hands-on engineering leader" = OK (score 7) - leadership style
   - "Hands-on coding required" = Reject (score 4)
2. Single team / small team (5-15 engineers) = Score 7 minimum. This is acceptable.
3. Team size not mentioned = Score 7. Do not penalize for missing information.
4. Unclear scope = Score 7. Give benefit of the doubt.
5. If title matches (Head/Director/VP of Engineering/Software) and it's software, score 7 minimum.

REASONS FORMAT - You MUST be specific:
- If scoring 7+: State why it's a good match
- If scoring 5-6: State the SPECIFIC concern (e.g., "requires hands-on coding per job description", "marketing domain not software")
- If scoring 1-4: State the hard reject reason (e.g., "contract role", "IT support not software", "relocation required")

CRITICAL - SCORE MUST MATCH REASONS:
If your reasons sound positive, your score MUST be 7+. Examples:

WRONG: {{"score": 5, "reasons": ["Title matches target roles", "B2B SaaS good fit"]}}
RIGHT: {{"score": 7, "reasons": ["Title matches target roles", "B2B SaaS good fit"]}}

WRONG: {{"score": 6, "reasons": ["Engineering Manager with people management", "Good domain"]}}
RIGHT: {{"score": 7, "reasons": ["Engineering Manager with people management", "Good domain"]}}

WRONG: {{"score": 5, "reasons": ["Head of Engineering reports to CEO", "Enterprise legal tech"]}}
RIGHT: {{"score": 7, "reasons": ["Head of Engineering reports to CEO", "Enterprise legal tech"]}}

Only score below 7 if you state a SPECIFIC NEGATIVE concern in the reasons.

Return ONLY a JSON object (no markdown, no explanation):
{{"score": <1-10>, "match": <true if score >= {min_score} else false>, "reasons": ["reason1", "reason2"]}}"""


def score_with_claude(prompt: str, model: str, max_retries: int = 3) -> str:
    """Run Claude CLI with the given prompt and return the response."""
    import tempfile
    import time
    import random

    for attempt in range(max_retries):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            cmd = ["claude", "-p", prompt, "--output-format", "text"]

            if model in ['haiku', 'sonnet', 'opus']:
                cmd.extend(["--model", model])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=90,
                encoding='utf-8'
            )

            Path(prompt_file).unlink(missing_ok=True)

            if result.returncode != 0:
                error_msg = result.stderr[:200] if result.stderr else "Unknown error"
                if "rate" in error_msg.lower() or "limit" in error_msg.lower() or "overloaded" in error_msg.lower():
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2 + random.uniform(0, 1)
                        time.sleep(wait_time)
                        continue
                raise Exception(f"Claude CLI error: {error_msg}")

            return result.stdout

        except subprocess.TimeoutExpired:
            Path(prompt_file).unlink(missing_ok=True)
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise Exception("Claude CLI timeout (90s)")
        except Exception as e:
            Path(prompt_file).unlink(missing_ok=True)
            if attempt < max_retries - 1 and ("rate" in str(e).lower() or "overloaded" in str(e).lower()):
                wait_time = (attempt + 1) * 2 + random.uniform(0, 1)
                time.sleep(wait_time)
                continue
            raise e

    raise Exception("Max retries exceeded")


def score_with_ollama(prompt: str, url: str, model: str) -> str:
    """Run Ollama with the given prompt and return the response."""
    response = requests.post(
        f"{url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3}
        },
        timeout=120
    )
    response.raise_for_status()
    return response.json().get('response', '')


def check_positive_reasons(reasons: list, score: int) -> tuple:
    """Check if reasons sound positive but score is low. Returns (adjusted_score, was_adjusted)."""
    if score >= 7 or score == 0:
        return score, False

    # Positive indicators that suggest the job should pass
    positive_phrases = [
        "matches target", "title matches", "good match", "strong match",
        "aligns well", "good fit", "good domain", "relevant domain",
        "people management", "people leadership", "leadership clear",
        "reports to cto", "reports to ceo", "reports to vp",
        "b2b saas", "enterprise software", "software engineering"
    ]

    # Negative indicators that justify a low score
    negative_phrases = [
        "hands-on coding", "coding required", "writing code", "build",
        "contract role", "part-time", "relocation", "not software",
        "it support", "infrastructure", "dba", "database engineering",
        "marketing", "martech", "adtech", "trading systems", "crypto",
        "unified communications", "poor fit", "outside background",
        "requires expertise in", "specific stack"
    ]

    reasons_text = " ".join(reasons).lower()

    has_positive = any(phrase in reasons_text for phrase in positive_phrases)
    has_negative = any(phrase in reasons_text for phrase in negative_phrases)

    # If reasons are positive and no clear negative, bump to 7
    if has_positive and not has_negative:
        return 7, True

    return score, False


def score_job_with_ai(job: dict, cv: str, config: dict) -> dict:
    """Use AI to score a job against the CV."""
    analysis_config = config.get("analysis", {})
    min_score = analysis_config.get("min_score", DEFAULT_MIN_SCORE)
    backend = analysis_config.get("backend", DEFAULT_BACKEND)
    model = analysis_config.get("model", DEFAULT_MODEL)
    ollama_url = analysis_config.get("ollama_url", "http://localhost:11434")

    prompt = build_prompt(job, cv, min_score)

    try:
        if backend == "claude":
            result_text = score_with_claude(prompt, model)
        else:
            result_text = score_with_ollama(prompt, ollama_url, model)

        # Extract JSON from response
        match = re.search(r'\{[^{}]*\}', result_text)
        if match:
            result = json.loads(match.group())
            score = int(result.get('score', 0))
            reasons = result.get('reasons', [])

            # Post-process: check for positive reasons with low score
            original_score = score
            score, was_adjusted = check_positive_reasons(reasons, score)

            return {
                "score": score,
                "original_score": original_score if was_adjusted else None,
                "adjusted": was_adjusted,
                "match": score >= min_score,
                "reasons": reasons
            }
    except Exception as e:
        return {"score": 0, "original_score": None, "adjusted": False, "match": False, "reasons": [f"AI error: {str(e)}"]}

    return {"score": 0, "original_score": None, "adjusted": False, "match": False, "reasons": ["Could not parse AI response"]}


def filter_jobs(jobs: list, config: dict, cv: str, limit: int = None, parallel: bool = True, workers: int = None) -> list:
    """Filter jobs using quick filters and AI scoring."""
    analysis_config = config.get("analysis", {})
    min_score = analysis_config.get("min_score", DEFAULT_MIN_SCORE)

    results = []
    matched = 0
    rejected_title = 0      # Rejected by exclude_in_title
    rejected_desc = 0       # Rejected by exclude_in_description
    rejected_keywords = 0   # Rejected by keyword score
    rejected_ai = 0

    jobs_to_process = jobs[:limit] if limit else jobs
    total = len(jobs_to_process)

    print(f"\nProcessing {total} jobs...")
    print("-" * 60)

    # Step 1: Quick filter (fast, sequential)
    jobs_for_ai = []
    for i, job in enumerate(jobs_to_process):
        title = job.get('title', 'Unknown')[:50]

        passed, reason = quick_filter(job, config)

        if not passed:
            results.append({
                **job,
                "decision": "REJECTED",
                "score": 0,
                "reason": reason
            })
            # Track rejection type for stats
            if reason.startswith("Title contains"):
                rejected_title += 1
            elif reason.startswith("Description contains"):
                rejected_desc += 1
            elif reason.startswith("Keyword score"):
                rejected_keywords += 1
            print(f"[{i+1}/{total}] SKIP: {title} - {reason}")
        else:
            jobs_for_ai.append((i, job))

    # Step 2: AI scoring
    if not jobs_for_ai:
        print("No jobs passed quick filter.")
    elif parallel and len(jobs_for_ai) > 1:
        num_workers = workers or DEFAULT_WORKERS
        print(f"\nScoring {len(jobs_for_ai)} jobs with AI in PARALLEL ({num_workers} workers)...")

        def score_single_job(item):
            idx, job = item
            ai_result = score_job_with_ai(job, cv, config)
            return idx, job, ai_result

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(score_single_job, item): item for item in jobs_for_ai}
            completed = 0

            for future in as_completed(futures):
                completed += 1
                try:
                    idx, job, ai_result = future.result()
                    title = job.get('title', 'Unknown')[:40]
                    company = job.get('company', 'Unknown')[:15]

                    score = ai_result.get('score', 0)
                    original_score = ai_result.get('original_score')
                    adjusted = ai_result.get('adjusted', False)
                    is_match = ai_result.get('match', False) and score >= min_score
                    reasons = ai_result.get('reasons', [])

                    # Build adjustment note for display
                    adj_note = f" (was {original_score})" if adjusted else ""
                    adj_flag = "*" if adjusted else " "

                    if is_match:
                        results.append({
                            **job,
                            "decision": "MATCHED",
                            "score": score,
                            "original_score": original_score,
                            "adjusted": adjusted,
                            "reason": "; ".join(reasons[:2])
                        })
                        matched += 1
                        print(f"[{completed:3}/{len(jobs_for_ai)}] MATCH {adj_flag}{score:2}{adj_note} {company:15} {title}")
                    else:
                        results.append({
                            **job,
                            "decision": "REJECTED",
                            "score": score,
                            "original_score": original_score,
                            "adjusted": adjusted,
                            "reason": "; ".join(reasons[:2])
                        })
                        rejected_ai += 1
                        print(f"[{completed:3}/{len(jobs_for_ai)}] REJECT{adj_flag}{score:2}{adj_note} {company:15} {title}")

                except Exception as e:
                    idx, job = futures[future]
                    title = job.get('title', 'Unknown')[:40]
                    results.append({
                        **job,
                        "decision": "REJECTED",
                        "score": 0,
                        "reason": f"AI error: {e}"
                    })
                    rejected_ai += 1
                    print(f"[{completed:3}/{len(jobs_for_ai)}] ERROR  -- {title[:50]}")
    else:
        # Sequential AI scoring
        for i, (idx, job) in enumerate(jobs_for_ai):
            title = job.get('title', 'Unknown')[:50]
            company = job.get('company', 'Unknown')[:20]

            print(f"[{i+1}/{len(jobs_for_ai)}] AI: {title} @ {company}...", end=" ", flush=True)
            ai_result = score_job_with_ai(job, cv, config)

            score = ai_result.get('score', 0)
            original_score = ai_result.get('original_score')
            adjusted = ai_result.get('adjusted', False)
            is_match = ai_result.get('match', False) and score >= min_score
            reasons = ai_result.get('reasons', [])

            adj_note = f" (was {original_score})" if adjusted else ""

            if is_match:
                results.append({
                    **job,
                    "decision": "MATCHED",
                    "score": score,
                    "original_score": original_score,
                    "adjusted": adjusted,
                    "reason": "; ".join(reasons[:2])
                })
                matched += 1
                print(f"MATCH (score {score}{adj_note})")
            else:
                results.append({
                    **job,
                    "decision": "REJECTED",
                    "score": score,
                    "original_score": original_score,
                    "adjusted": adjusted,
                    "reason": "; ".join(reasons[:2])
                })
                rejected_ai += 1
                print(f"REJECT (score {score}{adj_note})")

    print("-" * 60)
    total_quick = rejected_title + rejected_desc + rejected_keywords
    print(f"\nPre-filter summary (saved {total_quick} AI calls):")
    print(f"  - Title exclusions:    {rejected_title}")
    print(f"  - Description exclusions: {rejected_desc}")
    print(f"  - Keyword score < -8:  {rejected_keywords}")
    print(f"\nFinal results: {matched} matched, {total_quick} pre-filtered, {rejected_ai} AI-rejected")

    # Sort by score descending
    results.sort(key=lambda x: (-1 if x['decision'] == 'MATCHED' else 0, -x.get('score', 0)))

    return results


def create_excel_report(results: list, output_file: Path):
    """Create comprehensive Excel report with all job details."""
    wb = openpyxl.Workbook()

    # Styles
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    match_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    reject_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    skip_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    link_font = Font(color="0563C1", underline="single")
    wrap_alignment = Alignment(vertical="top", wrap_text=True)
    center_alignment = Alignment(horizontal="center", vertical="top")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    headers = ["Score", "Decision", "Company", "Job Title", "Location",
               "Rejection Reason", "Apply Link"]
    col_widths = [14, 12, 25, 45, 30, 60, 12]

    # Style for adjusted scores
    adjusted_fill = PatternFill(start_color="B4C6E7", end_color="B4C6E7", fill_type="solid")  # Light blue

    def setup_sheet(ws, title, jobs_list):
        """Setup a worksheet with jobs data."""
        ws.title = title

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_alignment
            cell.border = thin_border

        ws.freeze_panes = "A2"

        for row_idx, job in enumerate(jobs_list, 2):
            decision = job.get('decision', 'UNKNOWN')
            score = job.get('score', 0)
            original_score = job.get('original_score')
            adjusted = job.get('adjusted', False)

            if decision == 'MATCHED':
                row_fill = match_fill
            elif score == 0:
                row_fill = skip_fill
            else:
                row_fill = reject_fill

            # Score - show adjustment if applicable
            if adjusted and original_score is not None:
                score_display = f"{score} (was {original_score})"
                score_fill = adjusted_fill  # Light blue for adjusted
            else:
                score_display = str(score)
                score_fill = row_fill

            cell = ws.cell(row=row_idx, column=1, value=score_display)
            cell.fill = score_fill
            cell.border = thin_border
            cell.alignment = center_alignment

            # Decision
            cell = ws.cell(row=row_idx, column=2, value=decision)
            cell.fill = row_fill
            cell.border = thin_border
            cell.alignment = center_alignment

            # Company
            cell = ws.cell(row=row_idx, column=3, value=job.get('company', ''))
            cell.fill = row_fill
            cell.border = thin_border
            cell.alignment = wrap_alignment

            # Job Title
            cell = ws.cell(row=row_idx, column=4, value=job.get('title', ''))
            cell.fill = row_fill
            cell.border = thin_border
            cell.alignment = wrap_alignment

            # Location
            cell = ws.cell(row=row_idx, column=5, value=job.get('location', ''))
            cell.fill = row_fill
            cell.border = thin_border
            cell.alignment = wrap_alignment

            # Rejection Reason
            cell = ws.cell(row=row_idx, column=6, value=job.get('reason', ''))
            cell.fill = row_fill
            cell.border = thin_border
            cell.alignment = wrap_alignment

            # Apply Link (clickable)
            url = job.get('url', '')
            cell = ws.cell(row=row_idx, column=7, value="Apply" if url else "")
            if url:
                cell.hyperlink = url
                cell.font = link_font
            cell.fill = row_fill
            cell.border = thin_border
            cell.alignment = center_alignment

        for col, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = width

        return len(jobs_list)

    # Sheet 1: All Jobs
    ws_all = wb.active
    all_sorted = sorted(results, key=lambda x: (-x.get('score', 0), x.get('company', '')))
    count_all = setup_sheet(ws_all, "All Jobs", all_sorted)

    # Sheet 2: Matched Jobs Only
    ws_matched = wb.create_sheet()
    matched = [j for j in results if j.get('decision') == 'MATCHED']
    matched_sorted = sorted(matched, key=lambda x: (-x.get('score', 0), x.get('company', '')))
    count_matched = setup_sheet(ws_matched, "Matched", matched_sorted)

    # Sheet 3: Rejected by AI
    ws_rejected = wb.create_sheet()
    rejected_ai = [j for j in results if j.get('decision') == 'REJECTED' and j.get('score', 0) > 0]
    rejected_sorted = sorted(rejected_ai, key=lambda x: (-x.get('score', 0), x.get('company', '')))
    count_rejected = setup_sheet(ws_rejected, "AI Rejected", rejected_sorted)

    # Sheet 4: Quick-filtered
    ws_skipped = wb.create_sheet()
    skipped = [j for j in results if j.get('score', 0) == 0]
    count_skipped = setup_sheet(ws_skipped, "Quick Filtered", skipped)

    # Sheet 5: Summary
    ws_summary = wb.create_sheet("Summary")
    ws_summary.cell(row=1, column=1, value="Category").font = header_font
    ws_summary.cell(row=1, column=1).fill = header_fill
    ws_summary.cell(row=1, column=2, value="Count").font = header_font
    ws_summary.cell(row=1, column=2).fill = header_fill

    # Count adjusted scores
    count_adjusted = len([j for j in results if j.get('adjusted', False)])

    summary_data = [
        ("Total Jobs Processed", count_all),
        ("Matched (Recommended)", count_matched),
        ("AI Rejected", count_rejected),
        ("Quick Filtered (Keywords)", count_skipped),
        ("Score Auto-Adjusted", count_adjusted),
    ]

    for row_idx, (label, count) in enumerate(summary_data, 2):
        ws_summary.cell(row=row_idx, column=1, value=label)
        ws_summary.cell(row=row_idx, column=2, value=count)

    ws_summary.column_dimensions['A'].width = 35
    ws_summary.column_dimensions['B'].width = 10

    wb.save(output_file)
    print(f"Excel report saved: {output_file}")
    return count_matched


def save_results(results: list, output_file: Path):
    """Save results to JSON, shortlist JSON, and Excel report."""
    # Save full results JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Create shortlist JSON (matched only)
    shortlist = [r for r in results if r['decision'] == 'MATCHED']
    shortlist_file = output_file.with_name(output_file.stem + '_shortlist.json')

    with open(shortlist_file, 'w', encoding='utf-8') as f:
        json.dump(shortlist, f, indent=2, ensure_ascii=False)

    # Create Excel report
    excel_file = output_file.with_suffix('.xlsx')
    create_excel_report(results, excel_file)

    print(f"\nSaved {len(results)} results to {output_file}")
    print(f"Saved {len(shortlist)} shortlisted jobs to {shortlist_file}")

    # Print shortlist summary
    if shortlist:
        print("\n" + "=" * 60)
        print("SHORTLISTED JOBS")
        print("=" * 60)
        for job in shortlist[:15]:
            print(f"\n[Score {job.get('score', 0)}] {job.get('title', 'Unknown')}")
            print(f"  Company: {job.get('company', 'Unknown')}")
            print(f"  Location: {job.get('location', 'Unknown')}")
            print(f"  URL: {job.get('url', '')}")
            if job.get('reason'):
                print(f"  Why: {job.get('reason', '')[:80]}")

        if len(shortlist) > 15:
            print(f"\n... and {len(shortlist) - 15} more jobs")


def main():
    parser = argparse.ArgumentParser(
        description="AI Job Analyzer - Score jobs against your CV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Analyze latest with defaults (Claude Opus, parallel)
    python analyze.py

    # Specific file
    python analyze.py --input output/linkedin_jobs_20260121.json

    # Different model
    python analyze.py --model haiku

    # Ollama backend
    python analyze.py --backend ollama --model qwen2.5:7b

    # Parallel with custom worker count
    python analyze.py --workers 8
        """
    )

    # Input/Output
    parser.add_argument("--input", "-i", help="Input JSON file (default: latest in output/)")
    parser.add_argument("--output", "-o", help="Output filename prefix")
    parser.add_argument("--cv", default=str(DEFAULT_CV_PATH),
                        help=f"Path to CV text file (default: {DEFAULT_CV_PATH})")

    # AI Backend
    parser.add_argument("--backend", "-b", default=DEFAULT_BACKEND,
                        choices=["claude", "ollama"],
                        help=f"AI backend (default: {DEFAULT_BACKEND})")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--ollama-url", default="http://localhost:11434",
                        help="Ollama URL (default: http://localhost:11434)")

    # Processing options
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE,
                        help=f"Minimum score to match (default: {DEFAULT_MIN_SCORE})")
    parser.add_argument("--workers", "-w", type=int, default=DEFAULT_WORKERS,
                        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})")
    parser.add_argument("--parallel", "-p", action="store_true", default=True,
                        help="Score jobs in parallel (default: True)")
    parser.add_argument("--sequential", "-s", action="store_true",
                        help="Score jobs sequentially (disables parallel)")
    parser.add_argument("--limit", "-n", type=int, help="Limit number of jobs to process")

    args = parser.parse_args()

    print("=" * 60)
    print("AI JOB ANALYZER")
    print("=" * 60)

    # Load config
    config = load_config()

    # Build analysis config from args and file
    analysis_config = config.get("analysis", {})
    analysis_config["backend"] = args.backend
    analysis_config["model"] = args.model
    analysis_config["min_score"] = args.min_score
    analysis_config["ollama_url"] = args.ollama_url
    config["analysis"] = analysis_config

    print(f"Backend: {args.backend}")
    print(f"Model: {args.model}")
    print(f"Min score: {args.min_score}")
    print(f"Workers: {args.workers}")

    # Check AI backend
    if args.backend == "claude":
        if not check_claude():
            print("\nMake sure Claude CLI is installed and configured")
            sys.exit(1)
    else:
        if not check_ollama(args.ollama_url, args.model):
            print("\nTo install a model: ollama pull qwen2.5:7b")
            sys.exit(1)

    # Load CV
    cv = load_cv(Path(args.cv) if args.cv else None)

    # Load jobs
    try:
        input_file = Path(args.input) if args.input else None
        jobs = load_jobs(input_file)
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        print("Run 'python run.py' first to scrape jobs.")
        sys.exit(1)

    if not jobs:
        print("No jobs to analyze.")
        sys.exit(1)

    # Filter jobs
    parallel = args.parallel and not args.sequential
    results = filter_jobs(jobs, config, cv, limit=args.limit, parallel=parallel, workers=args.workers)

    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_name = f"{args.backend}_{args.model}".replace(":", "_").replace("/", "_")

    if args.output:
        output_file = OUTPUT_DIR / args.output
    else:
        output_file = OUTPUT_DIR / f"analysis_{model_name}_{timestamp}.json"

    save_results(results, output_file)

    print(f"\nTo compare with another model, run again with different backend:")
    print(f"  python analyze.py --backend claude --model haiku")
    print(f"  python analyze.py --backend ollama --model qwen2.5:7b")


if __name__ == "__main__":
    main()
