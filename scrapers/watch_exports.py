#!/usr/bin/env python3
"""
File Watcher for Chrome Extension Exports

Monitors Company_Pages folder for new jobs_export.json files
and automatically processes them to fetch descriptions.

Usage:
    python scrapers/watch_exports.py

Set your Chrome download folder to include Company_Pages/ or
configure Chrome to save to C:\\tmp\\Find_Jobs_Directly_on_websites\\
"""

import sys
import time
import json
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Import processing function from our script
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "scrapers"))

try:
    from process_extension_export import process_export, is_navigation_item
except ImportError:
    print("Error: Could not import process_extension_export.py")
    print("Make sure it exists in the scrapers folder")
    sys.exit(1)

COMPANY_PAGES_DIR = BASE_DIR / "Company_Pages"
PROCESSED_MARKER = ".processed"


class ExportHandler(FileSystemEventHandler):
    """Handle new jobs_export.json files."""

    def __init__(self):
        self.processing = set()  # Track files being processed
        self.cooldown = {}  # Prevent duplicate processing

    def on_created(self, event):
        self._handle_file(event.src_path)

    def on_modified(self, event):
        self._handle_file(event.src_path)

    def _handle_file(self, filepath):
        path = Path(filepath)

        # Only process jobs_export.json files
        if path.name != "jobs_export.json":
            return

        # Check cooldown (don't reprocess same file within 5 seconds)
        now = time.time()
        if filepath in self.cooldown and now - self.cooldown[filepath] < 5:
            return
        self.cooldown[filepath] = now

        # Skip if already processing
        if filepath in self.processing:
            return

        self.processing.add(filepath)

        try:
            # Wait a moment for file to be fully written
            time.sleep(1)

            # Get company folder name
            company_folder = path.parent.name

            print("\n" + "=" * 60)
            print(f"NEW EXPORT DETECTED: {company_folder}")
            print("=" * 60)

            # Process the export
            process_export(company_folder)

            # Mark as processed
            marker_file = path.parent / PROCESSED_MARKER
            marker_file.write_text(datetime.now().isoformat())

            print("\n[Watching for more exports... Press Ctrl+C to stop]\n")

        except Exception as e:
            print(f"Error processing {company_folder}: {e}")

        finally:
            self.processing.discard(filepath)


def main():
    # Check if watchdog is installed
    try:
        from watchdog.observers import Observer
    except ImportError:
        print("Installing watchdog package...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "watchdog"])
        from watchdog.observers import Observer

    # Create Company_Pages if it doesn't exist
    COMPANY_PAGES_DIR.mkdir(exist_ok=True)

    print("=" * 60)
    print("JOB EXPORT WATCHER")
    print("=" * 60)
    print(f"\nWatching: {COMPANY_PAGES_DIR}")
    print("\nWorkflow:")
    print("  1. Visit a careers page in Chrome")
    print("  2. Press Alt+Shift+J for quick export (or use popup)")
    print("  3. Save to Company_Pages/<CompanyName>/")
    print("  4. This script auto-processes and fetches descriptions")
    print("\nPress Ctrl+C to stop\n")

    # Check for unprocessed exports on startup
    print("Checking for unprocessed exports...")
    found_any = False
    for folder in COMPANY_PAGES_DIR.iterdir():
        if folder.is_dir():
            export_file = folder / "jobs_export.json"
            marker_file = folder / PROCESSED_MARKER

            if export_file.exists():
                # Check if needs processing
                needs_processing = False

                if not marker_file.exists():
                    needs_processing = True
                else:
                    # Check if export is newer than marker
                    export_mtime = export_file.stat().st_mtime
                    marker_mtime = marker_file.stat().st_mtime
                    if export_mtime > marker_mtime:
                        needs_processing = True

                if needs_processing:
                    found_any = True
                    print(f"\nProcessing: {folder.name}")
                    try:
                        process_export(folder.name)
                        marker_file.write_text(datetime.now().isoformat())
                    except Exception as e:
                        print(f"  Error: {e}")

    if not found_any:
        print("No unprocessed exports found.\n")

    # Start watching
    event_handler = ExportHandler()
    observer = Observer()
    observer.schedule(event_handler, str(COMPANY_PAGES_DIR), recursive=True)
    observer.start()

    print("[Watching for new exports...]\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping watcher...")
        observer.stop()

    observer.join()
    print("Done.")


if __name__ == "__main__":
    main()
