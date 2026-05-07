# Billing System + Bench Header / Data Size Analysis
> Created: 2026-05-06

---

## Issue 1: Bench Header / "Code" Mapping

**Current state**: Already mapped. `causelist_bench` stores `jurisdiction` (the block of text between judges and VC link). `causelist_case` has `section` + `subsection` fields that come from the all-caps headers within each court block (e.g., "GROUP - IX", "PIL", "TRIBUNAL MOTION"). Each case FK-links to its bench via `bench_id`.

**What's missing**: The screenshot shows an "ORDER SHEET" header with **typed matter categories** (e.g., "MATTERS RELATING TO CENTRAL GOVERNMENT SERVICES"). The parser already captures these as `section` on each case. But the **full order-sheet header text** (the descriptive block at top of each bench) is stored in `jurisdiction` column — it's there, just not exposed in the search API response.

**Fix — two small changes:**
1. Add `jurisdiction` field to `GET /causelist/{date}` and search responses
2. Strip `raw_text` from DB storage (see Issue 2 — it's the size culprit)

---

## Issue 2: Data Size (45–50 MB / week)

`raw_text` on every `causelist_case` row is the problem. It stores the original text block per case — redundant, never queried. Drop it.

**Rough estimate**: If avg case raw_text is ~300 chars, 1000 cases/day × 7 days = ~2MB just from raw_text. But 45MB suggests the HTML itself may be cached or there's logging overhead. Need to check.

**Fix**: Stop writing `raw_text` to DB. It's debug data — keep it in logs if needed.

---

## Issue 3: Billing System with Hierarchy

### Role Hierarchy

```
Client
Solicitor
Senior Counsel        (optional)
Counsel               (optional)
Junior Counsel        (optional)
Advocate on Record
Clerk
```

### Billing Types

- **OUT_OF_COURT** — drafting, research, client meetings (manual entry)
- **IN_COURT** — appearance fee; can be auto-suggested from causelist data (court_date + court_no)

### New Tables

```sql
-- Matter = a legal case/engagement
CREATE TABLE matters (
  id           TEXT PRIMARY KEY,
  title        TEXT NOT NULL,          -- case name / matter name
  case_ref     TEXT,                   -- FK to causelist_case.case_ref (optional)
  created_by   TEXT REFERENCES users(id),
  created_at   TEXT NOT NULL
);

-- Who is on this matter + their role
CREATE TABLE matter_members (
  matter_id    TEXT REFERENCES matters(id),
  user_id      TEXT REFERENCES users(id),
  role         TEXT NOT NULL,          -- SOLICITOR | ADVOCATE_ON_RECORD | COUNSEL | etc.
  fee_share    REAL,                   -- % split (like Splitwise)
  PRIMARY KEY (matter_id, user_id)
);

-- Individual billing entries
CREATE TABLE billing_entries (
  id           TEXT PRIMARY KEY,
  matter_id    TEXT REFERENCES matters(id),
  billed_by    TEXT REFERENCES users(id),
  entry_type   TEXT NOT NULL,          -- IN_COURT | OUT_OF_COURT
  description  TEXT,
  amount       REAL NOT NULL,
  currency     TEXT NOT NULL DEFAULT 'INR',
  entry_date   TEXT NOT NULL,
  -- In-court specific
  court_date   TEXT,                   -- hearing date
  court_no     TEXT,
  case_ref     TEXT,
  -- Approval chain
  approved_by  TEXT REFERENCES users(id),
  approved_at  TEXT,
  created_at   TEXT NOT NULL
);

-- Email-based collaboration invites (cross-firm)
CREATE TABLE matter_invites (
  id            TEXT PRIMARY KEY,
  matter_id     TEXT REFERENCES matters(id),
  invited_email TEXT NOT NULL,
  role          TEXT NOT NULL,
  invited_by    TEXT REFERENCES users(id),
  accepted_at   TEXT,
  created_at    TEXT NOT NULL
);
```

### Hierarchy Rules for Billing Approval

| Role | Can approve |
|------|------------|
| SOLICITOR | All junior entries |
| ADVOCATE_ON_RECORD | All junior entries |
| SENIOR_COUNSEL / COUNSEL | Their own entries |
| CLIENT | Sees total invoice only (not internal splits) |

### API Endpoints Needed

```
POST /matters                        — create matter
GET  /matters                        — list my matters
POST /matters/{id}/members           — add member (by phone/email)
POST /matters/{id}/billing           — add billing entry
GET  /matters/{id}/billing           — list entries
GET  /matters/{id}/billing/summary   — per-role breakdown (Splitwise view)
POST /matters/{id}/invite            — email invite for cross-firm collaboration
```

### Causelist Integration

When creating an IN_COURT billing entry:
- If `case_ref` is tracked in `tracked_cases`, auto-fill `court_date` + `court_no` from `causelist_case`
- Link order sheet info (bench, judges) from `causelist_bench` via `case_ref` + date

---

## Priority Order

| # | Task | Effort | Blocker |
|---|------|--------|---------|
| 1 | Drop `raw_text` from DB writes | 1h | None |
| 2 | Expose `jurisdiction` in causelist/search API responses | 2h | None |
| 3 | `matters` + `matter_members` + `billing_entries` tables | 1 day | None |
| 4 | Billing API routes | 1 day | Needs #3 |
| 5 | Billing UI in EventTrace-Web (Splitwise-style dashboard) | 2 days | Needs #4 |
| 6 | Email invite via Resend | 0.5 day | Needs #3 |

**Start with 1 + 2** — no schema changes, immediate wins.
**Then** decide if billing is next sprint.
