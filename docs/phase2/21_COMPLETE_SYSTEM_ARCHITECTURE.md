# EventTrace — Complete System Architecture
# Legal-Tech Platform: High Court Case Tracking + Advocate Billing

> Version: 1.0 | Date: 2026-05-06  
> Author: System Architecture Design  
> Scope: Production-grade SaaS — scraping → parsing → billing → notifications

---

## TABLE OF CONTENTS

1. [High-Level Architecture Overview](#1-high-level-architecture-overview)
2. [Recommended Tech Stack](#2-recommended-tech-stack)
3. [Database Schema Design](#3-database-schema-design)
4. [ECODE → Header → Case Mapping (Core Problem)](#4-ecode--header--case-mapping-core-problem)
5. [Microservices / Modules Breakdown](#5-microservices--modules-breakdown)
6. [Queue Architecture](#6-queue-architecture)
7. [PDF Processing Strategy](#7-pdf-processing-strategy)
8. [Search Indexing Strategy](#8-search-indexing-strategy)
9. [Storage Optimization Strategy](#9-storage-optimization-strategy)
10. [Caching Strategy](#10-caching-strategy)
11. [API Design](#11-api-design)
12. [Event Flow](#12-event-flow)
13. [State Machine: Case Tracking](#13-state-machine-case-tracking)
14. [Advocate Hierarchy & Billing System](#14-advocate-hierarchy--billing-system)
15. [Receipt Generation Workflow](#15-receipt-generation-workflow)
16. [User Permission Model](#16-user-permission-model)
17. [Background Jobs Architecture](#17-background-jobs-architecture)
18. [Cron Strategy](#18-cron-strategy)
19. [Deployment Architecture](#19-deployment-architecture)
20. [Monitoring & Logging Strategy](#20-monitoring--logging-strategy)
21. [Edge Cases Handling](#21-edge-cases-handling)
22. [AI Readiness Layer](#22-ai-readiness-layer)

---

## 1. High-Level Architecture Overview

```
╔══════════════════════════════════════════════════════════════════════════╗
║                         EXTERNAL DATA SOURCES                            ║
║  Calcutta HC Website   │  PDF Cause Lists   │  Order Sheets              ║
║  (principal.php)       │  (AS/OS/Monthly)   │  (daily orders)            ║
╚══════════════╤═════════╧══════════╤══════════╧══════════╤════════════════╝
               │                    │                       │
               │ Playwright         │ urllib3/PDF           │ urllib3
               ▼                    ▼                       ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                         INGESTION LAYER (Railway)                        ║
║                                                                          ║
║  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────┐   ║
║  │  LiveMonitor    │  │ CauselistScraper  │  │  OrderScraper        │   ║
║  │  (15s poll loop)│  │ (daily 20:30 IST) │  │  (daily 18:00 IST)   │   ║
║  └────────┬────────┘  └────────┬─────────┘  └──────────┬───────────┘   ║
║           │                    │                          │               ║
║           └──────────┬─────────┘                         │               ║
║                      │ push events                        │               ║
║                      ▼                                    ▼               ║
║           ┌─────────────────────┐           ┌─────────────────────┐     ║
║           │   Message Queue     │           │   PDF Parser        │     ║
║           │   (Redis / PG-based)│           │   + OCR Fallback    │     ║
║           └─────────┬───────────┘           └──────────┬──────────┘     ║
╚═════════════════════╪═══════════════════════════════════╪════════════════╝
                      │                                   │
                      ▼                                   ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                       PROCESSING LAYER                                   ║
║                                                                          ║
║  ChangeDetector → EventEmitter → AppearanceClassifier → BillingTrigger  ║
║  ECODEMapper → CaseIndexer → OrderMatcher → AuditLogger                 ║
╚══════════════════════════════╤═══════════════════════════════════════════╝
                               │ write
                               ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                       STORAGE LAYER (Supabase Postgres)                  ║
║                                                                          ║
║  Core:         event_trace, field_state, current_state                   ║
║  Causelist:    causelist_bench, causelist_ecode, causelist_case           ║
║  Orders:       court_order, order_case_map                               ║
║  Advocate:     advocate_profile, law_firm, firm_member                   ║
║  Billing:      matter, billing_entry, invoice, receipt                   ║
║  Users:        user, role, subscription, audit_log                       ║
╚══════════════════════════════╤═══════════════════════════════════════════╝
                               │
           ┌───────────────────┼────────────────────┐
           │ REST (FastAPI)     │ WebSocket (Realtime)│ Search (PG-FTS)
           ▼                   ▼                      ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                       API LAYER (Railway FastAPI)                        ║
║  /causelist  /search  /billing  /advocate  /orders  /auth  /admin       ║
╚══════════════════════════════╤═══════════════════════════════════════════╝
                               │
╔══════════════════════════════╧═══════════════════════════════════════════╗
║                       FRONTEND (Vercel)                                  ║
║  React + Vite + TypeScript + Tailwind + TanStack Query                  ║
║  Pages: Causelist / Search / Dashboard / Billing / Firm / Admin         ║
╚══════════════════════════════╤═══════════════════════════════════════════╝
                               │ triggers
╔══════════════════════════════╧═══════════════════════════════════════════╗
║                       NOTIFICATION LAYER                                 ║
║  WhatsApp (MSG91/WATI) │ Email (Resend) │ In-app (Supabase Realtime)    ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 2. Recommended Tech Stack

### Backend
| Component | Choice | Reason |
|---|---|---|
| API Framework | FastAPI (Python 3.12) | Already deployed, async, auto-docs |
| Scraping | Playwright + urllib3 | Playwright for JS-rendered pages, urllib3 for static HTML |
| PDF Parsing | pdfplumber + PyMuPDF | pdfplumber for text extraction, PyMuPDF for layout analysis |
| OCR Fallback | Tesseract via pytesseract | When PDF is image-based (scanned orders) |
| Queue | PostgreSQL SKIP LOCKED | No new infra needed — PG acts as queue |
| Task Runner | APScheduler (in-process) | Cron + interval jobs, no Redis needed at this scale |
| ORM/DB | psycopg2 (raw SQL, current) → SQLAlchemy 2.0 (future) | Migration path exists |
| Migrations | Alembic | Versioned schema changes |
| Receipt PDF | WeasyPrint or ReportLab | HTML→PDF (WeasyPrint) or precise layout (ReportLab) |
| Auth | Supabase Auth (JWT) + FastAPI dependency | RLS enforcement at DB layer |

### Database
| Component | Choice | Reason |
|---|---|---|
| Primary DB | Supabase Postgres | Auth, RLS, Realtime, FTS, backups — all built in |
| Search | Postgres GIN + tsvector | No Elasticsearch needed at this scale |
| Cache | Redis (Upstash free tier) | Query caching, rate limiting |
| File Storage | Supabase Storage | PDFs, receipts, order documents |

### Frontend
| Component | Choice | Reason |
|---|---|---|
| Framework | React 18 + Vite | Already in use |
| Styling | Tailwind CSS | Already in use |
| State | TanStack Query | Already in use |
| Charts | Recharts | Lightweight, good for timelines |
| PDF Viewer | react-pdf | View orders/receipts in-browser |
| Forms | React Hook Form + Zod | Type-safe form validation |

### Infrastructure
| Component | Choice | Reason |
|---|---|---|
| Backend hosting | Railway | Already deployed |
| Frontend | Vercel | CDN, auto-deploy |
| Database | Supabase | See Section 1 of product spec |
| Monitoring | Sentry + Supabase Dashboard | Error tracking + query perf |
| Notifications | MSG91 (OTP + WhatsApp) + Resend (email) | Already integrated for OTP |

---

## 3. Database Schema Design

### 3.1 Core Entities (normalized, production-grade)

#### `causelist_bench` (already exists, extended)
```sql
CREATE TABLE causelist_bench (
  id            SERIAL PRIMARY KEY,
  list_date     DATE NOT NULL,
  court_no      TEXT NOT NULL,
  bench_label   TEXT,                    -- "DIVISION BENCH (DB-IX)"
  judges_json   JSONB NOT NULL DEFAULT '[]',
  side          TEXT NOT NULL,           -- 'APPELLATE SIDE' | 'ORIGINAL SIDE'
  list_type     TEXT NOT NULL,           -- 'DAILY' | 'MONTHLY'
  jurisdiction  TEXT,                    -- full header text from order sheet
  not_sitting   BOOLEAN DEFAULT FALSE,
  vc_link       TEXT,
  source_id     TEXT,
  scraped_at    TIMESTAMPTZ,
  UNIQUE(list_date, court_no, side, list_type)
);
```

#### `causelist_ecode` (NEW — normalized ECODE/section entity)
```sql
CREATE TABLE causelist_ecode (
  id            SERIAL PRIMARY KEY,
  bench_id      INT NOT NULL REFERENCES causelist_bench(id) ON DELETE CASCADE,
  ecode         TEXT NOT NULL,           -- "GROUP_IX", "PIL", "CONTEMPT", etc.
  display_name  TEXT NOT NULL,           -- full human label from PDF
  subsection    TEXT,                    -- subsection label if any
  header_text   TEXT,                    -- full extracted header block text
  position      INT NOT NULL DEFAULT 0, -- order within bench
  UNIQUE(bench_id, ecode, subsection)
);

CREATE INDEX idx_causelist_ecode_bench ON causelist_ecode(bench_id);
```

**This is the normalized ECODE table.**  
- One row per distinct ECODE per bench.  
- Header text stored ONCE here, not repeated per case.  
- Cases point to this via FK.

#### `causelist_case` (extended to reference ecode)
```sql
CREATE TABLE causelist_case (
  id            SERIAL PRIMARY KEY,
  bench_id      INT NOT NULL REFERENCES causelist_bench(id) ON DELETE CASCADE,
  ecode_id      INT REFERENCES causelist_ecode(id),   -- NEW FK
  list_date     DATE NOT NULL,
  court_no      TEXT NOT NULL,
  serial_no     INT NOT NULL,
  case_ref      TEXT,
  case_type     TEXT,
  case_number   TEXT,
  case_year     INT,
  petitioner    TEXT,
  respondent    TEXT,
  advocate      TEXT,
  pro_se        BOOLEAN DEFAULT FALSE,
  ia_numbers    JSONB DEFAULT '[]',
  section       TEXT,                    -- kept for backward compat
  subsection    TEXT,
  hearing_type  TEXT,
  appearance_type TEXT,                  -- 'MOTION'|'HEARING'|'ADJOURNED'|'PASSED_OVER'
  scraped_at    TIMESTAMPTZ,
  search_vector TSVECTOR,               -- FTS column (auto-updated via trigger)
  UNIQUE(bench_id, serial_no)
);

-- FTS trigger
CREATE INDEX idx_causelist_case_fts ON causelist_case USING GIN(search_vector);
CREATE INDEX idx_causelist_case_ref ON causelist_case(case_ref);
CREATE INDEX idx_causelist_case_date ON causelist_case(list_date);
CREATE INDEX idx_causelist_case_ecode ON causelist_case(ecode_id);

CREATE OR REPLACE FUNCTION update_case_search_vector()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.case_ref, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.petitioner, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.respondent, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.advocate, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_case_search_vector
  BEFORE INSERT OR UPDATE ON causelist_case
  FOR EACH ROW EXECUTE FUNCTION update_case_search_vector();
```

#### `court_order`
```sql
CREATE TABLE court_order (
  id            SERIAL PRIMARY KEY,
  order_date    DATE NOT NULL,
  court_no      TEXT NOT NULL,
  order_no      TEXT,                    -- sequential order number if assigned
  file_url      TEXT,                    -- Supabase Storage URL
  file_hash     TEXT UNIQUE,             -- SHA-256 for dedup
  ocr_text      TEXT,                    -- extracted text (nullable if native PDF)
  is_ocr        BOOLEAN DEFAULT FALSE,
  status        TEXT DEFAULT 'pending',  -- 'pending'|'processed'|'matched'|'error'
  scraped_at    TIMESTAMPTZ,
  processed_at  TIMESTAMPTZ
);

CREATE INDEX idx_court_order_date ON court_order(order_date, court_no);
```

#### `order_case_map`
```sql
CREATE TABLE order_case_map (
  id            SERIAL PRIMARY KEY,
  order_id      INT NOT NULL REFERENCES court_order(id),
  case_ref      TEXT NOT NULL,
  court_no      TEXT,
  confidence    FLOAT DEFAULT 1.0,       -- 1.0=exact, <1.0=fuzzy match
  match_method  TEXT,                    -- 'exact'|'ocr_fuzzy'|'manual'
  UNIQUE(order_id, case_ref)
);
```

#### `advocate_profile`
```sql
CREATE TABLE advocate_profile (
  id                SERIAL PRIMARY KEY,
  user_id           UUID REFERENCES auth.users(id),   -- nullable: not all advocates are platform users
  enrollment_no     TEXT UNIQUE,           -- Bar Council enrollment
  full_name         TEXT NOT NULL,
  aliases           TEXT[],               -- alternate name spellings
  role              TEXT NOT NULL,        -- see hierarchy below
  bar_council       TEXT,                 -- 'CALCUTTA'|'SUPREME'|'DELHI' etc.
  phone             TEXT[],
  email             TEXT[],
  pan_no            TEXT,
  gstin             TEXT,
  upi_id            TEXT,
  bank_account_json JSONB,               -- {bank, ifsc, account_no, name}
  practice_areas    TEXT[],              -- ['CIVIL','CRIMINAL','CONSTITUTIONAL']
  firm_id           INT REFERENCES law_firm(id),
  senior_id         INT REFERENCES advocate_profile(id),  -- supervising advocate
  digital_sig_url   TEXT,               -- Supabase Storage URL
  is_verified       BOOLEAN DEFAULT FALSE,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  search_vector     TSVECTOR
);

CREATE INDEX idx_advocate_fts ON advocate_profile USING GIN(search_vector);
CREATE INDEX idx_advocate_enrollment ON advocate_profile(enrollment_no);
CREATE INDEX idx_advocate_name ON advocate_profile USING GIN(aliases);
```

#### `law_firm`
```sql
CREATE TABLE law_firm (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  aliases     TEXT[],
  gstin       TEXT,
  pan_no      TEXT,
  address     TEXT,
  phone       TEXT,
  email       TEXT,
  logo_url    TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

#### `matter` (a case tracked by a firm/advocate for a client)
```sql
CREATE TABLE matter (
  id              SERIAL PRIMARY KEY,
  firm_id         INT REFERENCES law_firm(id),
  client_id       INT REFERENCES advocate_profile(id),  -- or separate client table
  case_ref        TEXT NOT NULL,          -- e.g. WPA/71/2026
  case_title      TEXT,                   -- "RUPA PAUL vs STATE OF WB"
  court_no        TEXT,
  opened_at       DATE,
  closed_at       DATE,
  status          TEXT DEFAULT 'active',  -- 'active'|'disposed'|'stayed'
  billing_mode    TEXT DEFAULT 'appearance', -- 'appearance'|'retainer'|'fixed'
  retainer_amount NUMERIC(12,2),
  notes           TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_matter_case_ref ON matter(case_ref);
CREATE INDEX idx_matter_firm ON matter(firm_id);
```

#### `matter_member` (which advocates are on this matter)
```sql
CREATE TABLE matter_member (
  id              SERIAL PRIMARY KEY,
  matter_id       INT NOT NULL REFERENCES matter(id) ON DELETE CASCADE,
  advocate_id     INT NOT NULL REFERENCES advocate_profile(id),
  role            TEXT NOT NULL,  -- 'SENIOR_COUNSEL'|'AOR'|'JUNIOR'|'CLERK'
  revenue_share   NUMERIC(5,2),   -- percentage (0-100)
  fee_per_appearance NUMERIC(12,2),
  joined_at       DATE,
  left_at         DATE,
  UNIQUE(matter_id, advocate_id)
);
```

#### `billing_entry`
```sql
CREATE TABLE billing_entry (
  id              SERIAL PRIMARY KEY,
  matter_id       INT NOT NULL REFERENCES matter(id),
  advocate_id     INT REFERENCES advocate_profile(id),
  entry_date      DATE NOT NULL,
  entry_type      TEXT NOT NULL,         -- 'IN_COURT'|'OUT_OF_COURT'|'CLERK'|'SENIOR_FEE'|'MISC'
  description     TEXT,
  quantity        NUMERIC(8,2) DEFAULT 1, -- hours for out-of-court, appearances for in-court
  unit_amount     NUMERIC(12,2) NOT NULL,
  total_amount    NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_amount) STORED,
  gst_applicable  BOOLEAN DEFAULT TRUE,
  gst_rate        NUMERIC(5,2) DEFAULT 18.00,
  causelist_case_id INT REFERENCES causelist_case(id),  -- link to appearance
  order_id        INT REFERENCES court_order(id),        -- link to order
  is_invoiced     BOOLEAN DEFAULT FALSE,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_billing_entry_matter ON billing_entry(matter_id);
CREATE INDEX idx_billing_entry_date ON billing_entry(entry_date);
```

#### `invoice`
```sql
CREATE TABLE invoice (
  id              SERIAL PRIMARY KEY,
  invoice_no      TEXT UNIQUE NOT NULL,  -- "INV-2026-0001"
  matter_id       INT NOT NULL REFERENCES matter(id),
  firm_id         INT REFERENCES law_firm(id),
  client_name     TEXT NOT NULL,
  client_address  TEXT,
  client_gstin    TEXT,
  issue_date      DATE NOT NULL DEFAULT CURRENT_DATE,
  due_date        DATE,
  subtotal        NUMERIC(12,2) NOT NULL,
  gst_amount      NUMERIC(12,2) NOT NULL,
  total           NUMERIC(12,2) NOT NULL,
  paid_amount     NUMERIC(12,2) DEFAULT 0,
  status          TEXT DEFAULT 'draft',  -- 'draft'|'sent'|'paid'|'partial'|'cancelled'
  pdf_url         TEXT,                  -- Supabase Storage
  notes           TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  sent_at         TIMESTAMPTZ,
  paid_at         TIMESTAMPTZ
);
```

#### `audit_log`
```sql
CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID,
  action      TEXT NOT NULL,      -- 'CREATE_INVOICE'|'SCRAPE_CAUSELIST' etc.
  entity_type TEXT,
  entity_id   TEXT,
  before_json JSONB,
  after_json  JSONB,
  ip_address  INET,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user ON audit_log(user_id, created_at DESC);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
```

#### `scrape_job` (queue table)
```sql
CREATE TABLE scrape_job (
  id          BIGSERIAL PRIMARY KEY,
  job_type    TEXT NOT NULL,       -- 'CAUSELIST'|'ORDER'|'LIVE'
  target_date DATE,
  target_url  TEXT,
  status      TEXT DEFAULT 'pending', -- 'pending'|'running'|'done'|'error'
  attempts    INT DEFAULT 0,
  error_msg   TEXT,
  result_json JSONB,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  started_at  TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  UNIQUE(job_type, target_date, target_url)  -- idempotent: no duplicate jobs
);

CREATE INDEX idx_scrape_job_pending ON scrape_job(status, created_at)
  WHERE status = 'pending';
```

---

## 4. ECODE → Header → Case Mapping (Core Problem)

### The Problem (visual)
```
PDF Cause List Structure:
─────────────────────────
COURT 3 — JUSTICE SHAMPA SARKAR
  DIVISION BENCH (DB-IX) APPELLATE SIDE

  ┌─ ECODE: GROUP-IX (POLICE INACTION) ───────────────────────┐
  │  Header text: "For hearing of group-IX police inaction..."  │
  │  X-list notes: "All matters involving PILs on..."           │
  ├──────────────────────────────────────────────────────────── │
  │  1. WPA/71/2026   — RUPA PAUL vs STATE            Adv: X   │
  │  2. WPA/95/2026   — MOHAN DAS vs UNION OF INDIA  Adv: Y   │
  │  3. WPA/219/2026  — JAGAN NATH vs KOLKATA MC     Adv: Z   │
  └─────────────────────────────────────────────────────────────┘

  ┌─ ECODE: PIL (PUBLIC INTEREST LITIGATION) ──────────────────┐
  │  Header text: "PIL matters for motion hearing..."            │
  ├──────────────────────────────────────────────────────────── │
  │  4. WP/664/2025   — ABC vs STATE                 Adv: A   │
  └─────────────────────────────────────────────────────────────┘
```

### The Solution: 3-Level Hierarchy

```
causelist_bench (Court 3, 2026-05-06, APPELLATE SIDE, DAILY)
       │
       ├──→ causelist_ecode [GROUP_IX]
       │         header_text = "For hearing of group-IX..."
       │         position = 1
       │         │
       │         ├──→ causelist_case [serial=1, case_ref=WPA/71/2026]
       │         ├──→ causelist_case [serial=2, case_ref=WPA/95/2026]
       │         └──→ causelist_case [serial=3, case_ref=WPA/219/2026]
       │
       └──→ causelist_ecode [PIL]
                 header_text = "PIL matters for motion..."
                 position = 2
                 │
                 └──→ causelist_case [serial=4, case_ref=WP/664/2025]
```

### Why this structure wins

| Concern | Naive approach | This design |
|---|---|---|
| Header stored per case | Yes → huge duplication | No → stored once per ECODE |
| Query: "all cases under ECODE X" | Full table scan | `WHERE ecode_id = ?` — O(1) index |
| Query: "header for case Y" | JOIN hell | Single JOIN: case → ecode |
| Search by ECODE | LIKE on text | Exact match on `ecode` column |
| Many-to-one guaranteed | No | FK constraint enforces it |
| Storage | Headers repeated N times | Headers stored once |

### Query patterns

```sql
-- Get all cases under an ECODE for a bench (fast)
SELECT cc.* FROM causelist_case cc
WHERE cc.ecode_id = $1
ORDER BY cc.serial_no;

-- Get ECODE header for a case (single join)
SELECT ce.header_text, ce.display_name, ce.subsection
FROM causelist_case cc
JOIN causelist_ecode ce ON ce.id = cc.ecode_id
WHERE cc.id = $1;

-- Get full bench with ECODE groups (structured response)
SELECT 
  ce.ecode, ce.display_name, ce.header_text,
  json_agg(cc.* ORDER BY cc.serial_no) AS cases
FROM causelist_ecode ce
JOIN causelist_case cc ON cc.ecode_id = ce.id
WHERE ce.bench_id = $1
GROUP BY ce.id
ORDER BY ce.position;

-- Search cases + include their ECODE header
SELECT cc.case_ref, cc.petitioner, ce.display_name AS ecode_label
FROM causelist_case cc
LEFT JOIN causelist_ecode ce ON ce.id = cc.ecode_id
WHERE cc.search_vector @@ plainto_tsquery('english', $1)
LIMIT 50;
```

### Parser integration

```python
# causelist_parser.py — parse_court_block() output structure

{
  "bench": {
    "court_no": "3",
    "list_date": "2026-05-06",
    "bench_label": "DIVISION BENCH (DB-IX)",
    "judges": ["JUSTICE SHAMPA SARKAR"],
    "jurisdiction_notes": "...full header text...",
    "side": "APPELLATE SIDE",
    "list_type": "DAILY"
  },
  "ecodes": [                              # NEW
    {
      "ecode": "GROUP_IX",
      "display_name": "GROUP - IX (POLICE INACTION)",
      "subsection": "FOR MOTION HEARING",
      "header_text": "...full extracted header block...",
      "position": 1,
      "cases": [
        {"serial_no": 1, "case_ref": "WPA/71/2026", ...},
        {"serial_no": 2, "case_ref": "WPA/95/2026", ...}
      ]
    },
    {
      "ecode": "PIL",
      "display_name": "PUBLIC INTEREST LITIGATION",
      "position": 2,
      "cases": [...]
    }
  ]
}
```

### Storage estimate with this design

```
45MB/week problem breakdown:
- raw_text column per case: ~500 bytes × 50,000 cases = 25MB  ← DROP THIS
- header_text stored per case (duplicate): ~2KB × 50,000 = 100MB  ← AVOID

With normalized ECODE table:
- header_text stored once per ECODE: ~2KB × 200 ECODEs/day = 400KB/day
- Case row without raw_text: ~300 bytes × 7,000 cases/day = 2.1MB/day
- Total: ~2.5MB/day vs ~7MB/day → 65% reduction
```

---

## 5. Microservices / Modules Breakdown

### Service map
```
┌─────────────────────────────────────────────────────────────┐
│  INGESTION SERVICES                                          │
│                                                              │
│  live-monitor       → scrape display_api.json every 15s     │
│  causelist-scraper  → fetch + parse daily cause list HTML   │
│  order-scraper      → fetch daily order PDFs                │
│  backfill-worker    → historical data ingestion             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  PROCESSING SERVICES                                         │
│                                                              │
│  change-detector    → diff live snapshot → emit events      │
│  appearance-engine  → classify appearance type              │
│  order-matcher      → match orders to cases                 │
│  billing-trigger    → auto-create billing entries           │
│  notification-worker→ send alerts on matches                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  API SERVICE (FastAPI)                                       │
│                                                              │
│  /causelist         → browse/search cause lists             │
│  /orders            → order tracking                        │
│  /advocate          → advocate directory                    │
│  /billing           → billing management                    │
│  /auth              → JWT auth                              │
│  /admin             → admin operations                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  SCHEDULED JOBS                                              │
│                                                              │
│  daily-causelist    → 20:30 IST (next day's list)           │
│  daily-orders       → 18:00 IST (today's orders)            │
│  daily-alerts       → 07:00 IST (morning hearing alerts)    │
│  weekly-backup      → Sunday 02:00 IST                      │
└─────────────────────────────────────────────────────────────┘
```

### Module boundaries (SOLID)
```
src/eventtrace/
├── scraping/
│   ├── live_monitor.py      # Playwright poll loop
│   ├── causelist_scraper.py # HTML fetch + routing
│   └── order_scraper.py     # PDF fetch + OCR fallback
├── parsing/
│   ├── causelist_parser.py  # HTML → structured dicts
│   ├── order_parser.py      # PDF → case refs + text
│   └── ocr_engine.py        # Tesseract wrapper
├── processing/
│   ├── change_detector.py   # diff + event emission
│   ├── appearance_engine.py # classify appearance type
│   ├── order_matcher.py     # match orders to causelist cases
│   └── billing_trigger.py  # auto billing entry creation
├── storage/
│   ├── repositories/
│   │   ├── causelist.py     # causelist_bench/ecode/case CRUD
│   │   ├── orders.py        # court_order CRUD
│   │   ├── advocate.py      # advocate_profile CRUD
│   │   ├── billing.py       # matter/invoice CRUD
│   │   └── audit.py         # audit_log writes
│   └── db.py                # connection factory
├── services/
│   ├── billing_service.py   # billing business logic
│   ├── invoice_service.py   # invoice generation
│   ├── receipt_service.py   # PDF receipt generation
│   └── notification_service.py
├── routes/
│   ├── causelist.py
│   ├── orders.py
│   ├── advocate.py
│   ├── billing.py
│   ├── auth.py
│   └── admin.py
└── common/
    ├── config.py
    ├── time.py
    └── errors.py
```

---

## 6. Queue Architecture

### PostgreSQL as queue (no Redis needed at this scale)

```sql
-- Workers use SKIP LOCKED to claim jobs atomically
-- No two workers process the same job

SELECT * FROM scrape_job
WHERE status = 'pending'
AND job_type = $1
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;

-- On claim:
UPDATE scrape_job SET status='running', started_at=NOW(), attempts=attempts+1
WHERE id = $claimed_id;

-- On success:
UPDATE scrape_job SET status='done', finished_at=NOW(), result_json=$result
WHERE id = $claimed_id;

-- On failure:
UPDATE scrape_job
SET status = CASE WHEN attempts >= 3 THEN 'error' ELSE 'pending' END,
    error_msg = $error
WHERE id = $claimed_id;
```

### Job types and retry policy

| Job Type | Retry | Timeout | Idempotency |
|---|---|---|---|
| CAUSELIST | 3 attempts | 120s | UNIQUE(job_type, target_date, url) |
| ORDER | 3 attempts | 180s | UNIQUE on file_hash |
| LIVE | no retry (loop) | 15s | replace on conflict |
| NOTIFICATION | 3 attempts | 30s | track sent_at per user/case |

### Event flow for causelist scrape

```
Cron triggers at 20:30 IST
    │
    ▼
scrape_job INSERT (status='pending', job_type='CAUSELIST', target_date=tomorrow)
    │ (UNIQUE → no duplicate job)
    ▼
CauselistWorker polls scrape_job WHERE status='pending'
    │ SKIP LOCKED → claims job
    ▼
fetch_causelist_html(target_date)
    │
    ▼
parse_causelist_html(html) → [{bench, ecodes: [{ecode, header_text, cases}]}]
    │
    ▼
store_causelist(parsed)
    │ → INSERT causelist_bench (ON CONFLICT UPDATE)
    │ → INSERT causelist_ecode (ON CONFLICT UPDATE)
    │ → INSERT causelist_case (ON CONFLICT UPDATE)
    │ → UPDATE search_vector via trigger
    │
    ▼
scrape_job UPDATE status='done'
    │
    ▼
notification_trigger_job INSERT (for morning alerts)
```

---

## 7. PDF Processing Strategy

### Pipeline for order PDFs

```
Order PDF URL
    │
    ▼ Step 1: Download
    download_pdf(url) → bytes
    sha256_hash(bytes) → file_hash
    check: court_order WHERE file_hash = $hash → if exists, SKIP (idempotent)
    │
    ▼ Step 2: Classification
    is_native_pdf? → try pdfplumber.extract_text()
    if text_length > 100 chars → native PDF, skip OCR
    else → image-based PDF, run OCR
    │
    ▼ Step 3: Text Extraction
    [Native] pdfplumber → extract_text() per page
    [Image]  pdf2image → PIL images → pytesseract.image_to_string()
    │
    ▼ Step 4: Case Reference Extraction
    regex scan extracted text for case refs:
    pattern: r'\b([A-Z][A-Z\.\-]*)\s*/\s*(\d+)\s*/\s*(\d{4})\b'
    collect all matches → deduplicate
    │
    ▼ Step 5: Order-Case Matching
    for each case_ref found in order:
        lookup causelist_case WHERE case_ref = $ref AND list_date = $order_date
        if found → INSERT order_case_map (confidence=1.0, method='exact')
        else → fuzzy match by court_no + serial_no range (confidence < 1.0)
    │
    ▼ Step 6: Store
    INSERT court_order (file_url, file_hash, ocr_text, status='matched')
    upload PDF to Supabase Storage
    │
    ▼ Step 7: Trigger billing
    for each matched case_ref:
        if matter EXISTS for case_ref:
            INSERT billing_entry (entry_type='IN_COURT', order_id=$order_id)
```

### OCR quality handling

```python
def extract_order_text(pdf_bytes: bytes) -> tuple[str, bool]:
    """Returns (text, is_ocr). Try native first, fall back to OCR."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        if len(text.strip()) > 100:
            return text, False  # native PDF, good quality
    except Exception:
        pass
    
    # OCR fallback
    images = pdf2image.convert_from_bytes(pdf_bytes, dpi=300)
    text = "\n".join(
        pytesseract.image_to_string(img, lang="eng", config="--psm 6")
        for img in images
    )
    return text, True
```

---

## 8. Search Indexing Strategy

### Multi-field weighted FTS

```sql
-- Weight scheme: A=case_ref, B=parties, C=advocate, D=judge
-- Searches rank exact case_ref matches highest

SELECT 
  cc.case_ref, cc.petitioner, cc.respondent, cc.advocate,
  cc.list_date, cc.court_no, cc.serial_no,
  ce.display_name AS ecode,
  cb.judges_json,
  ts_rank_cd(cc.search_vector, query) AS rank
FROM causelist_case cc
JOIN causelist_bench cb ON cb.id = cc.bench_id
LEFT JOIN causelist_ecode ce ON ce.id = cc.ecode_id,
  plainto_tsquery('english', $1) query
WHERE cc.search_vector @@ query
  AND ($2::DATE IS NULL OR cc.list_date >= $2)
  AND ($3::DATE IS NULL OR cc.list_date <= $3)
  AND ($4::TEXT IS NULL OR cc.court_no = $4)
ORDER BY rank DESC, cc.list_date DESC
LIMIT 50;
```

### Advocate search (separate FTS)

```sql
-- Advocate profiles need fuzzy name matching (enrollment spelling variations)
CREATE INDEX idx_advocate_fts ON advocate_profile 
  USING GIN(to_tsvector('english', full_name || ' ' || array_to_string(aliases, ' ')));

-- Also add trigram index for partial matches
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_advocate_name_trgm ON advocate_profile 
  USING GIN(full_name gin_trgm_ops);

-- Search: FTS + trigram fallback
SELECT * FROM advocate_profile
WHERE to_tsvector('english', full_name) @@ plainto_tsquery('english', $1)
   OR full_name % $1   -- trigram similarity
ORDER BY similarity(full_name, $1) DESC
LIMIT 20;
```

### Search API design

```
GET /search?q=rupa+paul&type=party&date_from=2026-01-01
GET /search?q=WPA/71/2026&type=case_ref
GET /search?q=shampa+sarkar&type=judge
GET /advocate/search?q=bhaskar+manna
GET /causelist/{date}/ecode/{ecode}  → all cases under ECODE for date
```

---

## 9. Storage Optimization Strategy

### What causes storage bloat

| Column | Size/row | 50k rows/week | Action |
|---|---|---|---|
| `raw_text` in causelist_case | ~500B | 25MB | **DROP** — redundant debug data |
| `header_text` per case | ~2KB | 100MB | **MOVE** to causelist_ecode (one per ECODE) |
| `ocr_text` in court_order | ~10KB | varies | Keep — but compress |
| PDF files | ~500KB each | ~30MB/day | Supabase Storage (outside DB) |

### Immediate wins

```python
# 1. Drop raw_text from causelist_case inserts (parser.py)
# Just remove raw_text from INSERT columns and values — saves 25MB/week

# 2. Store PDFs in Supabase Storage, only URL in DB
async def store_order_pdf(pdf_bytes: bytes, filename: str) -> str:
    supabase.storage.from_("orders").upload(filename, pdf_bytes)
    return f"{SUPABASE_URL}/storage/v1/object/public/orders/{filename}"

# 3. Compress OCR text with postgres LZ4
-- In psql:
ALTER TABLE court_order ALTER COLUMN ocr_text SET STORAGE EXTENDED;
-- PG compresses TOAST columns > 2KB automatically
```

### Partitioning for scale (future, >1M rows)

```sql
-- Partition causelist_case by list_date (monthly partitions)
CREATE TABLE causelist_case (...)
PARTITION BY RANGE (list_date);

CREATE TABLE causelist_case_2026_05 
  PARTITION OF causelist_case
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

-- Old partitions can be archived/dropped without affecting current data
```

### Retention policy

```sql
-- Auto-expire raw_text after 30 days (keep structured data forever)
-- Run monthly via cron:
UPDATE causelist_case
SET section = section  -- no-op, just to trigger tsvector rebuild if needed
WHERE list_date < NOW() - INTERVAL '30 days'
  AND raw_text IS NOT NULL;

-- Actually: at parse time, never store raw_text
-- For orders: keep OCR text 90 days, then archive to cold storage
```

---

## 10. Caching Strategy

### Two-tier cache

```
Request
   │
   ▼ Tier 1: In-process LRU cache (5 min TTL)
   │  lru_cache or cachetools — for hot endpoints
   │  causelist dates list, bench list for today
   │
   ▼ Tier 2: Redis / Upstash (15 min TTL)
   │  causelist/{date}/summary → bench list JSON
   │  causelist/{date}/court/{no} → full court cases JSON
   │  advocate/{id} → profile JSON
   │
   ▼ Tier 3: Postgres (source of truth)
```

### Cache invalidation

```python
# After causelist scrape completes:
redis.delete(f"causelist:{target_date}:summary")
# After advocate update:
redis.delete(f"advocate:{advocate_id}")

# TTL-based for court data (15 min is fine for daily data)
# Live monitor data: NO cache (always fresh from DB)
```

---

## 11. API Design

### Route structure

```
/auth
  POST /auth/send-otp
  POST /auth/verify-otp
  GET  /auth/me
  PATCH /auth/me

/causelist
  GET  /causelist/dates
  GET  /causelist/prefixes
  GET  /causelist/search
  GET  /causelist/{date}
  GET  /causelist/{date}/court/{court_no}
  GET  /causelist/{date}/court/{court_no}/ecode/{ecode}   # NEW
  GET  /causelist/{date}/court/{court_no}/serial/{serial_no}

/orders
  GET  /orders/{date}
  GET  /orders/{date}/court/{court_no}
  GET  /orders/case/{case_ref}

/advocate
  GET  /advocate/search?q=
  GET  /advocate/{id}
  POST /advocate           (auth required)
  PATCH /advocate/{id}     (own profile)

/billing
  GET  /billing/matters
  POST /billing/matters
  GET  /billing/matters/{id}
  GET  /billing/matters/{id}/entries
  POST /billing/matters/{id}/entries
  POST /billing/matters/{id}/invoice   # generates invoice
  GET  /billing/invoices/{id}
  GET  /billing/invoices/{id}/pdf      # download PDF receipt

/firm
  GET  /firm/dashboard
  POST /firm/invite
  GET  /firm/members
  PATCH /firm/members/{id}/role

/admin
  GET  /admin/scrape-jobs
  POST /admin/scrape-jobs/trigger
  GET  /admin/audit-log
```

---

## 12. Event Flow

### Appearance detection flow

```
LiveMonitor polls display_api.json every 15s
    │
    ▼
current snapshot: {court: "3", serial: "5", case_no: "WPA/71/2026", ...}
    │
    ▼
ChangeDetector.apply_snapshot()
    │ compare against field_state table
    │ if serial changed → "case advanced" event
    │ if case_no changed → "new case on board" event
    │
    ▼
EventTrace records inserted:
  {court_id: "3", field: "case_no", old: "WPA/95/2026", new: "WPA/71/2026", ...}
    │
    ▼
AppearanceEngine.classify(event)
    │ lookup: is WPA/71/2026 in today's causelist? → YES
    │ what section? → GROUP_IX
    │ current serial vs causelist serial → serial 1 called → MOTION_HEARING
    │
    ▼
appearance_type = 'IN_COURT_MOTION'
    │
    ▼
BillingTrigger.on_appearance(case_ref, appearance_type, court_no, date)
    │ lookup: matter WHERE case_ref = 'WPA/71/2026' AND status = 'active'
    │ if found → INSERT billing_entry (entry_type='IN_COURT', auto_generated=true)
    │
    ▼
NotificationWorker.on_case_called(case_ref, court_no)
    │ lookup: tracked_cases WHERE case_ref = 'WPA/71/2026'
    │ for each user → send WhatsApp/push alert
```

---

## 13. State Machine: Case Tracking

### Appearance classification

```
Case appears in cause list
    │
    ├─→ serial called on live board?
    │       YES → APPEARED
    │       NO  → LISTED (not yet called)
    │
[APPEARED]
    │
    ├─→ serial advanced within 30 min?
    │       YES → HEARD (actual hearing)
    │       NO  → MENTIONED (passed over / brief mention)
    │
[HEARD]
    │
    ├─→ order uploaded same day?
    │       YES → ORDER_PASSED
    │       NO  → check next 3 days
    │             order found within 3 days → ORDER_PASSED (delayed)
    │             no order → ADJOURNED (no order)
    │
[ADJOURNED]
    │
    └─→ appears in next date's causelist?
            YES → RE_LISTED
            NO  → DISPOSED or long adjournment
```

### Database state storage

```sql
-- Case tracking state (extend my_cases / tracked_cases)
ALTER TABLE tracked_cases ADD COLUMN last_status TEXT;
ALTER TABLE tracked_cases ADD COLUMN last_heard_date DATE;
ALTER TABLE tracked_cases ADD COLUMN next_listed_date DATE;
ALTER TABLE tracked_cases ADD COLUMN times_heard INT DEFAULT 0;
ALTER TABLE tracked_cases ADD COLUMN times_adjourned INT DEFAULT 0;
```

---

## 14. Advocate Hierarchy & Billing System

### Role hierarchy (from product_spec.md §2, extended)

```
Law Firm (top-level entity — holds all matters)
    │
    ├─ Solicitor / Managing Partner
    │       └─ full firm access, all billing, invoicing authority
    │
    ├─ Senior Counsel (SC)
    │       └─ brief accepted from AOR, highest per-appearance fee
    │          typically engaged only for specific hearings
    │
    ├─ Advocate on Record (AOR)
    │       └─ registered with court registry
    │          files vakalatnama, manages client officially
    │          owns the matter, distributes to juniors
    │
    ├─ Junior Counsel
    │       └─ appears on behalf of AOR
    │          lower per-appearance fee
    │          can bill for out-of-court research
    │
    ├─ Clerk
    │       └─ files papers, collects orders, court runs
    │          flat fee per task or per day
    │
    └─ Client
            └─ see own matters, pay invoices, get alerts
               cannot see fee structure
```

### Registration data collected per role

#### All roles (mandatory)
```
full_name, phone (E.164), email, password/OTP
role selection (from hierarchy)
```

#### Advocate / Junior / Senior / AOR (additional mandatory)
```
enrollment_no       → Bar Council of Calcutta enrollment number
bar_council         → which bar council
court_practice_areas → checkboxes: Civil / Criminal / Constitutional / Labour / Tax
```

#### AOR specific
```
AOR registration no  → court registry number
vakalatnama authority → can file vakalatnama? checkbox
```

#### Billing fields (optional at signup, prompt later)
```
pan_no              → for GST invoice
gstin               → if GST registered (optional for individuals)
gst_registration_type → Regular / Composition / None
upi_id              → for payment
bank_account        → {bank_name, ifsc, account_no, beneficiary_name}
digital_signature   → upload file (for e-filing)
```

#### Law firm (firm account)
```
firm_name, gstin (mandatory for firm), firm_address
gst_rate applicable (18% default, can override)
invoice_prefix → "INV-FIRM-" (for invoice numbering)
letterhead_logo → upload
```

### Revenue ownership model

```python
# When a billing entry is created, split revenue per matter_member
def calculate_member_revenue(billing_entry: BillingEntry, matter: Matter) -> list[dict]:
    members = get_matter_members(matter.id)
    total = billing_entry.total_amount
    splits = []
    
    for member in members:
        if member.fee_per_appearance:
            # Fixed per-appearance: use member's own rate
            splits.append({
                "advocate_id": member.advocate_id,
                "amount": member.fee_per_appearance,
                "type": "fixed"
            })
        elif member.revenue_share:
            # Percentage split
            splits.append({
                "advocate_id": member.advocate_id,
                "amount": total * (member.revenue_share / 100),
                "type": "percentage"
            })
    return splits
```

### Commission structure example

```
Matter: WPA/71/2026 — Rupa Paul vs State of WB

matter_members:
  AOR: BHASKAR MANNA     → fee_per_appearance = ₹5,000
  Junior: AMIT SHARMA    → fee_per_appearance = ₹2,000
  Clerk: SURESH           → fee_per_appearance = ₹500

billing_entry (one court appearance):
  IN_COURT: AOR appears → ₹5,000
  IN_COURT: Junior appears → ₹2,000
  CLERK: Filing papers → ₹500

Invoice to client: ₹7,500 + GST
Internal split: already tracked via billing_entries per advocate
```

---

## 15. Receipt Generation Workflow

### Invoice numbering
```python
def next_invoice_no(firm_id: int, year: int) -> str:
    # Atomic sequence per firm per year
    seq = db.execute("""
        SELECT nextval('invoice_seq_' || $1::text || '_' || $2::text)
    """, [firm_id, year]).scalar()
    return f"INV-{year}-{seq:04d}"
    # e.g. INV-2026-0042
```

### Receipt format

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [FIRM LOGO]        BHASKAR MANNA & ASSOCIATES
                     Advocates, Calcutta High Court
                     GSTIN: 19ABCDE1234F1Z5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TAX INVOICE                          No: INV-2026-0042
                                     Date: 06-May-2026
To:
  Rupa Paul
  42 Park Street, Kolkata 700016
  GSTIN: (if applicable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER: WPA/71/2026 — Rupa Paul vs State of WB
        Calcutta High Court, Court 3

  Date        Description                    Amount
  ─────────── ─────────────────────────────  ─────────
  02-Mar-2026 Court appearance (Motion)      ₹5,000.00
  02-Mar-2026 Junior counsel appearance      ₹2,000.00
  02-Mar-2026 Clerk charges (filing)           ₹500.00
  04-Mar-2026 Out of court — drafting (3hr)  ₹3,000.00
  05-Mar-2026 Court appearance (Hearing)     ₹8,000.00
  ─────────── ─────────────────────────────  ─────────
                              Subtotal:     ₹18,500.00
                              GST @18%:     ₹3,330.00
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                              TOTAL:        ₹21,830.00
                              Amount Due:   ₹21,830.00
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  UPI: bhaskar@upi  |  Account: SBI 1234567890
  IFSC: SBIN0001234  |  Pan: ABCDE1234F
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### PDF generation

```python
# WeasyPrint: HTML template → PDF
from weasyprint import HTML, CSS

def generate_invoice_pdf(invoice_id: int) -> bytes:
    invoice = get_invoice_with_entries(invoice_id)
    html_content = render_template("invoice.html", invoice=invoice)
    pdf_bytes = HTML(string=html_content).write_pdf(
        stylesheets=[CSS(string=INVOICE_CSS)]
    )
    # Upload to Supabase Storage
    url = upload_to_storage(pdf_bytes, f"invoices/{invoice.invoice_no}.pdf")
    update_invoice(invoice_id, pdf_url=url)
    return pdf_bytes

# Sharing
def share_invoice(invoice_id: int, method: str):
    if method == "whatsapp":
        send_whatsapp_document(user.phone, invoice.pdf_url, invoice.invoice_no)
    elif method == "email":
        send_email_attachment(user.email, pdf_bytes, f"{invoice.invoice_no}.pdf")
```

### Billing entry types and rates

| Entry Type | Description | Who creates | Auto/Manual |
|---|---|---|---|
| `IN_COURT_MOTION` | Motion hearing appearance | System (from live board) | Auto |
| `IN_COURT_HEARING` | Final/part-heard | System | Auto |
| `IN_COURT_SENIOR` | Senior counsel appearance | System | Auto |
| `CLERK_FILING` | Papers filed, order collected | Clerk | Manual |
| `OUT_OF_COURT_DRAFT` | Drafting/research (hourly) | Any advocate | Manual |
| `OUT_OF_COURT_CONSULT` | Client consultation | Any advocate | Manual |
| `MISC` | Miscellaneous | Any | Manual |

---

## 16. User Permission Model

### Role → capability matrix

| Capability | Client | Clerk | Junior | AOR/Senior | Solicitor | Admin |
|---|---|---|---|---|---|---|
| View own case alerts | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Track cases | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| View firm causelist | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create billing entry | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create invoice | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| View all firm matters | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| Manage firm members | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| Admin panel | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

### Supabase RLS policies

```sql
-- Users see only their own matter entries
CREATE POLICY "own_matters" ON matter
  USING (
    firm_id IN (
      SELECT firm_id FROM firm_members 
      WHERE user_id = auth.uid()
    )
    OR id IN (
      SELECT matter_id FROM matter_member mm
      JOIN advocate_profile ap ON ap.id = mm.advocate_id
      WHERE ap.user_id = auth.uid()
    )
  );

-- Only AOR/Solicitor can create invoices
CREATE POLICY "invoice_create" ON invoice
  FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM user_roles
      WHERE user_id = auth.uid()
      AND role IN ('AOR', 'SOLICITOR', 'ADMIN')
    )
  );

-- Audit log: write-only for all, read for admin only
CREATE POLICY "audit_insert" ON audit_log FOR INSERT WITH CHECK (TRUE);
CREATE POLICY "audit_select" ON audit_log FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM user_roles WHERE role = 'ADMIN'));
```

---

## 17. Background Jobs Architecture

### Job registry

```python
# src/eventtrace/jobs/registry.py

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

# Live monitor — continuous
# (run as separate process, not APScheduler)

# Daily causelist scrape — 20:30 IST
scheduler.add_job(
    causelist_scraper.run,
    trigger="cron", hour=20, minute=30,
    id="daily_causelist", replace_existing=True
)

# Daily order scrape — 18:00 IST
scheduler.add_job(
    order_scraper.run,
    trigger="cron", hour=18, minute=0,
    id="daily_orders", replace_existing=True
)

# Morning alerts — 07:00 IST
scheduler.add_job(
    notification_worker.send_daily_alerts,
    trigger="cron", hour=7, minute=0,
    id="morning_alerts", replace_existing=True
)

# Retry failed jobs — every 30 min
scheduler.add_job(
    job_retry_worker.retry_failed,
    trigger="interval", minutes=30,
    id="job_retry"
)

# Auto-billing trigger — after causelist stored (event-driven)
# Not cron — triggered from causelist scraper completion

# Weekly DB backup — Sunday 02:00 IST
scheduler.add_job(
    backup_worker.dump_and_upload,
    trigger="cron", day_of_week="sun", hour=2,
    id="weekly_backup"
)
```

---

## 18. Cron Strategy

### Railway scheduler config

```toml
# railway.toml (per service)

[services.causelist-scheduler]
  startCommand = "python -m eventtrace.jobs.causelist_cron"

[services.live-monitor]
  startCommand = "chd-run-monitor"
  restartPolicy = "always"

[services.api]
  startCommand = "chd-api"
  healthcheckPath = "/health"
```

### Cron schedule overview

| Job | Schedule | Description |
|---|---|---|
| Causelist DAILY scrape | 20:30 IST | Next day's Appellate Daily list |
| Causelist ORIGINAL SIDE | 20:45 IST | Original Side list |
| Causelist MONTHLY | 1st of month 21:00 IST | Monthly list |
| Order PDF scrape | 18:00 IST | Today's uploaded orders |
| Order retry | 21:00 IST | Re-check delayed orders |
| Morning alerts | 07:00 IST | WhatsApp/email for today's listings |
| Backfill stale dates | 22:00 IST | Fill any failed scrapes |
| Auto billing scan | 22:00 IST | Create billing entries from appearances |
| Weekly backup | Sun 02:00 IST | pg_dump → Supabase Storage |

### Holiday/weekend handling

```python
def should_scrape_today(target_date: date) -> bool:
    """Courts don't sit on holidays/weekends."""
    if target_date.weekday() >= 5:  # Sat/Sun
        return False
    if is_high_court_holiday(target_date):  # check holiday table
        return False
    return True

# Holiday table
CREATE TABLE court_holiday (
  holiday_date DATE PRIMARY KEY,
  description  TEXT
);
-- Pre-populate from HC calendar annually
```

---

## 19. Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  RAILWAY PROJECT: "eventtrace"                               │
│                                                              │
│  Service 1: api                                              │
│    image: ./Dockerfile                                       │
│    cmd: chd-api                                             │
│    port: 8009                                               │
│    health: GET /health                                       │
│    env: DATABASE_URL, JWT_SECRET, MSG91_*, SENTRY_DSN       │
│                                                              │
│  Service 2: live-monitor                                     │
│    cmd: chd-run-monitor                                      │
│    restart: always                                           │
│    env: DATABASE_URL, CHD_KEY_FIELDS                        │
│                                                              │
│  Service 3: causelist-scheduler                              │
│    cmd: chd-schedule-causelist                               │
│    env: DATABASE_URL                                         │
│                                                              │
│  (All share same Docker image, different start commands)     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  SUPABASE PROJECT: "eventtrace-db"                           │
│  Postgres 15, Region: ap-south-1 (Mumbai)                   │
│  Auth: OTP via phone, Google OAuth                           │
│  Storage: orders/, invoices/, logos/                         │
│  Realtime: broadcast on event_trace inserts                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  VERCEL: "eventtrace-web"                                    │
│  React + Vite build                                          │
│  Edge CDN — auto-deploy on push to main                      │
│  Custom domain: eventtrace.in                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  UPSTASH REDIS (optional, free tier)                         │
│  API response cache (15 min TTL)                             │
│  Rate limiting for auth endpoints                            │
└─────────────────────────────────────────────────────────────┘
```

### Scaling path

```
Now (1–100 users):
  Single Railway project, 3 services, Supabase free/pro, Vercel free

At 1,000 users:
  Upgrade Supabase to Pro ($25/mo) → PITR backups, more connections
  Add Redis cache (Upstash free → $10/mo)
  Increase Railway service sizes

At 10,000 users:
  Separate read-replica for search queries
  Supabase connection pooler (PgBouncer) — already built-in
  Causelist CDN: cache static date's causelist JSON at edge

At 100,000 users:
  Extract causelist storage to dedicated analytics DB
  Elasticsearch for full-text search
  Message queue: migrate from PG-based to Redis Streams or Kafka
  Separate billing microservice
```

---

## 20. Monitoring & Logging Strategy

### Structured logging

```python
import structlog

log = structlog.get_logger()

# Every scrape job logs structured events
log.info("causelist_scraped",
    date=target_date,
    courts=len(benches),
    cases=total_cases,
    duration_ms=elapsed,
    job_id=job.id
)

log.error("order_scrape_failed",
    date=order_date,
    url=url,
    attempt=attempt,
    error=str(exc)
)
```

### Monitoring stack

| What | Tool | Alert on |
|---|---|---|
| API uptime | Railway health checks | 2 consecutive failures → Telegram alert |
| Error rate | Sentry (free: 5k/mo) | Any new error type |
| Scraper failures | Custom Telegram bot | 3 consecutive job failures |
| DB slow queries | Supabase Dashboard → Query Perf | Queries > 500ms |
| Storage size | Supabase Dashboard | > 400MB (free limit) |
| Invoice generation | Custom audit_log check | Failed PDF generation |
| Frontend errors | Vercel Analytics + Sentry | Any JS error with user impact |

### Audit log strategy

Every write operation logs to `audit_log`:

```python
def audit(action: str, entity_type: str, entity_id: str, 
          before: dict = None, after: dict = None, user_id: str = None):
    db.execute("""
        INSERT INTO audit_log(user_id, action, entity_type, entity_id, before_json, after_json, ip_address)
        VALUES($1,$2,$3,$4,$5,$6,$7)
    """, [user_id, action, entity_type, str(entity_id), 
          json.dumps(before), json.dumps(after), request_ip()])
```

Critical actions requiring audit:
- `CREATE_INVOICE` / `CANCEL_INVOICE`
- `MARK_PAID`
- `DELETE_MATTER`
- `CHANGE_MEMBER_ROLE`
- `BILLING_ENTRY_DELETED`

---

## 21. Edge Cases Handling

| Edge Case | Detection | Resolution |
|---|---|---|
| Duplicate cause list upload | `scrape_job` UNIQUE(job_type, date, url) | Skip — idempotent insert |
| Same PDF uploaded twice | `court_order.file_hash` UNIQUE | Skip on conflict |
| Corrupted PDF (unreadable) | pdfplumber throws exception | Log error, mark job='error', Telegram alert |
| OCR error in case ref | `r'\bWP[A-Z]*/\d+/\d{4}\b'` regex misses | Store null case_ref, human review flag |
| Case moved between sections | ecode_id changes in upsert | ON CONFLICT UPDATE ecode_id → tracked automatically |
| Judge change mid-date | bench re-scraped, `judges_json` updated | ON CONFLICT UPDATE, event_trace records change |
| Case listed under 2 ECODEs same day | Two serial_no rows with different ecode_id | Both stored — UNIQUE(bench_id, serial_no) allows it |
| Late order upload (T+2 or T+3) | order_scraper runs retry at 21:00 IST for 3 days | Match by date range: `order_date BETWEEN $date-3 AND $date` |
| Case number format variation | `WPA 71/26` vs `WPA/71/2026` | Normalize in parser: `_normalize_case_type` + 4-digit year |
| Re-listed matter (NEW case, same ref) | causelist appears again after disposal | Track via timeline: consecutive appearances after gap |
| Holiday / no causelist | Court closed | `should_scrape_today()` returns False, no job created |
| Concurrent scraper runs | `SKIP LOCKED` queue | Only one worker claims each job |
| Multiple courts, multiple ECODEs | Scale test | Handled by bench_id → ecode_id → case FK chain |
| Advocate name alias | "BHASKAR MANNA" vs "B. MANNA" | `aliases[]` array + trigram index |
| GST rate change | Currently 18% | `gst_rate` column per billing_entry, not hardcoded |
| Partial hearing (morning + afternoon) | Two serial calls same case same day | Two billing_entries for same case_ref, same date — deduplicate on invoice |

---

## 22. AI Readiness Layer

### What to prepare now (no extra cost)

1. **Store `raw_text` per order** (not per cause list case) — orders are richer for AI analysis
2. **ECODE header text** already stored in `causelist_ecode.header_text`  
3. **Timeline data** in `event_trace` is perfect for ML pattern detection

### Future AI use cases

| Use Case | Data needed | Model type |
|---|---|---|
| Predict next hearing date | event_trace timeline | Time series / regression |
| Classify order outcome | ocr_text from orders | Text classification (BERT) |
| Auto-extract parties from OCR | ocr_text | NER (Named Entity Recognition) |
| Advocate performance analytics | billing_entries + appearances | Analytics dashboard |
| Predict case disposal timeline | matter history + bench data | Survival analysis |
| Smart billing suggestions | past billing_entries for similar cases | Recommendation |

### API design for AI layer (future)

```
GET /ai/case/{case_ref}/predict-next-date
GET /ai/order/{id}/extract-outcome
POST /ai/order/analyze  body: {ocr_text}
GET /ai/advocate/{id}/performance-summary
```

### Claude API integration (when ready)

```python
# Analyze order text with Claude
import anthropic

client = anthropic.Anthropic()

def analyze_order_outcome(ocr_text: str) -> dict:
    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Extract from this court order:
1. Case result (adjourned/disposed/stayed/etc.)
2. Next date if mentioned
3. Key directions given

Order text:
{ocr_text[:4000]}"""
        }]
    )
    return parse_structured_response(message.content[0].text)
```

---

## IMPLEMENTATION PRIORITY

```
Phase 1 — Foundation (now)
  ✓ Add causelist_ecode table (ECODE mapping)
  ✓ Fix parser to emit ecode structure
  ✓ Drop raw_text from causelist_case writes
  ✓ Add search_vector + FTS trigger to causelist_case
  □ Migrate to Supabase

Phase 2 — Advocate System (Month 1)
  □ advocate_profile table + search
  □ law_firm + matter tables
  □ Registration flow (role-based profile fields)

Phase 3 — Billing (Month 2)
  □ billing_entry CRUD
  □ Auto billing trigger from appearance engine
  □ Invoice generation
  □ PDF receipt (WeasyPrint)
  □ WhatsApp/email sharing

Phase 4 — Orders (Month 3)
  □ Order scraper + PDF parser
  □ order_case_map matching
  □ OCR pipeline

Phase 5 — AI Layer (Month 6+)
  □ Outcome extraction from orders
  □ Hearing date prediction
  □ Performance analytics
```

---

*This document supersedes the partial billing analysis in `19_BILLING_AND_BENCH_HEADER_ANALYSIS.md`.*  
*Reference: `14_PRODUCT_SPEC.md` §2 (hierarchy) and §3 (search architecture).*
