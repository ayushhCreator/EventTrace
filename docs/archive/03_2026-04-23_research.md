# EventTrace — Research & Implementation Plan

> Status: **Pre-approval research — answers incorporated, ready for implementation.**

---

## 1. UI Redesign

### Current state
The existing `ui.html` is a developer dashboard — two-column grid, event traces, dev/user toggle. It is not the public-facing display board end-users need.

### Goal
A **two-page UI** inside the same single-file `ui.html`:

| Page | Purpose |
|------|---------|
| `#display` (default) | Replicate the CHC display board look — table with Court, Judge(s), Serials; VC link button per row |
| `#admin` (dev toggle) | Existing EventTrace developer view (keep as-is) |

### Layout plan (mobile-first)
```
┌─────────────────────────────────────────┐
│  [CHC Logo]  Display Board — Principal  │  ← sticky header
│  [Date/time]  Auto-refresh: 15s  [↺]   │
├──────┬──────────────────┬───────────────┤
│ Court│ Judge(s) Coram   │ Serials  [VC] │  ← table rows
│  1   │ CHIEF JUSTICE…   │ AD 1–5   📹  │
│  2   │ JUSTICE X        │ WP 10–15 📹  │
└──────┴──────────────────┴───────────────┘
```

- **Mobile**: stack columns, serials truncated with expand button  
- **VC button**: only shows if a link exists for that court today  
- **Nav buttons** matching original site: Home · Principal Bench · Jalpaiguri · Port Blair · Official Website  
- No CAPTCHA (we bypass it server-side already)

### Key changes needed in `ui.html`
1. Add nav bar with original site links
2. Add a "display board" view driven by `/current-state` API
3. Add VC link column — fetched from new `/vc-links` endpoint
4. Keep existing EventTrace panel hidden behind Dev toggle

---

## 2. Database

### Current: SQLite (WAL mode)
**Good enough for this project.** Reasons to keep it:
- Single-process writes (monitor loop only writes)
- Read-only API — many readers are fine in WAL
- Zero ops: no server to manage, file-based backup
- Already working

### What to ADD (new tables in existing SQLite DB)

```sql
-- Daily VC links scraped from cause list HTML
CREATE TABLE IF NOT EXISTS vc_links (
  date       TEXT NOT NULL,          -- YYYY-MM-DD IST
  court_no   TEXT NOT NULL,          -- "1", "2", etc.
  vc_url     TEXT NOT NULL,
  scraped_at TEXT NOT NULL,          -- ISO UTC
  PRIMARY KEY (date, court_no)
);

-- User notification subscriptions (for Telegram bot)
CREATE TABLE IF NOT EXISTS subscriptions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id   TEXT NOT NULL,
  court_id      TEXT NOT NULL,       -- e.g. "1"
  field_name    TEXT NOT NULL,       -- e.g. "running_serial"
  trigger_value TEXT NOT NULL,       -- e.g. "AD 5" (notify when serial reaches this)
  created_at    TEXT NOT NULL
);

-- Notification delivery log (avoid duplicates)
CREATE TABLE IF NOT EXISTS notification_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_id      INTEGER REFERENCES subscriptions(id),
  sent_at     TEXT NOT NULL,
  payload     TEXT NOT NULL
);
```

### When to consider PostgreSQL
Only if you add **multiple write processes** (e.g., notification worker + monitor loop both writing simultaneously at high frequency) or need **LISTEN/NOTIFY** for push-based events. For current scale: **keep SQLite**.

---

## 3. Cause List Scraping — VC Links

### URL pattern
```
https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{DD}{MM}{YYYY}.html
```
Example: `cla23042026.html` = 23 Apr 2026

### HTML structure (from image + inspection)
Each court section looks like:
```
DAILY CAUSELIST
For Thursday The 23rd April 2026
COURT NO. 1
First Floor
Main Building
DIVISION BENCH (DB - I)
AT 10:30 AM
HON'BLE CHIEF JUSTICE SUJOY PAUL
HON'BLE JUSTICE PARTHA SARATHI SEN
...
VC LINK: https://calcuttahighcourt-gov-in.zoom.us/j/98477830007?pwd=...
```

### Extraction strategy

**Step 1 — Playwright fetch** (reuse existing session cookies, no CAPTCHA on this URL):
```python
async def fetch_causelist_html(date: date) -> str:
    dd = date.strftime("%d")
    mm = date.strftime("%m")
    yyyy = date.strftime("%Y")
    url = f"https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{dd}{mm}{yyyy}.html"
    # page.goto(url) — no auth needed, public endpoint
    return await page.content()
```

**Step 2 — Parse with regex** (no heavy DOM parser needed):
```python
import re

COURT_BLOCK = re.compile(
    r"COURT\s+NO\.\s*(\d+).*?VC\s+LINK\s*:\s*(https?://\S+)",
    re.DOTALL | re.IGNORECASE
)

def extract_vc_links(html: str) -> dict[str, str]:
    # Returns {court_no: vc_url}
    return {m.group(1): m.group(2).strip() for m in COURT_BLOCK.finditer(html)}
```

**Step 3 — Store in DB** (`vc_links` table above)

**Step 4 — Schedule**: Run once daily at ~8:00 AM IST (court lists published night before or early morning). Can be a cron job or called at monitor startup.

### New API endpoint
```
GET /vc-links?date=YYYY-MM-DD
Response: {"1": "https://zoom.us/...", "2": "https://zoom.us/...", ...}
```

### Mapping to display.json
The `display_api.json` already has `court_no` field. The mapping is:
```
display_api.json[i].court_no  ←→  vc_links.court_no
```
No ambiguity — both use the integer court number string.

In the UI, after fetching `/current-state` and `/vc-links`:
```js
const vcMap = await fetch('/vc-links?date=today').then(r => r.json());
// In each row render:
const vcUrl = vcMap[row.court_no];
if (vcUrl) {
  cell.innerHTML += `<a href="${vcUrl}" target="_blank" class="vc-btn">📹 VC</a>`;
}
```

---

## 4. Notification System — Telegram vs WhatsApp

### Recommendation: **Telegram**

| Factor | Telegram | WhatsApp |
|--------|----------|----------|
| Official bot API | Yes — free, no approval | No official API; workarounds violate ToS |
| Setup complexity | Low (BotFather, 5 min) | High (Meta Cloud API needs business approval) |
| Cost | Free forever | Paid after free tier |
| Reliability | High | Rate-limited, account bans risk |
| Programmatic | `python-telegram-bot` library | 3rd-party wrappers only |

### How it works

1. User messages your Telegram bot: `/watch 1 AD 5`  
   → "notify me for Court 1 when serial reaches AD 5"
2. Bot stores subscription in `subscriptions` table
3. Notification worker polls `event_trace` table every 15s
4. When `running_serial` for court 1 changes and contains "AD 5" or beyond → send message
5. Bot sends: `"Court 1 — Serial now AD 5 (was AD 3). Your matter AD 10 is approaching."`

### Trigger logic for serial tracking
Serial numbers like `AD 1, AD 2 ... AD 10` — extract numeric part, compare:
```python
def serial_reached(current: str, target: str) -> bool:
    # "AD 5" reached when current serial >= target - LOOK_AHEAD
    # e.g., notify when 5 serials before user's matter
    curr_num = int(re.search(r'\d+', current).group())
    target_num = int(re.search(r'\d+', target).group())
    return curr_num >= (target_num - LOOK_AHEAD)  # LOOK_AHEAD = 5 default
```

### New files needed
```
src/eventtrace/causelist_scraper.py   # VC link scraper
src/eventtrace/notifier.py            # Telegram bot + notification worker
src/eventtrace/telegram_bot.py        # /watch, /unwatch commands
```

---

## 5. Deployment Plan

### Stack
- **FastAPI** (already exists) — add VC links endpoint
- **SQLite WAL** — add 2 new tables  
- **Playwright** — reuse existing setup for causelist scraping
- **python-telegram-bot** — new dependency
- **Hosting**: Any Linux VPS (DigitalOcean $6/mo, Railway, Render free tier)

### Process model (production)
```
systemd / supervisor:
  eventtrace-monitor    # existing poll loop + causelist scraper daily
  eventtrace-api        # FastAPI (gunicorn + uvicorn workers)
  eventtrace-bot        # Telegram bot (polling or webhook)
```

### nginx config sketch
```nginx
location /ui { alias /app/src/eventtrace/ui.html; }
location /    { proxy_pass http://127.0.0.1:8009; }
```

---

## 6. DB — Critical Finding: Field Name Collision

The display API JSON already has a field called `vc_link` — but **it contains the building location** ("Main Building", "First Floor"), NOT a Zoom URL. Naming collision from upstream API.

Correct key for mapping is `room_no` (values: `"1"`, `"2"`, `"3"`...), not `court_no` (which is the internal bench ID like `266385`).

Updated `vc_links` table:
```sql
CREATE TABLE IF NOT EXISTS vc_links (
  date     TEXT NOT NULL,   -- YYYY-MM-DD IST
  room_no  TEXT NOT NULL,   -- "1", "2", "3" — matches display API room_no
  zoom_url TEXT NOT NULL,
  scraped_at TEXT NOT NULL,
  PRIMARY KEY (date, room_no)
);
```

Mapping in UI:
```js
const vcMap = await fetch('/vc-links').then(r => r.json()); // {room_no: zoom_url}
const zoomUrl = vcMap[row.room_no]; // room_no field from current-state API
```

---

## 7. Serial Format — DB Findings

`cause_list_sr_no` values from last 3 days: plain integers (`1`, `9`, `92`) and ranges (`5-6`, `85-86`). **No letter prefix.** The "AD", "WP" etc. are case types in `case_no_string` field.

Telegram bot notification command:
```
/watch <room_no> <my_serial> <look_ahead>
Example: /watch 1 10 3
→ Alert when Court 1 serial ≥ 7 (10 minus look_ahead of 3)
```

Trigger logic:
```python
def serial_reached(current_sr: str, target_sr: int, look_ahead: int) -> bool:
    nums = [int(x) for x in re.findall(r'\d+', current_sr)]
    return max(nums, default=0) >= (target_sr - look_ahead)
```

---

## 8. Answers to Open Questions

| # | Answer | Impact |
|---|--------|--------|
| Bot name | `Eventtrace_bot` | Register `@Eventtrace_bot` with BotFather |
| Look-ahead | User sets per subscription in `/watch` command | e.g. `/watch 1 10 3` |
| VC scrape schedule | 4 runs: 8 PM (D-1) → 12 AM → 6 AM → 8 AM IST | 4 cron entries |
| Auth | Display board public; bot auth via Telegram; dev view via URL hash | See below |
| Other benches | Later (Principal Bench only now) | — |
| Serial format | Pure integer or range — max of range for comparison | Confirmed from DB |

### Auth detail (Q4)

- **Display board**: fully public — no login. CHC data is public, lawyers need zero friction on mobile.
- **Bot subscriptions**: auth is Telegram itself — only real accounts can message bot.
- **Dev/admin panel**: URL hash `#admin` shows dev view. Optional: add `?token=SECRET` check in JS for minimal protection. No server-side user DB needed.

---

## 9. Implementation Order

| Step | Task | Files | Est. |
|------|------|-------|------|
| 1 | DB migration: `vc_links`, `subscriptions`, `notification_log` | `db.py` | 30m |
| 2 | `causelist_scraper.py`: Playwright → regex → store by `room_no` | new | 2h |
| 3 | Schedule 4× daily VC scrape (8PM/12AM/6AM/8AM IST) | `run_monitor.py` | 30m |
| 4 | API `GET /vc-links` returning `{room_no: zoom_url}` | `api.py` | 20m |
| 5 | UI: display board — nav bar, table, VC button, mobile layout | `ui.html` | 3h |
| 6 | Telegram bot: `/watch`, `/unwatch`, `/list` + notification worker | new files | 3h |
| 7 | Deployment: systemd, nginx, TELEGRAM_TOKEN env var | ops | 1h |

**Total: ~10h**
