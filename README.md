# EventTrace (Prototype)

Monitors the Calcutta High Court Display Board in near real time (Playwright), detects field-level changes, and stores a change log in SQLite. Exposes a FastAPI read API for current state + recent changes.

## Quick start

1) Create a venv and install deps

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install
```

2) Initialize a Playwright session (manual CAPTCHA once)

```bash
court-display-init-session
```

3) Start the monitor loop (writes `eventtrace.sqlite3` by default)

```bash
court-display-run-monitor
```

4) Start the API

```bash
court-display-api
```

## Configuration

All config is via environment variables (optional):

- `CHD_URL` (default: `https://display.calcuttahighcourt.gov.in/principal.php`)
- `CHD_TABLE_SELECTOR` (default: `table`)
- `CHD_KEY_FIELDS` (default: `Court`)
- `CHD_POLL_SECONDS` (default: `15`)
- `CHD_DB_PATH` (default: `./eventtrace.sqlite3`)
- `CHD_STORAGE_STATE_PATH` (default: `./.state/storage_state.json`)
- `CHD_HEADLESS` (default: `0` for init-session, `1` for monitor unless unset)

## Notes

- This repo avoids hardcoding table columns. Headers are detected each scrape and rows are normalized.
- If the site blocks your session, re-run `chd-init-session` to refresh the stored cookies.
