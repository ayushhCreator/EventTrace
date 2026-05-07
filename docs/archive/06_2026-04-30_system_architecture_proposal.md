# Court Cause List Intelligence System
## Architecture & Tech Stack Proposal

**Prepared by:** EventTrace Engineering  
**Date:** 30 April 2026  
**Version:** 1.0  
**Status:** For Review

---

## Executive Summary

Every working day, thousands of lawyers in Calcutta spend significant time manually scanning
lengthy court cause lists to find their cases — checking which court, which serial number,
which judge. This is a solved problem in other domains. We are solving it for the legal community.

This document proposes a complete system to automatically extract, structure, and make
searchable the daily cause lists published by the Calcutta High Court. A lawyer should be
able to type a case number or their own name and immediately see: court number, serial
position, judge name, and Zoom link — for today or any past date.

---

## 1. High-Level Overview

### What the System Does (Non-Technical)

The Calcutta High Court publishes a daily cause list — a document listing every case
scheduled that day across all courtrooms. These documents are published as HTML pages on
the court's website. Currently:

- A lawyer must open the document manually
- Search through hundreds of entries
- Note down the courtroom and serial number
- Repeat this every single working day

Our system does this automatically:

1. **Downloads** the daily cause list at 8:00 PM every evening (published by the court for the next day)
2. **Reads and understands** the document — extracts every case, judge, courtroom, advocate
3. **Stores** all extracted data in a database
4. **Makes it searchable** through a clean web interface

A lawyer opens the website, types their name or a case number, and gets the answer in
under a second.

### Workflow: Input → Processing → Output

```
DAILY (8:00 PM IST)
        │
        ▼
┌─────────────────────┐
│  Court Website      │  HTML cause list published ~8 PM for next day
│  (public, no auth)  │
└────────┬────────────┘
         │  HTTP fetch
         ▼
┌─────────────────────┐
│  Parser Service     │  Extracts: court, judges, serial, case ref,
│  (Python)           │  petitioner, respondent, advocate, section
└────────┬────────────┘
         │  structured data
         ▼
┌─────────────────────┐
│  PostgreSQL DB      │  Stores structured case data, indexed for
│                     │  fast search by case number, name, advocate
└────────┬────────────┘
         │  SQL queries via API
         ▼
┌─────────────────────┐
│  FastAPI Backend    │  REST API — search, filter, retrieve
└────────┬────────────┘
         │  JSON responses
         ▼
┌─────────────────────┐
│  React Frontend     │  Clean search UI for lawyers
└─────────────────────┘
```

---

## 2. Frontend Design

### Recommended Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | React | 18 |
| Build Tool | Vite | 5 |
| Styling | Tailwind CSS | 4 |
| Data Fetching | TanStack Query (React Query) | 5 |
| Routing | React Router | 6 |
| Table Component | TanStack Table | 8 |
| Deployment | Vercel | — |

### Why This Stack

**React over Next.js:**  
Next.js is a server-side rendering framework designed for SEO-heavy public websites.
Our users are lawyers doing authenticated searches — SEO is irrelevant. React with Vite
is a pure client-side application: faster to build, simpler to deploy, and no server
infrastructure needed on the frontend side.

**Vite over Create React App:**  
Vite builds 10–20x faster than the legacy Create React App tooling. Hot reloading is
instant. Production builds are smaller and faster.

**TanStack Query:**  
Handles API data fetching with automatic caching, background refetching, and loading/error
states built in. Without it, developers write this boilerplate manually. With it, the search
results stay fresh automatically.

**Tailwind CSS:**  
No runtime cost, no separate CSS files to manage. Components look professional out of the
box. Consistent spacing and typography without writing custom CSS.

**Vercel:**  
One-command deployment from GitHub. Free tier is sufficient. Automatic preview deployments
on every pull request. Global CDN included — pages load fast regardless of user location.

---

### Key Frontend Features

#### 2.1 Search Interface

The primary screen is a search bar, prominent and centered. Three search modes:

- **By Case Number** — type `WPA/408/2024` or just `408/2024`; system finds it
- **By Party Name** — type petitioner or respondent name (partial match supported)
- **By Advocate Name** — type any part of the advocate's name

Date picker defaults to today. Can search historical dates.

#### 2.2 Filter Panel

Collapsible filter panel alongside search results:

- Court number (1, 2, 3 … or "All")
- Section (PIL, Group-IX, Tribunal, etc.)
- Hearing type (Motion / Hearing)
- Date range

#### 2.3 Results Display

Each result card shows:

```
┌─────────────────────────────────────────────────────┐
│  WPA(P)/408/2024          Serial: 7     Court: 1    │
│  PEOPLE FOR BETTER TREATMENT                        │
│  vs  STATE OF WEST BENGAL & ORS.                   │
│  Advocate: DR. KUNAL SAHA (PETITIONER IN PERSON)   │
│  Section: PIL (MOTION)                              │
│  Judges: HON'BLE CHIEF JUSTICE SUJOY PAUL          │
│           HON'BLE JUSTICE PARTHA SARATHI SEN        │
│  [Join VC Meeting]  [View Full Causelist]           │
└─────────────────────────────────────────────────────┘
```

VC link button only appears if a Zoom link exists for that court on that date.

#### 2.4 Today's Board View

A secondary tab showing the live display board — all active courts, current serials,
judges. Auto-refreshes every 15 seconds (feeds from existing monitor system).

#### 2.5 Scalability Considerations

- All search is server-side — frontend never queries the DB directly
- TanStack Query caches responses for the session — repeated searches cost zero
- Table virtualization (TanStack Table) handles rendering thousands of rows without lag
- Vercel CDN serves static assets globally — no performance degradation with more users

#### 2.6 Future Improvements

| Feature | Description |
|---------|------------|
| Lawyer dashboard | Personal case list — lawyer registers cases, sees them highlighted daily |
| Push notifications | WhatsApp/Telegram alert when their serial is approaching |
| Case history | All past dates a case appeared in cause lists |
| Bookmark cases | Save cases to a watchlist |
| Mobile app | PWA (Progressive Web App) wrapping same React code |

---

## 3. Backend Design

### Recommended Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.12 |
| API Framework | FastAPI | 0.110+ |
| HTML Parser | BeautifulSoup4 + lxml | 4.12 / 5.0 |
| HTTP Client | httpx | 0.27 |
| Database Driver | psycopg2-binary | 2.9 |
| Task Scheduler | APScheduler (or cron) | 3.10 |
| Deployment | Railway / Render | — |

### Why This Stack

**FastAPI over Django:**  
Django is a full-stack web framework built for rendering HTML pages. We are building a
pure API (JSON responses only). FastAPI is purpose-built for this: it is 3x faster than
Django REST Framework, generates OpenAPI documentation automatically, and has first-class
async support. Our existing codebase already uses FastAPI.

**Python over Node.js/Go:**  
The parsing workload (BeautifulSoup, regex, text processing) has the richest ecosystem
in Python. The existing monitor, scraper, and bot code is Python. Using the same language
means shared utilities, shared DB layer, and no context switching.

**httpx over requests:**  
httpx is the modern Python HTTP client with async support. Already a project dependency.
No additional library needed.

---

### Core Components

#### 3.1 HTML Parser (`parser/`)

Responsible for: fetching HTML → extracting clean text → splitting into court blocks →
parsing header metadata → parsing case records.

Key design decisions:
- Parse on **extracted plain text**, not raw HTML DOM — the causelist uses plain-text
  formatting, not structured HTML tables
- Regex patterns for case numbers, judge names, section headers, VC links
- Two-pass approach: pass 1 extracts court metadata (judges, bench, VC link); pass 2
  extracts individual cases within sections
- Idempotent: re-running the parser for the same date overwrites with upsert, never
  creates duplicates

#### 3.2 Normalization Layer (`services/normalization.py`)

Responsible for: converting raw extracted strings into canonical, searchable forms.

- **Case numbers:** `W.P.A. 123 OF 2024` → `WPA/123/2024`
- **Party names:** strip trailing `AND ORS.` variants, normalize to `& ORS.`
- **Advocate names:** strip prefixes (`Ld. Adv.`, `Mr.`, `Mrs.`)
- **Sections:** map `POLICE INACTION` → `GROUP_IX`, `PUBLIC INTEREST LITIGATION` → `PIL`
- **Encoding:** fix mojibake from the court's HTML (`â€"` → `–`)

#### 3.3 Database Layer (`models/`, `db.py`)

Two new tables added to existing PostgreSQL DB:

**`causelist_bench`** — one row per court per day
- Stores: court number, judges (array), bench type, VC link, jurisdiction notes,
  not-sitting flag

**`causelist_case`** — one row per case entry
- Stores: serial, case ref, case type, year, petitioner, respondent, advocate,
  section, hearing type, connected IAs

Full-text search index on petitioner + respondent + advocate (GIN/tsvector).  
Trigram index on advocate name for partial matching.  
B-tree index on case_ref for exact lookup.

#### 3.4 API Layer (`api/`)

Built on existing FastAPI app. New endpoints:

```
GET /causelist/{date}                      → all courts for a date
GET /causelist/{date}/court/{n}            → specific court
GET /causelist/{date}/court/{n}/serial/{s} → single case (used by bot)
GET /causelist/search                      → cross-date search
  ?case_ref=WPA/408/2024
  ?party=fakir+chand
  ?advocate=krishna+das
  ?date_from=2026-04-01&date_to=2026-04-30
  ?court_no=1&section=PIL
```

### Database: PostgreSQL

#### Why PostgreSQL over SQLite

| Concern | SQLite | PostgreSQL |
|---------|--------|-----------|
| Remote access (frontend on Vercel, backend on Railway) | ❌ File-based, local only | ✅ Network accessible |
| Full-text search | Limited | ✅ Native tsvector/tsquery |
| Trigram search (partial names) | ❌ No | ✅ pg_trgm extension |
| Array columns (judge list, IA list) | ❌ No | ✅ Native TEXT[] |
| JSONB for flexible raw storage | ❌ No | ✅ Native, indexable |
| Concurrent writers | Limited | ✅ MVCC, no locking |
| Managed hosting (Supabase free tier) | N/A | ✅ 500 MB free |

**Recommended hosting:** Supabase (managed PostgreSQL). Free tier: 500 MB storage,
auto-backups, built-in REST API, no infrastructure to manage.

### Search Optimization

| Search Type | Index | Query |
|------------|-------|-------|
| Exact case number | B-tree on `case_ref` | `WHERE case_ref = 'WPA/408/2024'` |
| Partial case number | — | `WHERE case_ref LIKE '%/408/2024'` |
| Party name (full-text) | GIN tsvector | `WHERE tsv @@ plainto_tsquery('fakir chand')` |
| Advocate (partial) | GIN trigram | `WHERE advocate ILIKE '%KRISHNA%'` |
| Today's serial | B-tree composite | `WHERE court_no='1' AND serial_no=7 AND list_date=TODAY` |

All search queries execute in under 50ms on a properly indexed table of 1M rows.

### Scalability Considerations

- **Large HTML files:** The parser processes text line by line, not loading entire DOM
  into memory. A 500-page causelist (unlikely) still processes in under 5 seconds.
- **Multiple courts:** The scraper loops over all court blocks sequentially. If needed,
  it can be parallelized with `asyncio.gather`.
- **Multiple establishments:** URL pattern change only. `AS` (Appellate Side) can become
  `JB` (Jalpaiguri), `PB` (Port Blair) with a config parameter.
- **Historical backfill:** Run scraper for any past date — same code, just pass the date.

---

## 4. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        LAWYER'S BROWSER                          │
│                     React SPA (Vercel CDN)                       │
└────────────────────────────┬─────────────────────────────────────┘
                             │  HTTPS REST (JSON)
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                       BACKEND SERVER                             │
│                  FastAPI (Railway / Render)                      │
│                                                                  │
│   ┌─────────────┐   ┌──────────────┐   ┌────────────────────┐   │
│   │  API Layer  │   │  Parser Svc  │   │  Monitor Loop      │   │
│   │  /causelist │   │  (scheduled) │   │  (existing)        │   │
│   │  /search    │   │  8:00 PM IST │   │  15s poll          │   │
│   └──────┬──────┘   └──────┬───────┘   └────────┬───────────┘   │
└──────────┼────────────────┼────────────────────┼───────────────┘
           │                │                     │
           │       ┌────────▼────────────────────▼──────────┐
           └──────▶│            PostgreSQL                   │
                   │         (Supabase managed)              │
                   │                                         │
                   │  causelist_bench   causelist_case       │
                   │  current_state     field_state          │
                   │  event_trace       subscriptions        │
                   └─────────────────────────────────────────┘
                                        ▲
                   ┌────────────────────┘
                   │  daily fetch
          ┌────────┴───────────┐
          │  Court Website     │
          │  calcuttahighcourt │
          │  .gov.in           │
          └────────────────────┘
```

### Data Pipeline (Detailed)

```
Court website publishes HTML at night
        │
        │  08:00 PM — scheduled trigger
        ▼
httpx.get(causelist_url) → raw HTML
        │
        ▼
BeautifulSoup → extract plain text (inner_text)
        │
        ▼
Split by "COURT NO. N" → list of court blocks
        │
        ├── For each block:
        │     ├── parse_court_header()  → bench metadata
        │     └── parse_cases()        → list of case dicts
        │
        ▼
normalize_case_numbers(), normalize_party_names(), normalize_advocates()
        │
        ▼
DB upsert (ON CONFLICT DO UPDATE — idempotent, re-runnable)
        │
        ▼
causelist_bench + causelist_case tables populated
        │
        │  Lawyer searches at 10:00 AM
        ▼
GET /causelist/search?advocate=krishna+das&date=2026-04-30
        │
        ▼
FastAPI → SQL query with GIN index → < 50ms
        │
        ▼
JSON response → React renders results
        │
        ▼
Lawyer sees: Court 1, Serial 1, MAT/911/2025, Zoom link
```

---

## 5. Folder Structure

### Backend

```
src/eventtrace/
├── api.py                  # FastAPI app — all endpoints
├── db.py                   # DB connection + all queries
├── config.py               # Settings (env vars)
├── run_monitor.py          # Display board polling loop
│
├── parser/
│   ├── __init__.py
│   ├── fetch.py            # httpx fetch + retry logic
│   ├── text_extract.py     # HTML → clean text
│   ├── block_splitter.py   # Split text by COURT NO.
│   ├── header_parser.py    # Extract court metadata from block
│   └── case_parser.py      # Extract individual case records
│
├── services/
│   ├── normalization.py    # Case number, name, advocate normalization
│   ├── causelist_ingest.py # Orchestrates fetch → parse → DB
│   └── scheduler.py        # APScheduler / cron trigger
│
└── ui/                     # Existing static HTML UI (legacy)
    ├── index.html
    └── admin.html
```

### Frontend

```
frontend/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── package.json
│
├── src/
│   ├── main.tsx            # App entry point
│   ├── App.tsx             # Router setup
│   │
│   ├── pages/
│   │   ├── SearchPage.tsx      # Main search interface
│   │   ├── BoardPage.tsx       # Live display board
│   │   └── CaseDetailPage.tsx  # Single case history view
│   │
│   ├── components/
│   │   ├── SearchBar.tsx       # Search input + mode selector
│   │   ├── FilterPanel.tsx     # Court/section/date filters
│   │   ├── CaseCard.tsx        # Single result display
│   │   ├── ResultsList.tsx     # Paginated results
│   │   ├── CourtBoardTable.tsx # Live board table
│   │   └── VCButton.tsx        # Zoom link button
│   │
│   ├── hooks/
│   │   ├── useCauselistSearch.ts  # TanStack Query search hook
│   │   ├── useBoardData.ts        # Live board polling hook
│   │   └── useDebounce.ts         # Input debounce
│   │
│   ├── services/
│   │   ├── api.ts              # All API call functions
│   │   └── queryClient.ts      # TanStack Query configuration
│   │
│   └── types/
│       └── index.ts            # TypeScript interfaces (Case, Bench, etc.)
```

---

## 6. Scalability & Performance

### Handling Large Cause Lists

The Calcutta High Court lists routinely contain 400–1,000 cases per day across 30+ courts.

- Parser processes text line by line — O(n) memory, never loads full DOM as object graph
- DB upserts are batched per court block — single transaction per court, not per case
- Expected ingest time for full day's list: **under 10 seconds**

### Handling Multiple Courts / Establishments

The system is parameterized by URL pattern. To add Jalpaiguri Circuit Bench:

```python
# config.py
ESTABLISHMENTS = {
    "AS": "https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{dd}{mm}{yyyy}.html",
    "JB": "https://calcuttahighcourt.gov.in/downloads/old_cause_lists/JB/cla{dd}{mm}{yyyy}.html",
}
```

No code changes to parser or DB. One config line per establishment.

### Handling Increasing Users

| Users | Architecture | Cost |
|-------|-------------|------|
| 0–100 | Single backend instance, Supabase free | ₹0 |
| 100–1,000 | Single backend, Supabase Pro | ~₹2,000/month |
| 1,000–10,000 | Read replica for search, Redis query cache | ~₹8,000/month |
| 10,000+ | Horizontal scaling, CDN for API responses | Custom |

The system is designed for the first two tiers. Scaling beyond requires infrastructure
changes but no code rewrites.

### Caching Strategy

| Layer | Cache | TTL |
|-------|-------|-----|
| Frontend | TanStack Query in-memory | Until page refresh |
| API | Response cache header `Cache-Control: max-age=300` | 5 minutes |
| DB | PostgreSQL shared_buffers (hot data stays in RAM) | Indefinite |
| Search results | Redis (future) | 60 seconds |

Cause list data for a given day is immutable after ~9 AM — aggressive caching is safe.

### Indexing Strategy

```
causelist_case table (expected: ~300 rows/day × 250 days = 75,000 rows/year)

B-tree indexes:
  - case_ref           → O(log n) exact lookup
  - (list_date, court_no) → O(log n) date+court filter
  - (bench_id, serial_no) → O(log n) serial lookup

GIN indexes:
  - tsvector(petitioner + respondent + advocate) → full-text search
  - advocate gin_trgm_ops → partial string match

At 75,000 rows, all queries execute in < 10ms.
At 750,000 rows (10 years), all queries still execute in < 50ms.
```

---

## 7. Timeline

### Phase 1: Parser Prototype — 1 Week

**Goal:** Working parser that correctly extracts all cases from a real HTML file.

| Day | Task |
|-----|------|
| 1 | Save 5 sample HTML files from real dates. Study structure variations. |
| 2–3 | Write `fetch.py`, `text_extract.py`, `block_splitter.py` |
| 4–5 | Write `header_parser.py`, `case_parser.py` |
| 6–7 | Test against all 5 sample files. Fix edge cases. Verify case counts match official list. |

**Deliverable:** Script that prints all extracted cases as JSON for any given date.

---

### Phase 2: Backend Development — 1.5 Weeks

**Goal:** Parser writes to DB; API endpoints work and return correct data.

| Day | Task |
|-----|------|
| 1–2 | Add `causelist_bench` + `causelist_case` tables to PostgreSQL |
| 3–4 | Write `normalization.py` — case numbers, names, advocates |
| 5–6 | Write `causelist_ingest.py` — orchestrate parse → normalize → DB upsert |
| 7–8 | Add API endpoints to `api.py` — `/causelist/{date}`, `/causelist/search` |
| 9–10 | Add scheduler — 8:00 PM IST daily trigger (cause list published by court ~8 PM for next day) |
| 11 | Backfill 30 days of historical data. Verify data quality. |

**Deliverable:** `GET /causelist/search?advocate=sharma` returns correct results.

---

### Phase 3: Frontend Development — 1.5 Weeks

**Goal:** Lawyer-facing search UI that works against live API.

| Day | Task |
|-----|------|
| 1 | Bootstrap Vite + React + Tailwind + TanStack Query |
| 2–3 | Build `SearchBar.tsx`, `FilterPanel.tsx` |
| 4–5 | Build `CaseCard.tsx`, `ResultsList.tsx` |
| 6–7 | Build `BoardPage.tsx` (live display board tab) |
| 8–9 | Add `VCButton.tsx` — Zoom link integration |
| 10–11 | Responsive design (mobile / tablet / desktop) |

**Deliverable:** Working UI connecting to backend API.

---

### Phase 4: Integration & Testing — 1 Week

**Goal:** Full system working end to end; data verified as correct.

| Day | Task |
|-----|------|
| 1–2 | Connect frontend to production backend (CORS, API URL config) |
| 3 | End-to-end test: scrape runs at 8:00 PM, lawyer finds their next-day cases by 8:30 PM |
| 4 | Edge case testing: Not Sitting courts, missing VC links, weekends |
| 5 | Performance testing: search under load |
| 6–7 | Bug fixes from testing |

---

### Phase 5: Deployment — 3 Days

| Day | Task |
|-----|------|
| 1 | Deploy backend to Railway (or Render). Set env vars. |
| 2 | Deploy frontend to Vercel. Point domain. |
| 3 | Monitor first live scrape. Verify in production. |

---

### Total Timeline Summary

| Phase | Duration |
|-------|---------|
| Phase 1: Parser Prototype | 1 week |
| Phase 2: Backend | 1.5 weeks |
| Phase 3: Frontend | 1.5 weeks |
| Phase 4: Integration & Testing | 1 week |
| Phase 5: Deployment | 3 days |
| **Total** | **~5.5 weeks** |

---

## 8. Why This Solution is Strong

### Scalable

The system is built from independent, loosely coupled components. The parser, the API,
the database, and the frontend can each be scaled independently. Adding Jalpaiguri
Circuit Bench requires one line of configuration, not a code rewrite. Adding 10x more
users requires a larger database instance, not a different architecture.

### Maintainable

- **Python** is readable, widely known, and has strong tooling
- **FastAPI** generates API documentation automatically — new developers understand the
  API without reading code
- **PostgreSQL** is the most mature open-source database; any developer knows it
- The parser is isolated in its own module — if the court changes their HTML format, only
  the parser changes, nothing else
- The normalization layer is a single file with a dictionary of rules — easy to extend

### Production-Ready Today

The backend is built on the existing EventTrace codebase which already runs in production:
monitoring 30+ courts, sending WhatsApp and Telegram notifications, handling daily scrapes.
The causelist parser is an extension of existing infrastructure, not a greenfield project.

### Path to Product

This system has clear commercial potential:

| Expansion | Effort | Value |
|-----------|--------|-------|
| All High Courts (Bombay, Delhi, Madras) | URL pattern per court | National coverage |
| District courts | Same parser, different HTML | 100x more cases |
| Subscription alerts | Already built in existing system | Immediate |
| Case tracking dashboard | Frontend feature | Lawyer retention |
| API for law firms | Auth layer + rate limiting | B2B revenue |
| Mobile app | PWA wrapper of existing frontend | Zero rebuild |

The core parsing and search engine built in Phase 1–2 is the hard part. Everything
above is an extension of it.

---

## Appendix A: Key Technologies Summary

| Technology | Purpose | Why |
|-----------|---------|-----|
| Python 3.12 | Backend language | Parsing ecosystem, existing codebase |
| FastAPI | API framework | Fast, async, auto-docs, already in use |
| BeautifulSoup4 + lxml | HTML parsing | Most mature Python HTML parser |
| httpx | HTTP client | Async, already a dependency |
| PostgreSQL 16 | Database | Full-text search, arrays, JSONB, network accessible |
| Supabase | Managed PostgreSQL | Free tier, backups, no infra |
| React 18 | Frontend framework | Ecosystem, widely known |
| Vite | Build tool | Fast builds, small bundles |
| Tailwind CSS v4 | Styling | Consistent, no runtime cost |
| TanStack Query | Data fetching | Caching, auto-refresh, loading states |
| Vercel | Frontend hosting | Free, CDN, zero config |
| Railway/Render | Backend hosting | Simple Python deployment, free tier |

---

## Appendix B: Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Court changes HTML format | Medium | `raw_text` column stores original; re-parse without data loss |
| Court website down at 8:00 PM | High (occasional) | Retry at 8:30 PM, 9:00 PM, 10:00 PM automatically |
| Encoding issues in HTML | Medium | `errors="replace"` + mojibake fix dictionary |
| Partial cause list (not all courts published) | Low | Upsert — partial data stored, full data added on retry |
| CAPTCHA added to cause list URL | Low | Playwright fallback (already in codebase) |

---

*End of Document*
