# Dev Session — 23 April 2026

## What we built

### 1. DB moved to `data/` folder
- Moved `eventtrace.sqlite3` from project root → `data/eventtrace.sqlite3`
- Updated `config.py` default: `CHD_DB_PATH` now defaults to `./data/eventtrace.sqlite3`
- Added `data/.gitkeep` so the folder is tracked in git
- Updated `.gitignore` to cover `*.sqlite3-shm` and `*.sqlite3-wal` (WAL mode sidecar files)

### 2. Telegram bot — `@Eventtrace_bot`

New file: `src/eventtrace/telegram_bot.py`

Commands implemented:
| Command | What it does |
|---------|-------------|
| `/start` / `/help` | 3-step onboarding guide |
| `/today` | All active rooms right now — room no, current serial, judge, VC indicator |
| `/status <room>` | Current serial + VC link for one room |
| `/watch <room> <serial> [ahead]` | Subscribe: alert when serial is within `ahead` of your case |
| `/unwatch <room>` | Cancel subscription |
| `/list` | Your active alerts with current serials |

Bot also sends proactive notifications — after each display board poll, checks if any subscribed serial is within `look_ahead` threshold and fires a Telegram message including the VC Zoom link.

### 3. VC scrape scheduler (background thread in monitor)

`run_monitor.py` now starts a daemon thread `_vc_scheduler_thread` that:
- Wakes every 30 minutes
- Scrapes cause list for today's VC links at 4 IST windows: **00:00, 06:00, 08:00, 20:00**
- At 20:00+ IST also scrapes tomorrow's cause list (so links are ready before court opens)
- Tracks which `(date, window)` pairs have been scraped — avoids redundant Playwright launches

### 4. New CLI commands

| Command | Purpose |
|---------|---------|
| `chd-bot` | Run the Telegram bot (needs `TELEGRAM_TOKEN` in env) |
| `chd-scrape-vc [YYYY-MM-DD]` | Manual one-shot VC link scrape for a specific date |

### 5. Systemd user services

Three service files created at `~/.config/systemd/user/`:
- `eventtrace-api.service` — FastAPI server
- `eventtrace-monitor.service` — display board scraper + VC scheduler
- `eventtrace-bot.service` — Telegram bot

All read config from `~/The_Base/EventTrace/.env`. Enable with:
```bash
systemctl --user enable --now eventtrace-api eventtrace-monitor eventtrace-bot
```

### 6. Duration / Observed column in public UI

New column added to the display board table: **Duration / Seen**
- **Duration** — how long the current serial has been showing without changing (e.g. `1h 23m`)
- **Seen** — how long ago the monitor last observed this court (e.g. `seen 3m ago`)

Backend: new DB method `list_serial_start_times()` + new API endpoint `GET /field-durations` returns `{court_id: serial_start_time}` for all courts in one query — avoids per-row API calls.

### 7. Bot UX redesign

Initial bot was confusing — commands gave terse errors, no explanation of what "serial" meant. Redesigned:
- `/watch` with no args shows full explanation of every argument
- `/unwatch` with no args shows which rooms you're already watching
- `/list` shows current serial next to each alert so users know how far away they are
- Error messages include examples

---

## Problems we hit

### Stray SQLite WAL files in root
After moving DB to `data/`, the root still had `eventtrace.sqlite3-shm` and `eventtrace.sqlite3-wal`. Cause: the DB had been open when we ran `mv`. The files in root were then recreated by the OS as empty shells. Fixed by deleting them manually and adding `*.sqlite3-shm` / `*.sqlite3-wal` to `.gitignore`.

### Old bot command list cached in Telegram
After rewriting all bot handlers, the user still saw the old help text. Cause: the `chd-bot` process was still running old code. Fix: restart the service (`systemctl --user restart eventtrace-bot`). Also updated BotFather's `/setcommands` list.

### Duration/Observed not visible in public UI
Added Duration/Observed to the info popup (behind the `i` button click) — user expected it on the main table without any click. Fixed by adding a dedicated **4th column** to the board table, fetching all durations in a single `GET /field-durations` call during each 15-second refresh cycle.

### `ruff` output not showing in bash
`ruff check src/` was returning exit code 1 but stdout/stderr were swallowed by the tool. Workaround: redirect output to `/tmp/r.txt` then `cat` it. All checks passed (exit 0) once redirected correctly.

---

## Current system state

```
3 processes (run as systemd user services):
  eventtrace-api      → http://127.0.0.1:8009
  eventtrace-monitor  → polls display board every 15s, scrapes VC links 4×/day
  eventtrace-bot      → @Eventtrace_bot on Telegram

DB: ./data/eventtrace.sqlite3 (WAL mode, shared by all 3)

Tables:
  current_state       — latest full row per court
  field_state         — current value + start_time per (court, field)
  event_trace         — append-only change log
  vc_zoom_link        — Zoom URLs per (date, room_no)
  subscriptions       — Telegram alert subscriptions
  notification_log    — sent notification history
```

## Commits this session

```
4e862a6  feat: Duration/Seen as dedicated table column in public UI
b9a2249  feat: show Duration and Observed time in UI (info popup — superseded)
8039189  feat: redesign bot UX — /today, better onboarding, smarter errors
46b7ae6  chore: add .env.example for config
a2fef94  feat: Telegram bot, VC scrape scheduler, chd-bot CLI
7ba54a5  feat: VC link scraping, split UI, subscriptions schema, data/ folder
```

## What's next

- [ ] Nginx reverse proxy so UI is accessible on port 80/443
- [ ] Multi-bench support (one room, two benches — correct serial detection per bench)
- [ ] Bot: `/status` should show all benches in a room, not just max serial
- [ ] Notification: fire again if serial jumps past target without prior alert (monitor restart scenario)
