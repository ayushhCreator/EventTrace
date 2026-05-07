# EventTrace — Project Plan & Roadmap

**Version:** 1.0  
**Date:** 2026-04-23  
**Status:** Active Development

---

## Table of Contents

1. [What is EventTrace](#1-what-is-eventtrace)
2. [Current State](#2-current-state)
3. [Known Bugs](#3-known-bugs)
4. [Full Cost Breakdown](#4-full-cost-breakdown)
5. [Infrastructure Plan](#5-infrastructure-plan)
6. [Database Migration Plan](#6-database-migration-plan)
7. [CI/CD Pipeline](#7-cicd-pipeline)
8. [WhatsApp Bot Plan](#8-whatsapp-bot-plan)
9. [Feature Roadmap](#9-feature-roadmap)
10. [Value Proposition](#10-value-proposition)
11. [What Needs to Be Built](#11-what-needs-to-be-built)

---

## 1. What is EventTrace

EventTrace is a real-time monitoring and alert system for the **Calcutta High Court Principal Bench display board**.

It scrapes the live display board every 15 seconds, tracks changes in serial numbers, and notifies lawyers and litigants before their case is called — so they don't miss their hearing.

**Core problem it solves:**  
Lawyers sit outside courtrooms for hours not knowing when their matter will be called. Serial numbers change unpredictably. Missing your turn means adjournment — costs time and money.

**What EventTrace does:**
- Live display board at any URL, accessible from phone/laptop anywhere
- Tracks how long each serial has been running ("matter chalte 1h 23m ho gaya")
- VC Zoom links for virtual hearings, scraped daily from official cause list
- Telegram + WhatsApp bot: "alert me when Room 8 reaches serial 40, my case is 45"
- Full history — see what happened on any past date

---

## 2. Current State

### What is working
| Feature | Status |
|---------|--------|
| Display board scraper (15s poll) | ✅ Working |
| Change detection + event log | ✅ Working |
| VC Zoom link scraper (4×/day) | ✅ Working |
| Public UI (`/`) | ✅ Working |
| Admin/dev UI (`/admin`) | ✅ Working |
| Duration + Observed column | ✅ Working |
| Date-wise history view | ✅ Working |
| Telegram bot (@Eventtrace_bot) | ✅ Working |
| Serial alert notifications (Telegram) | ✅ Working |
| WhatsApp bot | ❌ Not built |
| Daily digest (morning summary) | ❌ Not built |
| CI/CD | ❌ Not set up |
| Production deployment | ❌ Local only |
| PostgreSQL migration | ❌ Still SQLite |
| HTTPS / domain | ❌ Not set up |
| User auth / login | ❌ Not built |

### Architecture (current)
```
3 local processes share one SQLite DB:

chd-run-monitor  →  Playwright scraper → change_detector → DB
chd-api          →  FastAPI reads DB, serves HTML + JSON
chd-bot          →  Telegram bot, reads/writes DB

DB: ./data/eventtrace.sqlite3 (WAL mode)
```

---

## 3. Known Bugs

### Critical
| # | Bug | Impact | Fix needed |
|---|-----|--------|------------|
| B1 | Popup close (×) works but clicking outside table area sometimes doesn't close popup | UX broken | Debug document click handler |
| B2 | If monitor restarts mid-day, `was_notified_today` check prevents re-notification even if serial moved past target during downtime | User misses alert | Track `last_notified_serial` not just date |
| B3 | VC scrape scheduler resets on monitor restart — loses track of which windows already ran today | Redundant Playwright launches | Persist scrape state to DB, not in-memory dict |

### Medium
| # | Bug | Impact | Fix needed |
|---|-----|--------|------------|
| B4 | Multi-bench rooms (37, 40, 238): two benches share one room, serial tracking uses max — could report wrong bench serial | Wrong alert timing | Track per bench, not per room |
| B5 | `cause_list_sr_no` ranges like "85-86" — notification logic takes upper bound only; could miss if user's case is at lower end | Wrong alert | Parse full range, check against both ends |
| B6 | `durationMap` in UI keyed by `court_id` (internal bench ID) but some courts have the same room_no across benches — duration column can show wrong court's duration | Wrong data shown | Key duration map by room_no instead |
| B7 | Bot `/today` truncates judge names at 40 chars but some names with multiple judges go over — formatting breaks on long names | Visual glitch | Wrap at word boundary |
| B8 | Date filter dropdown shows dates from `hearing_date` field — if monitor runs late night, hearing_date may be next day but display shows today's courts | Wrong date shown | Confirm hearing_date vs observed_time logic |

### Low
| # | Bug | Impact | Fix needed |
|---|-----|--------|------------|
| B9 | `chd-scrape-vc` CLI doesn't handle 404 gracefully when cause list not yet published | Confusing error | Show friendly message |
| B10 | Admin page stale banner checks `last_seen_time` but shows time in UTC not IST | Confusing for operators | Convert to IST in admin JS |
| B11 | Footer shows "Refreshed X:XX:XX IST" but seconds aren't meaningful — distracting | Minor UX | Show only HH:MM |

---

## 4. Full Cost Breakdown

### One-time costs
| Item | Cost | Notes |
|------|------|-------|
| Domain (`.com`) | ₹800–1,200/yr | Namecheap / GoDaddy / Porkbun (cheapest) |
| Domain (`.in`) | ₹700–900/yr | Option if .com taken |
| Twilio number | ~₹85/mo ($1) | WhatsApp-enabled number |
| Meta Business verification | Free | Required for WhatsApp API |
| SSL certificate | Free | Let's Encrypt via certbot |

### Monthly recurring costs (minimum viable)

| Item | Provider | Cost/month | Notes |
|------|----------|-----------|-------|
| VPS | Hetzner CAX11 | €3.29 (~₹300) | 2 vCPU ARM, 4GB RAM, 40GB SSD |
| Domain | Any registrar | ₹70–100 | Amortized monthly |
| WhatsApp number | Twilio | ₹85 | $1/mo |
| WhatsApp messages | Twilio | ₹0.60/msg | Outbound template only |
| Telegram | — | Free | No cost |
| **Total (no WhatsApp messages)** | | **~₹460/mo** | |

### Message cost estimate (WhatsApp)

| Users | Alerts/day | Messages/mo | Cost/mo |
|-------|-----------|-------------|---------|
| 50 | 1 each | 1,500 | ₹900 |
| 100 | 1 each | 3,000 | ₹1,800 |
| 500 | 1 each | 15,000 | ₹9,000 |

> Daily digest messages = template messages (paid).  
> Replies to user messages within 24h = session messages (free).

### Scale-up costs (when needed)

| Item | When | Cost |
|------|------|------|
| Hetzner CX22 upgrade | >200 concurrent users | +€3/mo |
| PostgreSQL (Supabase free tier) | >10K rows/day | Free up to 500MB |
| Supabase Pro | >500MB DB | $25/mo |
| Sentry (error tracking) | Production launch | Free tier sufficient |
| Uptime monitoring | Production launch | Free (UptimeRobot) |

### Total realistic monthly cost

| Stage | Cost/mo |
|-------|---------|
| Development / testing | ₹300 (VPS only) |
| Launch (< 100 users) | ₹800–1,200 |
| Growth (100–500 users) | ₹2,000–5,000 |

---

## 5. Infrastructure Plan

### Target architecture

```
Internet
    │
    ▼
Cloudflare (DNS + DDoS protection — free)
    │
    ▼
Hetzner VPS (Ubuntu 24.04 LTS)
    │
    ├─ Nginx (reverse proxy, SSL termination)
    │       eventtrace.in → localhost:8009
    │       /webhook/whatsapp → localhost:8009
    │
    ├─ eventtrace-api.service     (FastAPI / uvicorn)
    ├─ eventtrace-monitor.service (scraper + VC scheduler)
    ├─ eventtrace-bot.service     (Telegram bot)
    ├─ eventtrace-wbot.service    (WhatsApp bot — planned)
    │
    └─ PostgreSQL (local, or Supabase managed)
```

### Domain setup
1. Buy domain: e.g. `eventtrace.in` or `chclive.in`
2. Point DNS to Hetzner VPS IP via Cloudflare (free plan)
3. Cloudflare handles: DDoS, caching static assets, SSL (or use certbot)
4. Nginx config:
   ```nginx
   server {
       listen 443 ssl;
       server_name eventtrace.in;
       location / { proxy_pass http://127.0.0.1:8009; }
   }
   ```

### VPS setup steps
```bash
# On fresh Hetzner Ubuntu 24.04:
apt update && apt upgrade -y
apt install nginx certbot python3-pip git python3-venv -y

# Clone repo
git clone https://github.com/ayushhCreator/EventTrace.git /opt/eventtrace
cd /opt/eventtrace
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install --with-deps chromium

# Copy .env, set TELEGRAM_TOKEN, TWILIO creds
cp .env.example .env && nano .env

# Enable services
cp deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now eventtrace-api eventtrace-monitor eventtrace-bot
```

---

## 6. Database Migration Plan

### Why move from SQLite to PostgreSQL

| Issue | SQLite | PostgreSQL |
|-------|--------|------------|
| Concurrent writers | 1 at a time (WAL helps but limited) | Many concurrent |
| Remote access | File on disk only | Network accessible |
| Backups | Manual `cp` | pg_dump, automated |
| Full-text search | Basic | Full |
| Production reliability | OK for small scale | Industry standard |
| Managed hosting | No | Supabase, Neon, RDS |

**Threshold:** Migrate when monitor + API + bot + WhatsApp bot = 4 writers hitting DB simultaneously. Currently at 3 — fine with WAL. Add WhatsApp bot → migrate.

### Migration approach

**Step 1 — Add SQLAlchemy ORM layer** (replaces raw `sqlite3` calls in `db.py`)
```python
# db.py changes: sqlite3.connect() → SQLAlchemy engine
# Connection string from env: DATABASE_URL
# SQLite:     sqlite:///./data/eventtrace.sqlite3
# PostgreSQL: postgresql://user:pass@host/dbname
```

**Step 2 — Add Alembic for schema migrations**
```bash
pip install alembic sqlalchemy
alembic init migrations
# Each schema change = one migration file, versioned in git
```

**Step 3 — Data migration**
```bash
# Export SQLite → CSV → import to PostgreSQL
python scripts/migrate_to_postgres.py
```

**Step 4 — Switch DATABASE_URL in .env**
```
DATABASE_URL=postgresql://eventtrace:password@localhost/eventtrace
```

No code changes needed after Step 1 — SQLAlchemy abstracts the engine.

### Schema changes needed
- Add `users` table (for web auth, future)
- Add index on `vc_zoom_link(date)` (currently only indexed on PK)
- Add `whatsapp_subscriptions` table (separate from Telegram subscriptions)
- Rename `subscriptions` → `telegram_subscriptions` for clarity

---

## 7. CI/CD Pipeline

### Tool: GitHub Actions

**On every push to `main`:**
```
push → lint (ruff) → tests → build Docker image → deploy to VPS
```

### File: `.github/workflows/deploy.yml`

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/ruff-action@v1

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[test]"
      - run: pytest tests/ -v

  deploy:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST }}
          username: deploy
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /opt/eventtrace
            git pull origin main
            source .venv/bin/activate
            pip install -e . -q
            systemctl restart eventtrace-api eventtrace-monitor eventtrace-bot
```

### GitHub Secrets needed
| Secret | Value |
|--------|-------|
| `VPS_HOST` | Your Hetzner IP |
| `VPS_SSH_KEY` | Private SSH key for deploy user |
| `TELEGRAM_TOKEN` | Bot token (for tests) |

### Tests to write (currently none)
```
tests/
  test_db.py          — upsert, field_state, event_trace CRUD
  test_change_detector.py — apply_snapshot logic
  test_causelist_scraper.py — regex parsing on sample HTML
  test_api.py         — FastAPI TestClient, all endpoints
```

---

## 8. WhatsApp Bot Plan

### Provider: Twilio WhatsApp API

**Setup steps:**
1. Create Twilio account → $15 free credit
2. Enable WhatsApp Sandbox: send `join <keyword>` to `+1 415 523 8886`
3. Deploy VPS + HTTPS first (Twilio needs a public webhook URL)
4. Set webhook: Twilio Console → Messaging → WhatsApp → Sandbox settings → Webhook URL = `https://eventtrace.in/webhook/whatsapp`
5. Apply for dedicated number + message templates (takes 2-5 days)

### Commands (same as Telegram bot)
```
TODAY           — all active courts right now
STATUS 8        — current serial for room 8
WATCH 8 45      — alert when room 8 reaches serial 40
WATCH 8 45 3    — alert when room 8 reaches serial 42 (3 before)
UNWATCH 8       — cancel alert
LIST            — your active alerts
HELP            — usage guide
```

### Daily digest (new — not in Telegram bot yet)

Sent at **8:00 AM IST** to all WhatsApp subscribers:

```
📋 CHC Cause List — 24 Apr 2026

🏛 Room 1   → AD, Serial 1–92
📹 Room 2   → AD, Serial 1–33  [VC available]
📹 Room 8   → AD, Serial 1–135 [VC available]
🏛 Room 23  → OD, Serial 1–2   [In-person]
...

Reply WATCH <room> <serial> to set alert.
Reply STATUS <room> to check current serial.
```

Template message (needs Meta approval):
```
Name: eventtrace_daily_digest
Body: 📋 CHC Cause List — {{1}}\n\n{{2}}\n\nReply WATCH <room> <serial> to set an alert.
```

### New files needed
```
src/eventtrace/whatsapp_bot.py     — webhook handler + message sender
src/eventtrace/daily_digest.py     — builds and sends morning summary
```

New FastAPI routes:
```
POST /webhook/whatsapp   — Twilio sends inbound messages here
```

New systemd service:
```
eventtrace-wbot.service  — (optional, or integrate into api.py)
```

New env vars:
```
TWILIO_ACCOUNT_SID=ACxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

---

## 9. Feature Roadmap

### Phase 1 — Production-ready (next 2 weeks)
- [ ] Fix bugs B1–B6 (critical + medium)
- [ ] Deploy to Hetzner VPS
- [ ] Domain + HTTPS + Nginx
- [ ] GitHub Actions CI/CD
- [ ] Basic test suite
- [ ] Environment variable validation on startup

### Phase 2 — WhatsApp (2–4 weeks)
- [ ] `whatsapp_bot.py` — webhook handler
- [ ] Daily 8AM digest
- [ ] Twilio sandbox testing
- [ ] Apply for Meta template approval
- [ ] Go live with dedicated number

### Phase 3 — Database (4–6 weeks)
- [ ] SQLAlchemy ORM layer in `db.py`
- [ ] Alembic migrations
- [ ] Migrate to PostgreSQL
- [ ] `whatsapp_subscriptions` table
- [ ] `users` table (for future web login)

### Phase 4 — Scale & Polish (6–10 weeks)
- [ ] Web-based alert signup (no bot needed — user enters phone + room + serial on UI)
- [ ] Multi-bench awareness (correct serial per bench, not max per room)
- [ ] Cause list PDF parsing (some days HTML is not available)
- [ ] Original Side cause list scraping (currently only Appellate Side `AS`)
- [ ] Push notifications (PWA — works on Android home screen)
- [ ] Uptime monitoring (UptimeRobot — free)
- [ ] Error tracking (Sentry — free tier)

### Phase 5 — Business features (future)
- [ ] Lawyer profile page — all cases across rooms
- [ ] Case number search — find which room your case is in
- [ ] SMS fallback when WhatsApp not available
- [ ] Weekly/monthly hearing history PDF export
- [ ] API access for law firms (paid tier)

---

## 10. Value Proposition

### Who uses this
- **Lawyers** appearing in multiple courts on the same day
- **Clerks** managing briefs for senior advocates
- **Litigants** who travel long distances to attend hearings

### What they gain

| Without EventTrace | With EventTrace |
|-------------------|----------------|
| Sit outside court for 3-4 hours | Go for breakfast, get alerted when serial is close |
| Miss hearing because serial jumped | 15-second tracking + proactive alert |
| Don't know if court is sitting today | Live display board anywhere, any device |
| No idea who's sitting in which court | Real-time judge coram per room |
| Have to call clerk repeatedly for updates | WhatsApp/Telegram bot answers instantly |

### Competitive advantage
- **No login required** for the display board (public, open access)
- **VC Zoom links** automatically scraped and attached to alerts — unique feature
- **Duration tracking** ("matter 2h se chal raha hai") — tells you if court is moving slow
- **History** — see past days to understand a court's typical pace

### Monetization options (future)
- Free tier: display board access + Telegram bot
- ₹99/mo: WhatsApp alerts + daily digest
- ₹499/mo (law firms): multi-user, API access, case tracking

---

## 11. What Needs to Be Built

### Immediate (before first real users)

| Task | Effort | Priority |
|------|--------|----------|
| Fix bug B1 (popup close) | 1h | High |
| Fix bug B2 (notification on restart) | 2h | High |
| Fix bug B3 (VC scrape state in DB) | 2h | High |
| Fix bug B6 (duration map key) | 30m | High |
| Deploy to Hetzner | 3-4h | High |
| Nginx + HTTPS | 1h | High |
| GitHub Actions CI | 2h | Medium |
| `.env` validation on startup | 1h | Medium |
| Basic test suite (5 tests) | 3h | Medium |

### Next sprint

| Task | Effort | Priority |
|------|--------|----------|
| `whatsapp_bot.py` | 4h | High |
| Daily digest scheduler | 2h | High |
| SQLAlchemy ORM layer | 6h | Medium |
| Alembic setup | 2h | Medium |
| Fix bugs B4, B5 (multi-bench) | 4h | Medium |
| Web-based alert signup form | 4h | Low |

---

## Cost Summary Table

| Item | Monthly Cost |
|------|-------------|
| Hetzner CAX11 VPS | ₹300 |
| Domain (amortized) | ₹85 |
| Twilio WhatsApp number | ₹85 |
| WhatsApp messages (100 users) | ₹1,800 |
| Telegram | ₹0 |
| SSL (Let's Encrypt) | ₹0 |
| Cloudflare (DNS + proxy) | ₹0 |
| GitHub (CI/CD) | ₹0 |
| Sentry (error tracking) | ₹0 |
| UptimeRobot (monitoring) | ₹0 |
| **Total (100 users)** | **~₹2,270/mo** |
| **Total (launch, no users)** | **~₹470/mo** |

---

*Document maintained by the EventTrace dev team. Update after each major sprint.*
