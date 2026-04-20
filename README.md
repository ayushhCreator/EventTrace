# EventTrace

Monitors the Calcutta High Court Principal Bench display board in near real-time. Detects field-level changes per court, stores a full change log in SQLite, and serves a live dashboard + CSV export via FastAPI.

---

## How it works

The site exposes `display_api.json` — a public JSON endpoint updated every ~15 seconds. EventTrace polls it, compares each field against the previous snapshot, and writes a change record whenever anything changes (judge names, serial numbers, etc.).

No CAPTCHA solving needed. No login. The JSON endpoint is open.

---

## Setup (one time)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

---

## Running

Open **two terminals**.

**Terminal 1 — monitor loop** (writes to DB every 15s):
```bash
source .venv/bin/activate
chd-run-monitor
```

You'll see output like:
```
Monitoring https://display.calcuttahighcourt.gov.in/principal.php
DB: ./eventtrace.sqlite3
Poll seconds: 15
[2026-04-20T10:05:30+00:00] 266385 judge_names: None -> 'HON'BLE CHIEF JUSTICE...' (0s)
[2026-04-20T10:20:15+00:00] 266385 cause_list_sr_no: '27' -> '28' (885s)
```

Each printed line = one field changed on one court.

**Terminal 2 — API + dashboard**:
```bash
source .venv/bin/activate
chd-api
```

---

## Viewing data

### Dashboard (recommended)

Open in browser: **http://127.0.0.1:8009/ui**

- **Current State** table — live snapshot of all 23+ courts right now
- **Event Traces** table — every change ever recorded, newest first
- Filter by court, adjust auto-refresh interval (10s / 15s / 30s / 60s / off)
- Download either table as CSV with one click

### API endpoints

| Endpoint | What it returns |
|----------|----------------|
| `GET /current-state` | All courts, latest data |
| `GET /event-traces?limit=200&court_id=266385` | Change log, filterable |
| `GET /field-state/266385` | Per-field history for one court |
| `GET /export/current-state.csv` | Current state as CSV download |
| `GET /export/event-traces.csv?limit=2000` | Change log as CSV download |
| `GET /health` | `{"status": "ok"}` |

### SQLite directly

```bash
# How many courts are being tracked?
sqlite3 eventtrace.sqlite3 "SELECT COUNT(*) FROM current_state;"

# Last 10 changes across all courts
sqlite3 eventtrace.sqlite3 \
  "SELECT court_id, field_name, old_value, new_value, duration_seconds, observed_time
   FROM event_trace ORDER BY observed_time DESC LIMIT 10;"

# Full history for one court (replace ID)
sqlite3 eventtrace.sqlite3 \
  "SELECT field_name, old_value, new_value, duration_seconds, observed_time
   FROM event_trace WHERE court_id='266385' ORDER BY observed_time DESC;"
```

---

## What gets tracked

Each row in `display_api.json` maps to one court bench. Fields tracked per bench:

| Field | Example |
|-------|---------|
| `judge_names` | `HON'BLE CHIEF JUSTICE SUJOY PAUL` |
| `cause_list_sr_no` | `27` |
| `cause_list_type_name` | `Daily List` |
| `case_no_string` | `WPA(P)/172/2026` |
| `pass_over` | `14,16,17,19` |
| `message` | (any court message) |
| `hearing_last_modified` | timestamp of last update |
| `__present__` | synthetic — `1` when court active, `0` when disappeared |

Every time a field value changes, EventTrace records: old value, new value, how long the old value lasted (`duration_seconds`).

---

## Configuration (all optional, via env vars)

```bash
CHD_URL=https://display.calcuttahighcourt.gov.in/principal.php
CHD_KEY_FIELDS=court_no          # field used as unique court ID
CHD_POLL_SECONDS=15              # how often to scrape
CHD_DB_PATH=./eventtrace.sqlite3
CHD_API_HOST=127.0.0.1
CHD_API_PORT=8009
```

---

## DB schema (quick reference)

| Table | Purpose |
|-------|---------|
| `current_state` | Latest full row per court (JSON blob) |
| `field_state` | Current value + `start_time` per (court, field) — acts as previous snapshot |
| `event_trace` | Append-only change log with `duration_seconds` |
