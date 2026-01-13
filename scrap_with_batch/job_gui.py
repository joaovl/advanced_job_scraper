#!/usr/bin/env python3
"""
Job Scraper & Analyzer GUI

A graphical interface for managing job scraping, analysis, and applications.

Features:
- Configure and run LinkedIn/Fintech scrapers
- View run history and logs
- Analyze jobs with AI scoring
- Browse and filter matched jobs
- Open job URLs to apply

Usage:
    python job_gui.py
"""

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from html import unescape
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, scrolledtext
import tkinter as tk
from typing import Optional, List, Dict, Any


def html_to_text(html: str) -> str:
    """Convert HTML to readable plain text"""
    if not html:
        return ""

    text = html

    # Replace common block elements with newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '  • ', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<h[1-6][^>]*>', '\n\n', text, flags=re.IGNORECASE)

    # Handle strong/bold - add emphasis markers
    text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)

    # Handle em/italic
    text = re.sub(r'<em[^>]*>(.*?)</em>', r'_\1_', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<i[^>]*>(.*?)</i>', r'_\1_', text, flags=re.IGNORECASE | re.DOTALL)

    # Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = unescape(text)

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces to single
    text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newlines
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)  # Leading whitespace per line

    return text.strip()

# Configuration
APP_DIR = Path(__file__).parent
CONFIG_FILE = APP_DIR / "config.json"
HISTORY_FILE = APP_DIR / "run_history.json"
APPLIED_FILE = APP_DIR / "applied_jobs.json"


class JobScraperGUI:
    """Main GUI application for job scraping and analysis"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Job Scraper & Analyzer")
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)

        # State
        self.config = self._load_config()
        self.history = self._load_history()
        self.applied_jobs = self._load_applied_jobs()
        self.current_process: Optional[subprocess.Popen] = None
        self.current_jobs: List[Dict] = []

        # Build UI
        self._create_menu()
        self._create_notebook()
        self._create_status_bar()

        # Bind close event
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_config(self) -> Dict:
        """Load configuration from config.json"""
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def _save_config(self):
        """Save configuration to config.json"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")

    def _load_history(self) -> List[Dict]:
        """Load run history"""
        try:
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_history(self):
        """Save run history"""
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history[-100:], f, indent=2)  # Keep last 100
        except Exception as e:
            print(f"Error saving history: {e}")

    def _load_applied_jobs(self) -> Dict[str, Dict]:
        """Load applied jobs tracking"""
        try:
            if APPLIED_FILE.exists():
                with open(APPLIED_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_applied_jobs(self):
        """Save applied jobs tracking"""
        try:
            with open(APPLIED_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.applied_jobs, f, indent=2)
        except Exception as e:
            print(f"Error saving applied jobs: {e}")

    def _create_menu(self):
        """Create menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Results...", command=self._open_results_file)
        file_menu.add_command(label="Open Excel...", command=self._open_excel_file)
        file_menu.add_separator()
        file_menu.add_command(label="Refresh Files", command=self._refresh_files)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Check Ollama Status", command=self._check_ollama)
        tools_menu.add_command(label="Open Config Folder", command=self._open_config_folder)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)

    def _create_notebook(self):
        """Create tabbed interface"""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create tabs
        self._create_scraper_tab()
        self._create_analyzer_tab()
        self._create_config_tab()
        self._create_results_tab()
        self._create_history_tab()
        self._create_debug_tab()

    def _create_scraper_tab(self):
        """Create scraper configuration tab"""
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="Scraper")

        # Left panel - Scraper selection
        left_frame = ttk.LabelFrame(frame, text="Scraper Type", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        self.scraper_type = tk.StringVar(value="linkedin")
        ttk.Radiobutton(left_frame, text="LinkedIn", variable=self.scraper_type,
                        value="linkedin", command=self._on_scraper_change).pack(anchor=tk.W)
        ttk.Radiobutton(left_frame, text="Fintech Companies", variable=self.scraper_type,
                        value="fintech", command=self._on_scraper_change).pack(anchor=tk.W)

        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Quick actions
        ttk.Label(left_frame, text="Quick Actions:", font=('', 9, 'bold')).pack(anchor=tk.W)
        ttk.Button(left_frame, text="Run All Titles",
                   command=self._run_all_titles).pack(fill=tk.X, pady=2)
        ttk.Button(left_frame, text="Run Custom Search",
                   command=self._run_custom_search).pack(fill=tk.X, pady=2)

        # Right panel - Configuration
        right_frame = ttk.LabelFrame(frame, text="Configuration", padding=10)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # LinkedIn options
        self.linkedin_frame = ttk.Frame(right_frame)
        self.linkedin_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(self.linkedin_frame, text="Keywords:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.keywords_var = tk.StringVar(value="Engineering Manager")
        ttk.Entry(self.linkedin_frame, textvariable=self.keywords_var, width=40).grid(
            row=row, column=1, sticky=tk.W, pady=2)

        row += 1
        ttk.Label(self.linkedin_frame, text="Location:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.location_var = tk.StringVar(value=self.config.get("location", "London, UK"))
        ttk.Entry(self.linkedin_frame, textvariable=self.location_var, width=40).grid(
            row=row, column=1, sticky=tk.W, pady=2)

        row += 1
        ttk.Label(self.linkedin_frame, text="Time Range:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.time_range_var = tk.StringVar(value=self.config.get("time_range", "48h"))
        time_combo = ttk.Combobox(self.linkedin_frame, textvariable=self.time_range_var,
                                   values=["24h", "48h", "7d", "30d"], width=10)
        time_combo.grid(row=row, column=1, sticky=tk.W, pady=2)

        row += 1
        ttk.Label(self.linkedin_frame, text="Max Jobs:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.max_jobs_var = tk.StringVar(value=str(self.config.get("max_jobs_per_title", 50)))
        ttk.Entry(self.linkedin_frame, textvariable=self.max_jobs_var, width=10).grid(
            row=row, column=1, sticky=tk.W, pady=2)

        row += 1
        ttk.Label(self.linkedin_frame, text="Workers:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.workers_var = tk.StringVar(value="4")
        ttk.Spinbox(self.linkedin_frame, textvariable=self.workers_var, from_=1, to=8, width=5).grid(
            row=row, column=1, sticky=tk.W, pady=2)

        row += 1
        self.fetch_desc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.linkedin_frame, text="Fetch job descriptions",
                        variable=self.fetch_desc_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)

        # Job titles from config
        row += 1
        ttk.Label(self.linkedin_frame, text="Job Titles (from config):").grid(
            row=row, column=0, columnspan=2, sticky=tk.W, pady=(10, 2))

        row += 1
        self.titles_listbox = tk.Listbox(self.linkedin_frame, height=6, selectmode=tk.MULTIPLE)
        self.titles_listbox.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=2)
        for title in self.config.get("job_titles", []):
            self.titles_listbox.insert(tk.END, title)

        # Fintech options (hidden initially)
        self.fintech_frame = ttk.Frame(right_frame)

        ttk.Label(self.fintech_frame, text="Companies to scrape:").pack(anchor=tk.W)
        self.companies_listbox = tk.Listbox(self.fintech_frame, height=10, selectmode=tk.MULTIPLE)
        self.companies_listbox.pack(fill=tk.BOTH, expand=True, pady=5)

        companies = ["NatWest", "HSBC", "Barclays", "Wise", "Revolut", "Monzo",
                     "Starling", "Stripe", "Checkout.com", "SumUp", "GoCardless", "eFinancialCareers"]
        for company in companies:
            self.companies_listbox.insert(tk.END, company)

        self.fetch_fintech_desc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.fintech_frame, text="Fetch job descriptions",
                        variable=self.fetch_fintech_desc_var).pack(anchor=tk.W)

        # Output section
        output_frame = ttk.LabelFrame(frame, text="Output", padding=10)
        output_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        ttk.Label(output_frame, text="Output File:").pack(anchor=tk.W)
        self.output_file_var = tk.StringVar(value=f"linkedin_jobs_{datetime.now().strftime('%Y%m%d')}.json")
        ttk.Entry(output_frame, textvariable=self.output_file_var, width=30).pack(fill=tk.X, pady=2)

        ttk.Separator(output_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        self.run_button = ttk.Button(output_frame, text="Run Scraper", command=self._run_scraper)
        self.run_button.pack(fill=tk.X, pady=5)

        self.stop_button = ttk.Button(output_frame, text="Stop", command=self._stop_process, state=tk.DISABLED)
        self.stop_button.pack(fill=tk.X, pady=5)

    def _create_analyzer_tab(self):
        """Create analyzer configuration tab"""
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="Analyzer")

        # Input file selection
        input_frame = ttk.LabelFrame(frame, text="Input", padding=10)
        input_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(input_frame, text="JSON File:").grid(row=0, column=0, sticky=tk.W)
        self.analyze_input_var = tk.StringVar()
        input_combo = ttk.Combobox(input_frame, textvariable=self.analyze_input_var, width=50)
        input_combo.grid(row=0, column=1, sticky=tk.W, padx=5)
        self._update_json_files(input_combo)

        ttk.Button(input_frame, text="Browse...", command=lambda: self._browse_json(input_combo)).grid(
            row=0, column=2, padx=5)
        ttk.Button(input_frame, text="Refresh", command=lambda: self._update_json_files(input_combo)).grid(
            row=0, column=3)

        # Options
        options_frame = ttk.LabelFrame(frame, text="Options", padding=10)
        options_frame.pack(fill=tk.X, pady=(0, 10))

        row = 0
        ttk.Label(options_frame, text="Ollama Model:").grid(row=row, column=0, sticky=tk.W)
        self.model_var = tk.StringVar(value=self.config.get("ollama_model", "qwen2.5:7b"))
        model_combo = ttk.Combobox(options_frame, textvariable=self.model_var, width=20,
                                    values=["qwen2.5:7b", "llama3.1:8b", "gemma2:9b", "mistral:7b"])
        model_combo.grid(row=row, column=1, sticky=tk.W, padx=5)

        row += 1
        ttk.Label(options_frame, text="Limit Jobs:").grid(row=row, column=0, sticky=tk.W)
        self.limit_var = tk.StringVar(value="")
        ttk.Entry(options_frame, textvariable=self.limit_var, width=10).grid(
            row=row, column=1, sticky=tk.W, padx=5)
        ttk.Label(options_frame, text="(empty = all)").grid(row=row, column=2, sticky=tk.W)

        row += 1
        ttk.Label(options_frame, text="Min Score:").grid(row=row, column=0, sticky=tk.W)
        self.min_score_var = tk.StringVar(value=str(self.config.get("min_score", 7)))
        ttk.Spinbox(options_frame, textvariable=self.min_score_var, from_=1, to=10, width=5).grid(
            row=row, column=1, sticky=tk.W, padx=5)

        row += 1
        self.matched_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="Only show matched jobs in output",
                        variable=self.matched_only_var).grid(row=row, column=0, columnspan=3, sticky=tk.W)

        # Output
        output_frame = ttk.LabelFrame(frame, text="Output", padding=10)
        output_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(output_frame, text="Excel File:").grid(row=0, column=0, sticky=tk.W)
        self.analyze_output_var = tk.StringVar(value=f"analysis_{datetime.now().strftime('%Y%m%d')}.xlsx")
        ttk.Entry(output_frame, textvariable=self.analyze_output_var, width=40).grid(
            row=0, column=1, sticky=tk.W, padx=5)

        # Run button
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)

        self.analyze_button = ttk.Button(button_frame, text="Run Analysis", command=self._run_analyzer)
        self.analyze_button.pack(side=tk.LEFT, padx=5)

        self.analyze_stop_button = ttk.Button(button_frame, text="Stop",
                                               command=self._stop_process, state=tk.DISABLED)
        self.analyze_stop_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(button_frame, text="Check Ollama", command=self._check_ollama).pack(side=tk.RIGHT, padx=5)

        # Progress/Log area
        log_frame = ttk.LabelFrame(frame, text="Progress", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.analyze_log = scrolledtext.ScrolledText(log_frame, height=15, state=tk.DISABLED)
        self.analyze_log.pack(fill=tk.BOTH, expand=True)

    def _create_config_tab(self):
        """Create configuration tab for fine-tuning search and scoring"""
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="Configuration")

        # Create a canvas with scrollbar for the whole tab
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack scrollbar and canvas
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Enable mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # === AI Model Settings ===
        model_frame = ttk.LabelFrame(scrollable_frame, text="AI Model Settings", padding=10)
        model_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        row = 0
        ttk.Label(model_frame, text="Ollama Model:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.cfg_model_var = tk.StringVar(value=self.config.get("ollama_model", "qwen2.5:7b"))
        model_combo = ttk.Combobox(model_frame, textvariable=self.cfg_model_var, width=20,
                                    values=["qwen2.5:7b", "llama3.1:8b", "gemma2:9b", "mistral:7b", "qwen3-vl:8b"])
        model_combo.grid(row=row, column=1, sticky=tk.W, padx=5)

        row += 1
        ttk.Label(model_frame, text="Ollama URL:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.cfg_ollama_url_var = tk.StringVar(value=self.config.get("ollama_url", "http://localhost:11434"))
        ttk.Entry(model_frame, textvariable=self.cfg_ollama_url_var, width=35).grid(row=row, column=1, sticky=tk.W, padx=5)

        row += 1
        ttk.Label(model_frame, text="Min Score:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.cfg_min_score_var = tk.StringVar(value=str(self.config.get("min_score", 7)))
        ttk.Spinbox(model_frame, textvariable=self.cfg_min_score_var, from_=1, to=10, width=5).grid(row=row, column=1, sticky=tk.W, padx=5)

        # === Score Adjustments - Positive ===
        pos_frame = ttk.LabelFrame(scrollable_frame, text="Positive Keywords (Boost Score)", padding=10)
        pos_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10), padx=5)

        ttk.Label(pos_frame, text="Keywords that INCREASE the job match score:").pack(anchor=tk.W)

        # Create treeview for positive keywords
        pos_tree_frame = ttk.Frame(pos_frame)
        pos_tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.pos_tree = ttk.Treeview(pos_tree_frame, columns=("keyword", "weight"), show="headings", height=8)
        self.pos_tree.heading("keyword", text="Keyword")
        self.pos_tree.heading("weight", text="Weight")
        self.pos_tree.column("keyword", width=250)
        self.pos_tree.column("weight", width=80, anchor=tk.CENTER)

        pos_vsb = ttk.Scrollbar(pos_tree_frame, orient=tk.VERTICAL, command=self.pos_tree.yview)
        self.pos_tree.configure(yscrollcommand=pos_vsb.set)
        self.pos_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pos_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Populate positive keywords
        score_adj = self.config.get("score_adjustments", {})
        for kw, weight in score_adj.get("positive", {}).items():
            self.pos_tree.insert("", tk.END, values=(kw, f"+{weight}"))

        # Add/Edit/Delete buttons for positive
        pos_btn_frame = ttk.Frame(pos_frame)
        pos_btn_frame.pack(fill=tk.X)

        ttk.Label(pos_btn_frame, text="Keyword:").pack(side=tk.LEFT)
        self.pos_keyword_var = tk.StringVar()
        ttk.Entry(pos_btn_frame, textvariable=self.pos_keyword_var, width=25).pack(side=tk.LEFT, padx=5)
        ttk.Label(pos_btn_frame, text="Weight:").pack(side=tk.LEFT)
        self.pos_weight_var = tk.StringVar(value="3")
        ttk.Spinbox(pos_btn_frame, textvariable=self.pos_weight_var, from_=1, to=10, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Button(pos_btn_frame, text="Add", command=self._add_positive_keyword).pack(side=tk.LEFT, padx=5)
        ttk.Button(pos_btn_frame, text="Delete Selected", command=self._delete_positive_keyword).pack(side=tk.LEFT, padx=5)

        # === Score Adjustments - Negative ===
        neg_frame = ttk.LabelFrame(scrollable_frame, text="Negative Keywords (Reduce Score)", padding=10)
        neg_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10), padx=5)

        ttk.Label(neg_frame, text="Keywords that DECREASE the job match score:").pack(anchor=tk.W)

        # Create treeview for negative keywords
        neg_tree_frame = ttk.Frame(neg_frame)
        neg_tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.neg_tree = ttk.Treeview(neg_tree_frame, columns=("keyword", "weight"), show="headings", height=8)
        self.neg_tree.heading("keyword", text="Keyword")
        self.neg_tree.heading("weight", text="Weight")
        self.neg_tree.column("keyword", width=250)
        self.neg_tree.column("weight", width=80, anchor=tk.CENTER)

        neg_vsb = ttk.Scrollbar(neg_tree_frame, orient=tk.VERTICAL, command=self.neg_tree.yview)
        self.neg_tree.configure(yscrollcommand=neg_vsb.set)
        self.neg_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        neg_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Populate negative keywords
        for kw, weight in score_adj.get("negative", {}).items():
            self.neg_tree.insert("", tk.END, values=(kw, str(weight)))

        # Add/Edit/Delete buttons for negative
        neg_btn_frame = ttk.Frame(neg_frame)
        neg_btn_frame.pack(fill=tk.X)

        ttk.Label(neg_btn_frame, text="Keyword:").pack(side=tk.LEFT)
        self.neg_keyword_var = tk.StringVar()
        ttk.Entry(neg_btn_frame, textvariable=self.neg_keyword_var, width=25).pack(side=tk.LEFT, padx=5)
        ttk.Label(neg_btn_frame, text="Weight:").pack(side=tk.LEFT)
        self.neg_weight_var = tk.StringVar(value="-2")
        ttk.Spinbox(neg_btn_frame, textvariable=self.neg_weight_var, from_=-10, to=-1, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Button(neg_btn_frame, text="Add", command=self._add_negative_keyword).pack(side=tk.LEFT, padx=5)
        ttk.Button(neg_btn_frame, text="Delete Selected", command=self._delete_negative_keyword).pack(side=tk.LEFT, padx=5)

        # === Exclusion Lists ===
        excl_frame = ttk.LabelFrame(scrollable_frame, text="Exclusion Filters (Instant Reject)", padding=10)
        excl_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10), padx=5)

        # Title exclusions
        title_excl_frame = ttk.Frame(excl_frame)
        title_excl_frame.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=(0, 5))

        ttk.Label(title_excl_frame, text="Exclude if TITLE contains:").pack(anchor=tk.W)
        self.title_excl_text = scrolledtext.ScrolledText(title_excl_frame, height=6, width=35)
        self.title_excl_text.pack(fill=tk.BOTH, expand=True)
        self.title_excl_text.insert(tk.END, "\n".join(self.config.get("exclude_in_title", [])))

        # Description exclusions
        desc_excl_frame = ttk.Frame(excl_frame)
        desc_excl_frame.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=(5, 0))

        ttk.Label(desc_excl_frame, text="Exclude if DESCRIPTION contains:").pack(anchor=tk.W)
        self.desc_excl_text = scrolledtext.ScrolledText(desc_excl_frame, height=6, width=35)
        self.desc_excl_text.pack(fill=tk.BOTH, expand=True)
        self.desc_excl_text.insert(tk.END, "\n".join(self.config.get("exclude_in_description", [])))

        # === Must Have Keywords ===
        must_frame = ttk.LabelFrame(scrollable_frame, text="Must-Have Keywords (At least one required)", padding=10)
        must_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        ttk.Label(must_frame, text="Job must contain at least ONE of these keywords:").pack(anchor=tk.W)
        self.must_have_text = scrolledtext.ScrolledText(must_frame, height=3, width=70)
        self.must_have_text.pack(fill=tk.X)
        self.must_have_text.insert(tk.END, "\n".join(self.config.get("must_have", [])))

        # === Flag for Review ===
        flag_frame = ttk.LabelFrame(scrollable_frame, text="Flag for Review (Warnings)", padding=10)
        flag_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        ttk.Label(flag_frame, text="Jobs containing these will be flagged but not rejected:").pack(anchor=tk.W)
        self.flag_review_text = scrolledtext.ScrolledText(flag_frame, height=3, width=70)
        self.flag_review_text.pack(fill=tk.X)
        self.flag_review_text.insert(tk.END, "\n".join(self.config.get("flag_for_review", [])))

        # === Job Titles ===
        titles_frame = ttk.LabelFrame(scrollable_frame, text="Job Search Titles", padding=10)
        titles_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        ttk.Label(titles_frame, text="Job titles to search for (one per line):").pack(anchor=tk.W)
        self.job_titles_text = scrolledtext.ScrolledText(titles_frame, height=4, width=70)
        self.job_titles_text.pack(fill=tk.X)
        self.job_titles_text.insert(tk.END, "\n".join(self.config.get("job_titles", [])))

        # === Save Button ===
        save_frame = ttk.Frame(scrollable_frame)
        save_frame.pack(fill=tk.X, pady=10, padx=5)

        ttk.Button(save_frame, text="Save Configuration", command=self._save_all_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(save_frame, text="Reload from File", command=self._reload_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(save_frame, text="Export Config...", command=self._export_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(save_frame, text="Import Config...", command=self._import_config).pack(side=tk.RIGHT, padx=5)

    def _add_positive_keyword(self):
        """Add a positive keyword"""
        keyword = self.pos_keyword_var.get().strip()
        try:
            weight = int(self.pos_weight_var.get())
        except ValueError:
            weight = 3

        if keyword:
            self.pos_tree.insert("", tk.END, values=(keyword, f"+{abs(weight)}"))
            self.pos_keyword_var.set("")

    def _delete_positive_keyword(self):
        """Delete selected positive keyword"""
        selected = self.pos_tree.selection()
        for item in selected:
            self.pos_tree.delete(item)

    def _add_negative_keyword(self):
        """Add a negative keyword"""
        keyword = self.neg_keyword_var.get().strip()
        try:
            weight = int(self.neg_weight_var.get())
        except ValueError:
            weight = -2

        if keyword:
            self.neg_tree.insert("", tk.END, values=(keyword, str(-abs(weight))))
            self.neg_keyword_var.set("")

    def _delete_negative_keyword(self):
        """Delete selected negative keyword"""
        selected = self.neg_tree.selection()
        for item in selected:
            self.neg_tree.delete(item)

    def _save_all_config(self):
        """Save all configuration to config.json"""
        # AI Model settings
        self.config["ollama_model"] = self.cfg_model_var.get()
        self.config["ollama_url"] = self.cfg_ollama_url_var.get()
        try:
            self.config["min_score"] = int(self.cfg_min_score_var.get())
        except ValueError:
            self.config["min_score"] = 7

        # Score adjustments - positive
        positive = {}
        for item in self.pos_tree.get_children():
            values = self.pos_tree.item(item)["values"]
            keyword = values[0]
            weight_str = str(values[1]).replace("+", "")
            try:
                weight = int(weight_str)
            except ValueError:
                weight = 3
            positive[keyword] = abs(weight)

        # Score adjustments - negative
        negative = {}
        for item in self.neg_tree.get_children():
            values = self.neg_tree.item(item)["values"]
            keyword = values[0]
            try:
                weight = int(values[1])
            except ValueError:
                weight = -2
            negative[keyword] = weight if weight < 0 else -weight

        self.config["score_adjustments"] = {"positive": positive, "negative": negative}

        # Exclusion lists
        title_excl = [line.strip() for line in self.title_excl_text.get(1.0, tk.END).split("\n") if line.strip()]
        desc_excl = [line.strip() for line in self.desc_excl_text.get(1.0, tk.END).split("\n") if line.strip()]
        must_have = [line.strip() for line in self.must_have_text.get(1.0, tk.END).split("\n") if line.strip()]
        flag_review = [line.strip() for line in self.flag_review_text.get(1.0, tk.END).split("\n") if line.strip()]
        job_titles = [line.strip() for line in self.job_titles_text.get(1.0, tk.END).split("\n") if line.strip()]

        self.config["exclude_in_title"] = title_excl
        self.config["exclude_in_description"] = desc_excl
        self.config["must_have"] = must_have
        self.config["flag_for_review"] = flag_review
        self.config["job_titles"] = job_titles

        # Save to file
        self._save_config()
        messagebox.showinfo("Success", "Configuration saved successfully!")

    def _reload_config(self):
        """Reload configuration from file"""
        self.config = self._load_config()
        # Refresh the config tab
        self.notebook.forget(2)  # Remove config tab
        self._create_config_tab()  # Recreate it
        messagebox.showinfo("Success", "Configuration reloaded from file!")

    def _export_config(self):
        """Export configuration to a file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="config_backup.json"
        )
        if filename:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            messagebox.showinfo("Success", f"Configuration exported to {filename}")

    def _import_config(self):
        """Import configuration from a file"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")]
        )
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                self._save_config()
                self._reload_config()
                messagebox.showinfo("Success", "Configuration imported successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import: {e}")

    def _create_results_tab(self):
        """Create results viewer tab"""
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="Results")

        # Filter bar
        filter_frame = ttk.Frame(frame)
        filter_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(filter_frame, text="Load:").pack(side=tk.LEFT)
        self.results_file_var = tk.StringVar()
        self.results_combo = ttk.Combobox(filter_frame, textvariable=self.results_file_var, width=40)
        self.results_combo.pack(side=tk.LEFT, padx=5)
        self._update_result_files()

        ttk.Button(filter_frame, text="Load", command=self._load_results).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_frame, text="Refresh", command=self._update_result_files).pack(side=tk.LEFT)

        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace('w', lambda *args: self._filter_results())
        ttk.Entry(filter_frame, textvariable=self.filter_var, width=20).pack(side=tk.LEFT, padx=5)

        self.show_applied_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(filter_frame, text="Show Applied",
                        variable=self.show_applied_var,
                        command=self._filter_results).pack(side=tk.LEFT, padx=5)

        # Results treeview
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("score", "company", "title", "location", "status")
        self.results_tree = ttk.Treeview(tree_frame, columns=columns, show="headings")

        self.results_tree.heading("score", text="Score")
        self.results_tree.heading("company", text="Company")
        self.results_tree.heading("title", text="Title")
        self.results_tree.heading("location", text="Location")
        self.results_tree.heading("status", text="Status")

        self.results_tree.column("score", width=60, anchor=tk.CENTER)
        self.results_tree.column("company", width=150)
        self.results_tree.column("title", width=300)
        self.results_tree.column("location", width=150)
        self.results_tree.column("status", width=100, anchor=tk.CENTER)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.results_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.results_tree.xview)
        self.results_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.results_tree.grid(row=0, column=0, sticky=tk.NSEW)
        vsb.grid(row=0, column=1, sticky=tk.NS)
        hsb.grid(row=1, column=0, sticky=tk.EW)

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Bind double-click
        self.results_tree.bind("<Double-1>", self._on_result_double_click)
        self.results_tree.bind("<Return>", self._on_result_double_click)

        # Action buttons
        action_frame = ttk.Frame(frame)
        action_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(action_frame, text="Open Job URL", command=self._open_selected_job).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Mark as Applied", command=self._mark_applied).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Mark as Not Interested", command=self._mark_not_interested).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Clear Status", command=self._clear_status).pack(side=tk.LEFT, padx=5)

        # Job details panel
        details_frame = ttk.LabelFrame(frame, text="Job Details", padding=10)
        details_frame.pack(fill=tk.X, pady=(10, 0))

        self.details_text = scrolledtext.ScrolledText(details_frame, height=15, state=tk.DISABLED, wrap=tk.WORD)
        self.details_text.pack(fill=tk.BOTH, expand=True)

        # Bind selection
        self.results_tree.bind("<<TreeviewSelect>>", self._on_result_select)

    def _create_history_tab(self):
        """Create run history tab"""
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="History")

        # History list
        columns = ("timestamp", "type", "command", "status", "jobs")
        self.history_tree = ttk.Treeview(frame, columns=columns, show="headings")

        self.history_tree.heading("timestamp", text="Time")
        self.history_tree.heading("type", text="Type")
        self.history_tree.heading("command", text="Command")
        self.history_tree.heading("status", text="Status")
        self.history_tree.heading("jobs", text="Jobs")

        self.history_tree.column("timestamp", width=150)
        self.history_tree.column("type", width=80)
        self.history_tree.column("command", width=400)
        self.history_tree.column("status", width=80)
        self.history_tree.column("jobs", width=80)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=vsb.set)

        self.history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_history()

        # Buttons
        button_frame = ttk.Frame(frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)

        ttk.Button(button_frame, text="Refresh", command=self._refresh_history).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear History", command=self._clear_history).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Re-run Selected", command=self._rerun_selected).pack(side=tk.RIGHT, padx=5)

    def _create_debug_tab(self):
        """Create debug/logs tab"""
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="Debug")

        # Toolbar
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(toolbar, text="Clear Log", command=self._clear_debug_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Save Log...", command=self._save_debug_log).pack(side=tk.LEFT, padx=5)

        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.auto_scroll_var).pack(side=tk.LEFT, padx=10)

        self.debug_level_var = tk.StringVar(value="INFO")
        ttk.Label(toolbar, text="Level:").pack(side=tk.LEFT, padx=(10, 5))
        ttk.Combobox(toolbar, textvariable=self.debug_level_var, width=10,
                     values=["DEBUG", "INFO", "WARNING", "ERROR"]).pack(side=tk.LEFT)

        # Log area
        self.debug_log = scrolledtext.ScrolledText(frame, height=30, state=tk.DISABLED,
                                                    font=('Consolas', 9))
        self.debug_log.pack(fill=tk.BOTH, expand=True)

        # Configure tags for log levels
        self.debug_log.tag_configure("ERROR", foreground="red")
        self.debug_log.tag_configure("WARNING", foreground="orange")
        self.debug_log.tag_configure("INFO", foreground="black")
        self.debug_log.tag_configure("DEBUG", foreground="gray")

    def _create_status_bar(self):
        """Create status bar"""
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # === Event Handlers ===

    def _on_scraper_change(self):
        """Handle scraper type change"""
        if self.scraper_type.get() == "linkedin":
            self.fintech_frame.pack_forget()
            self.linkedin_frame.pack(fill=tk.BOTH, expand=True)
            self.output_file_var.set(f"linkedin_jobs_{datetime.now().strftime('%Y%m%d')}.json")
        else:
            self.linkedin_frame.pack_forget()
            self.fintech_frame.pack(fill=tk.BOTH, expand=True)
            self.output_file_var.set(f"jobs_{datetime.now().strftime('%Y%m%d')}.json")

    def _on_result_double_click(self, event):
        """Handle double-click on result"""
        self._open_selected_job()

    def _on_result_select(self, event):
        """Handle result selection"""
        selection = self.results_tree.selection()
        if not selection:
            return

        item = self.results_tree.item(selection[0])
        idx = self.results_tree.index(selection[0])

        if idx < len(self.current_jobs):
            job = self.current_jobs[idx]
            self._show_job_details(job)

    def _show_job_details(self, job: Dict):
        """Show job details in panel"""
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)

        # Handle both raw jobs and analyzed results field names
        title = job.get('title', '') or job.get('job_title', 'N/A')
        company = job.get('company', 'N/A')
        location = job.get('location', 'N/A')
        url = job.get('url', '') or job.get('job_link', 'N/A')
        score = job.get('score', 'N/A')
        ai_score = job.get('ai_score', '')
        adjustment = job.get('adjustment', '')
        decision = job.get('decision', '')
        reason = job.get('reason', '') or job.get('analysis', '')
        flags = job.get('flags', '')
        score_details = job.get('score_details', '')

        # Convert HTML description to readable text
        raw_description = job.get('description', 'No description available')
        description = html_to_text(raw_description)

        # Build details string
        details = f"""Title: {title}
Company: {company}
Location: {location}
URL: {url}

"""
        # Add score info if available
        if score != 'N/A':
            details += f"Score: {score}"
            if ai_score:
                details += f" (AI: {ai_score}, Adjust: {adjustment:+d})" if isinstance(adjustment, int) else f" (AI: {ai_score})"
            details += "\n"
        if decision:
            details += f"Decision: {decision}\n"
        if reason:
            details += f"Reason: {reason}\n"
        if flags:
            details += f"Flags: {flags}\n"
        if score_details:
            details += f"Score Details: {score_details}\n"

        details += f"""
{'='*50}
DESCRIPTION:
{'='*50}

{description}
"""
        self.details_text.insert(tk.END, details)
        self.details_text.configure(state=tk.DISABLED)

    def _on_close(self):
        """Handle window close"""
        if self.current_process:
            if messagebox.askyesno("Confirm", "A process is running. Stop it and exit?"):
                self._stop_process()
            else:
                return
        self._save_applied_jobs()
        self.root.destroy()

    # === Actions ===

    def _run_scraper(self):
        """Run the selected scraper"""
        if self.scraper_type.get() == "linkedin":
            self._run_linkedin_scraper()
        else:
            self._run_fintech_scraper()

    def _run_linkedin_scraper(self):
        """Run LinkedIn scraper"""
        keywords = self.keywords_var.get().strip()
        if not keywords:
            messagebox.showwarning("Warning", "Please enter keywords")
            return

        cmd = [
            sys.executable, "linkedin_scraper.py",
            "-k", keywords,
            "-l", self.location_var.get(),
            "-n", self.max_jobs_var.get(),
            "-t", self.time_range_var.get(),
            "-w", self.workers_var.get(),
            "-o", self.output_file_var.get()
        ]

        if not self.fetch_desc_var.get():
            cmd.append("--no-description")

        self._execute_command(cmd, "linkedin")

    def _run_all_titles(self):
        """Run scraper for all job titles from config"""
        if self.scraper_type.get() == "linkedin":
            cmd = [
                sys.executable, "linkedin_scraper.py",
                "-a",  # All titles
                "-l", self.location_var.get(),
                "-t", self.time_range_var.get(),
                "-o", self.output_file_var.get()
            ]
            if not self.fetch_desc_var.get():
                cmd.append("--no-description")
            self._execute_command(cmd, "linkedin")
        else:
            self._run_fintech_scraper()

    def _run_custom_search(self):
        """Run scraper with current settings"""
        self._run_scraper()

    def _run_fintech_scraper(self):
        """Run fintech company scraper"""
        cmd = [sys.executable, "job_scraper.py", "-f"]

        # Get selected companies
        selected = self.companies_listbox.curselection()
        if selected:
            companies = [self.companies_listbox.get(i) for i in selected]
            if len(companies) == 1:
                cmd.extend(["--company", companies[0]])

        self._execute_command(cmd, "fintech")

    def _run_analyzer(self):
        """Run job analyzer"""
        input_file = self.analyze_input_var.get()
        if not input_file:
            messagebox.showwarning("Warning", "Please select an input file")
            return

        cmd = [
            sys.executable, "job_analyzer.py",
            input_file,
            "-o", self.analyze_output_var.get(),
            "--model", self.model_var.get()
        ]

        if self.limit_var.get():
            cmd.extend(["--limit", self.limit_var.get()])

        if self.matched_only_var.get():
            cmd.append("--matched-only")

        self._execute_command(cmd, "analyzer")

    def _execute_command(self, cmd: List[str], cmd_type: str):
        """Execute a command in background"""
        self.status_var.set(f"Running {cmd_type}...")
        self.run_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.analyze_button.configure(state=tk.DISABLED)
        self.analyze_stop_button.configure(state=tk.NORMAL)

        # Add to history
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": cmd_type,
            "command": " ".join(cmd),
            "status": "running",
            "jobs": 0
        }
        self.history.append(history_entry)
        self._save_history()
        self._refresh_history()

        # Log command
        self._log(f"Starting: {' '.join(cmd)}")

        def run():
            try:
                self.current_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=str(APP_DIR)
                )

                for line in iter(self.current_process.stdout.readline, ''):
                    if line:
                        self._log(line.strip())
                        self._update_analyze_log(line)

                self.current_process.wait()
                exit_code = self.current_process.returncode

                # Update history
                history_entry["status"] = "success" if exit_code == 0 else "failed"
                self._save_history()

                self.root.after(0, lambda: self._on_process_complete(exit_code))

            except Exception as e:
                self._log(f"ERROR: {e}", "ERROR")
                history_entry["status"] = "error"
                self._save_history()
                self.root.after(0, lambda: self._on_process_complete(-1))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _on_process_complete(self, exit_code: int):
        """Handle process completion"""
        self.current_process = None
        self.run_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.analyze_button.configure(state=tk.NORMAL)
        self.analyze_stop_button.configure(state=tk.DISABLED)

        if exit_code == 0:
            self.status_var.set("Completed successfully")
            self._refresh_files()
        else:
            self.status_var.set(f"Process exited with code {exit_code}")

        self._refresh_history()

    def _stop_process(self):
        """Stop running process"""
        if self.current_process:
            self.current_process.terminate()
            self._log("Process terminated by user", "WARNING")
            self.status_var.set("Stopped")

    def _load_results(self):
        """Load results from selected file"""
        filename = self.results_file_var.get()
        if not filename:
            return

        filepath = APP_DIR / filename
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Handle both list and dict formats
            if isinstance(data, list):
                self.current_jobs = data
            elif isinstance(data, dict) and "jobs" in data:
                self.current_jobs = data["jobs"]
            else:
                self.current_jobs = []

            self._populate_results_tree()
            self.status_var.set(f"Loaded {len(self.current_jobs)} jobs from {filename}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load results: {e}")

    def _populate_results_tree(self):
        """Populate results treeview"""
        self.results_tree.delete(*self.results_tree.get_children())

        for job in self.current_jobs:
            # Handle both raw jobs (url) and analyzed results (job_link)
            url = job.get("url", "") or job.get("job_link", "")
            status = self.applied_jobs.get(url, {}).get("status", "")

            # Handle both raw jobs (title/company) and analyzed results (job_title)
            title = job.get("title", "") or job.get("job_title", "")
            company = job.get("company", "")
            location = job.get("location", "")
            score = job.get("score", "N/A")

            self.results_tree.insert("", tk.END, values=(
                score,
                company,
                title,
                location,
                status
            ))

    def _filter_results(self):
        """Filter results based on search text"""
        filter_text = self.filter_var.get().lower()
        show_applied = self.show_applied_var.get()

        self.results_tree.delete(*self.results_tree.get_children())

        for job in self.current_jobs:
            # Handle both raw jobs (url) and analyzed results (job_link)
            url = job.get("url", "") or job.get("job_link", "")
            status = self.applied_jobs.get(url, {}).get("status", "")

            # Handle both raw jobs (title/company) and analyzed results (job_title)
            title = job.get("title", "") or job.get("job_title", "")
            company = job.get("company", "")
            location = job.get("location", "")
            score = job.get("score", "N/A")

            # Filter by applied status
            if not show_applied and status == "applied":
                continue

            # Filter by text
            if filter_text:
                searchable = f"{company} {title} {location}".lower()
                if filter_text not in searchable:
                    continue

            self.results_tree.insert("", tk.END, values=(
                score,
                company,
                title,
                location,
                status
            ))

    def _open_selected_job(self):
        """Open selected job URL in browser"""
        selection = self.results_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Please select a job")
            return

        idx = self.results_tree.index(selection[0])
        if idx < len(self.current_jobs):
            url = self.current_jobs[idx].get("url", "")
            if url:
                webbrowser.open(url)

    def _mark_applied(self):
        """Mark selected job as applied"""
        self._set_job_status("applied")

    def _mark_not_interested(self):
        """Mark selected job as not interested"""
        self._set_job_status("not interested")

    def _clear_status(self):
        """Clear status for selected job"""
        self._set_job_status("")

    def _set_job_status(self, status: str):
        """Set status for selected job"""
        selection = self.results_tree.selection()
        if not selection:
            return

        for item in selection:
            idx = self.results_tree.index(item)
            if idx < len(self.current_jobs):
                url = self.current_jobs[idx].get("url", "")
                if url:
                    if status:
                        self.applied_jobs[url] = {
                            "status": status,
                            "date": datetime.now().isoformat(),
                            "title": self.current_jobs[idx].get("title", ""),
                            "company": self.current_jobs[idx].get("company", "")
                        }
                    elif url in self.applied_jobs:
                        del self.applied_jobs[url]

        self._save_applied_jobs()
        self._filter_results()

    # === Helper Methods ===

    def _update_json_files(self, combo: ttk.Combobox):
        """Update JSON file list in combobox"""
        files = sorted(APP_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        file_names = [f.name for f in files if f.name not in ["config.json", "run_history.json", "applied_jobs.json"]]
        combo['values'] = file_names
        if file_names:
            combo.set(file_names[0])

    def _update_result_files(self):
        """Update result files list"""
        files = sorted(APP_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        file_names = [f.name for f in files if f.name not in ["config.json", "run_history.json", "applied_jobs.json"]]
        self.results_combo['values'] = file_names
        if file_names and not self.results_file_var.get():
            self.results_combo.set(file_names[0])

    def _browse_json(self, combo: ttk.Combobox):
        """Browse for JSON file"""
        filename = filedialog.askopenfilename(
            initialdir=APP_DIR,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filename:
            combo.set(Path(filename).name)

    def _refresh_files(self):
        """Refresh all file lists"""
        self._update_result_files()

    def _refresh_history(self):
        """Refresh history list"""
        self.history_tree.delete(*self.history_tree.get_children())
        for entry in reversed(self.history[-50:]):
            self.history_tree.insert("", tk.END, values=(
                entry.get("timestamp", "")[:19],
                entry.get("type", ""),
                entry.get("command", "")[:60] + "..." if len(entry.get("command", "")) > 60 else entry.get("command", ""),
                entry.get("status", ""),
                entry.get("jobs", "")
            ))

    def _clear_history(self):
        """Clear run history"""
        if messagebox.askyesno("Confirm", "Clear all run history?"):
            self.history = []
            self._save_history()
            self._refresh_history()

    def _rerun_selected(self):
        """Re-run selected command from history"""
        selection = self.history_tree.selection()
        if not selection:
            return

        item = self.history_tree.item(selection[0])
        # Would need to parse and re-execute command
        messagebox.showinfo("Info", "Re-run functionality coming soon")

    def _log(self, message: str, level: str = "INFO"):
        """Add message to debug log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_message = f"[{timestamp}] {level}: {message}\n"

        self.debug_log.configure(state=tk.NORMAL)
        self.debug_log.insert(tk.END, full_message, level)
        if self.auto_scroll_var.get():
            self.debug_log.see(tk.END)
        self.debug_log.configure(state=tk.DISABLED)

    def _update_analyze_log(self, message: str):
        """Update analyzer log"""
        self.analyze_log.configure(state=tk.NORMAL)
        self.analyze_log.insert(tk.END, message)
        self.analyze_log.see(tk.END)
        self.analyze_log.configure(state=tk.DISABLED)

    def _clear_debug_log(self):
        """Clear debug log"""
        self.debug_log.configure(state=tk.NORMAL)
        self.debug_log.delete(1.0, tk.END)
        self.debug_log.configure(state=tk.DISABLED)

    def _save_debug_log(self):
        """Save debug log to file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.debug_log.get(1.0, tk.END))

    def _check_ollama(self):
        """Check Ollama status"""
        try:
            import urllib.request
            url = self.config.get("ollama_url", "http://localhost:11434")
            req = urllib.request.Request(f"{url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read())
                models = [m["name"] for m in data.get("models", [])]
                messagebox.showinfo("Ollama Status",
                    f"Ollama is running!\n\nAvailable models:\n" + "\n".join(models[:10]))
        except Exception as e:
            messagebox.showerror("Ollama Status",
                f"Ollama is not running or not accessible.\n\nError: {e}\n\nStart Ollama with: ollama serve")

    def _open_results_file(self):
        """Open a results JSON file"""
        filename = filedialog.askopenfilename(
            initialdir=APP_DIR,
            filetypes=[("JSON files", "*.json")]
        )
        if filename:
            self.results_file_var.set(Path(filename).name)
            self._load_results()
            self.notebook.select(2)  # Switch to Results tab

    def _open_excel_file(self):
        """Open an Excel file"""
        filename = filedialog.askopenfilename(
            initialdir=APP_DIR,
            filetypes=[("Excel files", "*.xlsx")]
        )
        if filename:
            os.startfile(filename)

    def _open_config_folder(self):
        """Open config folder in explorer"""
        os.startfile(str(APP_DIR))

    def _show_about(self):
        """Show about dialog"""
        messagebox.showinfo("About",
            "Job Scraper & Analyzer GUI\n\n"
            "A unified interface for:\n"
            "- LinkedIn job scraping\n"
            "- Fintech company scraping\n"
            "- AI-powered job analysis\n"
            "- Application tracking\n\n"
            "Version 1.0")


def main():
    root = tk.Tk()
    app = JobScraperGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
