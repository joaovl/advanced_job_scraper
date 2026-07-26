# UI end-to-end tests

`ui_e2e.py` drives the running web app in a **real Chrome window** so you can watch
it: it moves the mouse, draws a red ring where it clicks, and shows a caption for
each step. Covers landing page, navigation, library search/filter/sort, job
expand, Run Center command building, dashboard and command builder.

## Run it (watch it live)
1. Start the app in one terminal:
   ```
   python -m jobsdb.app          # http://localhost:5000
   ```
2. In another terminal:
   ```
   python tests/ui_e2e.py        # opens Chrome, runs slowly, visible clicks
   ```

A Chrome window opens, walks through 12 steps, and prints `PASS/FAIL` per check
plus a final `N/N checks passed`.

## Options (environment variables)
| Var | Default | Meaning |
|-----|---------|---------|
| `BASE_URL` | `http://localhost:5000` | app under test |
| `HEADLESS` | unset | `1` = no window (for CI) |
| `SLOWMO` | `550` | ms between actions — raise to watch more slowly |

Examples:
```
SLOWMO=900 python tests/ui_e2e.py     # slower, easier to follow
HEADLESS=1 python tests/ui_e2e.py     # fast, no window, exit code = result
```

## Requirements
```
pip install playwright
python -m playwright install chromium   # or: install chrome
```
Uses your installed Google Chrome if present, otherwise Playwright's bundled Chromium.
Exit code is `0` when every check passes, `1` otherwise.
