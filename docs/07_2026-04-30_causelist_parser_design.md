# Causelist Parser — System Design

**Date:** 2026-04-30  
**Scope:** Backend only — parsing, normalization, schema, search, edge cases.  
**Target:** Calcutta High Court daily cause lists at  
`https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{DD}{MM}{YYYY}.html`

---

## 1. Real HTML Structure (from actual 30 Apr 2026 causelist)

**Critical:** Cases are NOT in HTML `<table>` elements. The causelist is formatted plain text
rendered in HTML (likely `<pre>`, `<p>`, or `<br>`-separated blocks). `inner_text("body")`
gives the correct parse surface.

### Page 1 — Court Header Block

```
In The High Court At Calcutta
Appellate Side
DAILY CAUSELIST
For Thursday The 30th April 2026
COURT NO. 1
First Floor
Main Building
DIVISION BENCH (DB - I)
HON'BLE CHIEF JUSTICE SUJOY PAUL
HON'BLE JUSTICE PARTHA SARATHI SEN

NOT SITTING ON 30.04.2026

FROM 2ND MARCH, 2026 - PUBLIC INTEREST LITIGATION;
[... jurisdiction paragraphs ...]

NOTE:
I.  ON EVERY MONDAY, PIL (MOTION) MATTERS WILL BE TAKEN UP FIRST. [...]
[... notes I through XI ...]

VC LINK: https://calcuttahighcourt-gov-in.zoom.us/j/98477830007?pwd=...
```

Page 1 contains **no cases**. It is pure metadata: court identity, jurisdiction, procedural notes.
Must be parsed separately and stored in `causelist_bench`.

### Case Block Structure (page 2+)

Cases appear under section + subsection headers, one case per multi-line block:

```
POLICE INACTION
(GROUP - IX)
1    MAT/911/2025

FAKIR CHAND MODAK
VS
STATE OF WEST BENGAL AND ORS.    KRISHNA DAS PODDAR
2    MAT/1550/2025

SUKTARA BIBI AND ANR.
VS
THE STATE OF WEST BENGAL AND ORS.    SYED ALI AFZAL
IA NO: CAN/1/2025
3    MAT/1966/2025

...

PIL
(MOTION)
7    WPA(P)/408/2024

PEOPLE FOR BETTER TREATMENT (PBT) ...
VS
STATE OF WEST BENGAL ...    DR KUNAL SAHA (PETITIONER IN PERSON)
IA NO: CAN/1/2026

GROUP - IX (HEARING)
(POLICE INACTION)
24   MAT/406/2021

SAHIDUL ISLAM MANDAL AND ORS
VS
UNION OF INDIA AND ORS.    Ali Ahsan Alamgir
IA NO: CAN/1/2021
```

### Exact case record pattern

```
{serial}    {case_number}
[blank line]
{PETITIONER}
VS
{RESPONDENT}    {ADVOCATE}
[IA NO: {ia_case_number}]    ← optional, may repeat
[blank line]
```

### Section header pattern

```
{SECTION_NAME}           ← e.g. "POLICE INACTION", "PIL", "TRIBUNAL MOTION"
({SUBSECTION})           ← e.g. "(GROUP - IX)", "(MOTION)", "(HEARING)"
```

Subsection is optional. Some sections are combined inline:
`GROUP - IX (HEARING)` with subsection `(POLICE INACTION)`.

### "NOT SITTING" courts

Court 1 on 30 Apr 2026 says `NOT SITTING ON 30.04.2026` — still has cases listed (the
court is not sitting today but cases are listed for future/other courts). Must parse this flag.

---

## 2. Parsing Strategy

### 2a. Fetch

`httpx` (already a dep) — static HTML, no JS:

```python
import httpx
from datetime import date

def fetch_causelist_html(for_date: date) -> str | None:
    dd = for_date.strftime("%d")
    mm = for_date.strftime("%m")
    yyyy = for_date.strftime("%Y")
    url = f"https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{dd}{mm}{yyyy}.html"
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        return resp.text if resp.status_code < 400 else None
    except httpx.TimeoutException:
        return None
```

Extract clean text:
```python
from bs4 import BeautifulSoup

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    # Preserve line structure — replace <br> and block elements with newlines
    for tag in soup.find_all(["br", "p", "div", "tr"]):
        tag.insert_after("\n")
    return soup.get_text("\n")
```

### 2b. Split into Court Blocks

The full HTML covers all courts (one large document). Split by `COURT NO. N` headers.

```python
import re

COURT_BLOCK_RE = re.compile(
    r"(?=(?:^|\n)COURT\s+NO[\.\s]*\s*\d+)",
    re.IGNORECASE | re.MULTILINE
)

def split_court_blocks(text: str) -> list[str]:
    return [b.strip() for b in COURT_BLOCK_RE.split(text) if b.strip()]
```

Each block starts at `COURT NO. N` and ends before the next `COURT NO.`.

### 2c. Parse Court Header (Page 1 equivalent)

```python
COURT_NO_RE    = re.compile(r"COURT\s+NO[\.\s]*\s*(\d+)", re.IGNORECASE)
JUDGE_RE       = re.compile(r"HON['']?BLE\s+((?:CHIEF\s+)?(?:DR\.\s+)?JUSTICE\s+[A-Z][A-Z\s\.]+?)(?=\n|HON)", re.IGNORECASE)
BENCH_RE       = re.compile(r"(DIVISION\s+BENCH|SINGLE\s+BENCH|DB|SB)\s*[-–(IVX\d\-\s)]*", re.IGNORECASE)
SIDE_RE        = re.compile(r"(APPELLATE\s+SIDE|ORIGINAL\s+SIDE)", re.IGNORECASE)
LIST_TYPE_RE   = re.compile(r"(DAILY|MONTHLY|SUPPLEMENTARY|SPECIAL)\s+CAUSELIST", re.IGNORECASE)
DATE_RE        = re.compile(r"For\s+\w+\s+The\s+(\d+(?:st|nd|rd|th)?)\s+(\w+)\s+(\d{4})", re.IGNORECASE)
NOT_SITTING_RE = re.compile(r"NOT\s+SITTING\s+ON\s+([\d\.]+)", re.IGNORECASE)
VC_LINK_RE     = re.compile(r"VC\s+LINK\s*:\s*(https?://\S+)", re.IGNORECASE)

def parse_court_header(block: str) -> dict:
    judges = [m.group(1).strip() for m in JUDGE_RE.finditer(block)]
    not_sitting_match = NOT_SITTING_RE.search(block)
    return {
        "court_no":    _first_group(COURT_NO_RE, block),
        "bench_label": _first_match(BENCH_RE, block),
        "side":        _first_match(SIDE_RE, block),
        "list_type":   _first_group(LIST_TYPE_RE, block),
        "list_date":   _parse_date(DATE_RE, block),
        "judges":      judges,
        "not_sitting": bool(not_sitting_match),
        "vc_link":     _first_group(VC_LINK_RE, block),
        # jurisdiction text = everything between judge names and VC LINK
        "jurisdiction_notes": _extract_jurisdiction(block),
    }
```

### 2d. Split Block into Sections

After the header (before first numbered case), detect section headers:

```python
# Section header: ALL CAPS line, optionally followed by (SUBSECTION) line
SECTION_HEADER_RE = re.compile(
    r"^([A-Z][A-Z\s\-\(\)/]+?)$\n?"          # section name line
    r"(?:\(([A-Z][A-Z\s\-IX/]+?)\)\s*\n)?",  # optional subsection in parens
    re.MULTILINE
)

# A case starts with: digits + whitespace + case_type/number/year
CASE_START_RE = re.compile(
    r"^(\d+)\s{2,}([A-Z][A-Z\.\(\)]*\s*/\s*\d+\s*/\s*\d{4})",
    re.MULTILINE
)
```

Walk through the block line by line, tracking current section:

```python
def parse_cases_from_block(block: str) -> list[dict]:
    # Strip header (everything before first numbered case)
    first_case = CASE_START_RE.search(block)
    if not first_case:
        return []

    body = block[first_case.start():]
    cases = []
    current_section = None
    current_subsection = None

    # Split body into chunks — each chunk is either a section header or a case
    chunks = re.split(r"\n{2,}", body)  # blank-line separated

    i = 0
    while i < len(chunks):
        chunk = chunks[i].strip()
        if not chunk:
            i += 1
            continue

        # Section header detection: no digits at start, all-caps, short
        if _is_section_header(chunk):
            parts = chunk.splitlines()
            current_section = parts[0].strip()
            current_subsection = parts[1].strip("() ") if len(parts) > 1 else None
            i += 1
            continue

        # Try to parse as case
        case = _parse_case_chunk(chunk, current_section, current_subsection)
        if case:
            cases.append(case)
        i += 1

    return cases

def _is_section_header(chunk: str) -> bool:
    lines = chunk.strip().splitlines()
    first = lines[0].strip()
    # Section header: no leading digits, mostly uppercase, no "VS" or "/"
    if CASE_START_RE.match(first):
        return False
    if re.match(r"^[A-Z][A-Z\s\-\(\)/]+$", first) and len(first) < 80:
        return True
    return False
```

### 2e. Parse Single Case Chunk

```python
CASE_LINE_RE = re.compile(
    r"^(\d+)\s{2,}([A-Z][A-Z\.\(\)]*)\s*/\s*(\d+)\s*/\s*(\d{4})",
    re.MULTILINE
)
IA_RE = re.compile(r"IA\s+NO\s*:\s*([A-Z]+/\d+/\d{4})", re.IGNORECASE)

def _parse_case_chunk(chunk: str, section: str | None, subsection: str | None) -> dict | None:
    lines = [l.strip() for l in chunk.strip().splitlines() if l.strip()]
    if not lines:
        return None

    # Line 0: "1    MAT/911/2025"
    m = re.match(r"^(\d+)\s{2,}([A-Z][A-Z\.\(\)]*)\s*/\s*(\d+)\s*/\s*(\d{4})$", lines[0])
    if not m:
        return None

    serial     = int(m.group(1))
    case_type  = m.group(2).strip()
    case_num   = m.group(3).strip()
    case_year  = int(m.group(4))
    case_ref   = f"{case_type}/{case_num}/{case_year}"

    # Remaining lines: PETITIONER / VS / RESPONDENT    ADVOCATE / IA NO: ...
    petitioner = respondent = advocate = None
    ia_numbers: list[str] = []

    vs_idx = next((i for i, l in enumerate(lines) if l.upper() == "VS"), None)

    if vs_idx is not None:
        # Lines before VS = petitioner (may be multi-line, join with space)
        petitioner = " ".join(lines[1:vs_idx]).strip()

        # Line after VS = "RESPONDENT    ADVOCATE"
        if vs_idx + 1 < len(lines):
            resp_line = lines[vs_idx + 1]
            # Advocate is separated by 2+ spaces or a tab
            parts = re.split(r"\s{3,}|\t", resp_line, maxsplit=1)
            respondent = parts[0].strip()
            advocate   = parts[1].strip() if len(parts) > 1 else None

        # Remaining lines: IA NO or additional advocate lines
        for line in lines[vs_idx + 2:]:
            ia_m = IA_RE.match(line)
            if ia_m:
                ia_numbers.append(ia_m.group(1))

    return {
        "serial_no":    serial,
        "case_ref":     case_ref,
        "case_type":    case_type,
        "case_number":  case_num,
        "case_year":    case_year,
        "petitioner":   petitioner,
        "respondent":   respondent,
        "advocate":     advocate,      # petitioner's advocate (listed after respondent — CHC convention)
        "ia_numbers":   ia_numbers,
        "section":      section,
        "subsection":   subsection,
        "raw":          chunk,
    }
```

**CHC convention:** The advocate name listed after respondent is the **petitioner's advocate**,
not the respondent's advocate. No respondent advocate is listed in most cases.

---

## 3. Normalization

### 3a. Case Numbers

```python
# CHC case type normalizations (dots, spaces stripped)
CASE_TYPE_NORM = {
    "W.P.A.": "WPA",  "WPA(P)": "WPA(P)",  "WP.CT": "WP.CT",
    "W.P.(C)": "WPC", "M.A.T.": "MAT",     "C.A.N.": "CAN",
    "C.O.": "CO",     "F.A.": "FA",         "A.P.O.": "APO",
    "C.S.": "CS",     "C.P.": "CP",
}

def normalize_case_type(raw: str) -> str:
    key = raw.strip().upper()
    return CASE_TYPE_NORM.get(key, key)

def normalize_case_ref(case_type: str, number: str, year: int) -> str:
    return f"{normalize_case_type(case_type)}/{number.lstrip('0')}/{year}"
```

### 3b. Party Names

```python
import re

_WS = re.compile(r"\s{2,}")

def normalize_party(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().upper()
    s = _WS.sub(" ", s)
    s = re.sub(r"\bAND\s+ORS\.?\b", "& ORS.", s)
    s = re.sub(r"\bAND\s+ANR\.?\b", "& ANR.", s)
    return s

def normalize_advocate(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().upper()
    s = re.sub(r"^(MR\.?|MRS\.?|MS\.?|DR\.?|LD\.?\s+ADV\.?|ADV\.?)\s+", "", s)
    s = _WS.sub(" ", s)
    return s.strip()
```

### 3c. Sections → Canonical Tags

```python
SECTION_TAGS = {
    "POLICE INACTION": "GROUP_IX",
    "GROUP - IX":      "GROUP_IX",
    "PIL":             "PIL",
    "PUBLIC INTEREST LITIGATION": "PIL",
    "TRIBUNAL MOTION": "TRIBUNAL",
    "TRIBUNAL HEARING": "TRIBUNAL",
    "WP.CT":           "TRIBUNAL",
    "GROUP - VI":      "GROUP_VI",
    "CONTEMPT":        "CONTEMPT",
    "REVIEW":          "REVIEW",
}

HEARING_TYPE = {
    "MOTION":  "MOTION",
    "HEARING": "HEARING",
    "APPEAL":  "APPEAL",
}

def classify_section(section: str, subsection: str | None) -> tuple[str, str | None]:
    """Returns (canonical_category, hearing_type)."""
    s = (section or "").upper()
    sub = (subsection or "").upper()
    category = next((v for k, v in SECTION_TAGS.items() if k in s), section)
    h_type = next((v for k, v in HEARING_TYPE.items() if k in s or k in sub), None)
    return category, h_type
```

---

## 4. Database Schema

```sql
-- One row per court-bench on a given day
CREATE TABLE causelist_bench (
    id           BIGSERIAL PRIMARY KEY,
    list_date    DATE NOT NULL,
    court_no     TEXT NOT NULL,          -- "1", "237" — always TEXT
    bench_label  TEXT,                   -- "DIVISION BENCH (DB - I)"
    side         TEXT,                   -- "APPELLATE SIDE" | "ORIGINAL SIDE"
    list_type    TEXT,                   -- "DAILY" | "MONTHLY" | "SUPPLEMENTARY"
    judges       TEXT[],                 -- Postgres array
    not_sitting  BOOLEAN NOT NULL DEFAULT FALSE,
    vc_link      TEXT,
    jurisdiction TEXT,                   -- raw jurisdiction + notes text
    scraped_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX causelist_bench_unique
    ON causelist_bench(list_date, court_no);

CREATE INDEX causelist_bench_date  ON causelist_bench(list_date);
CREATE INDEX causelist_bench_court ON causelist_bench(court_no, list_date DESC);

-- One row per case listed
CREATE TABLE causelist_case (
    id             BIGSERIAL PRIMARY KEY,
    bench_id       BIGINT NOT NULL REFERENCES causelist_bench(id) ON DELETE CASCADE,
    list_date      DATE NOT NULL,        -- denormalized for fast date queries
    court_no       TEXT NOT NULL,        -- denormalized
    serial_no      INTEGER NOT NULL,
    case_ref       TEXT,                 -- "WPA(P)/408/2024" — normalized
    case_type      TEXT,                 -- "WPA(P)"
    case_number    TEXT,                 -- "408"
    case_year      INTEGER,              -- 2024
    petitioner     TEXT,
    respondent     TEXT,
    advocate       TEXT,                 -- petitioner's advocate (CHC lists only one)
    ia_numbers     TEXT[],               -- connected IAs e.g. ["CAN/1/2026"]
    section        TEXT,                 -- canonical: "PIL", "GROUP_IX", "TRIBUNAL"
    subsection     TEXT,                 -- e.g. "MOTION", "HEARING"
    hearing_type   TEXT,                 -- "MOTION" | "HEARING" | "APPEAL"
    raw_text       TEXT,                 -- original unparsed chunk
    scraped_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX causelist_case_unique
    ON causelist_case(bench_id, serial_no);

-- Core search indexes
CREATE INDEX causelist_case_ref        ON causelist_case(case_ref);
CREATE INDEX causelist_case_type_year  ON causelist_case(case_type, case_year);
CREATE INDEX causelist_case_date_court ON causelist_case(list_date, court_no);

-- Full-text: party names + advocate
CREATE INDEX causelist_case_fts ON causelist_case
    USING GIN (to_tsvector('english',
        COALESCE(petitioner, '') || ' ' ||
        COALESCE(respondent, '') || ' ' ||
        COALESCE(advocate, '')
    ));

-- Trigram: partial name / advocate search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX causelist_case_adv_trgm ON causelist_case USING GIN (advocate gin_trgm_ops);
CREATE INDEX causelist_case_pet_trgm ON causelist_case USING GIN (petitioner gin_trgm_ops);
```

---

## 5. Search Queries

### By case number (exact)
```sql
SELECT cc.*, cb.judges, cb.court_no, cb.vc_link
FROM causelist_case cc JOIN causelist_bench cb ON cb.id = cc.bench_id
WHERE cc.case_ref = 'WPA(P)/408/2024'
ORDER BY cc.list_date DESC;
```

### By case number (partial — user types "408/2024")
```sql
WHERE cc.case_ref LIKE '%/408/2024'
```

### By party name (full-text)
```sql
WHERE to_tsvector('english', COALESCE(petitioner,'') || ' ' || COALESCE(respondent,''))
      @@ plainto_tsquery('english', 'fakir chand modak')
ORDER BY list_date DESC LIMIT 50;
```

### By advocate (partial)
```sql
WHERE advocate ILIKE '%KRISHNA DAS%'
-- or with trigram:
WHERE advocate % 'KRISHNA DAS'  -- pg_trgm similarity operator
```

### Current day: what case is at serial N in court X
```sql
SELECT cc.case_ref, cc.petitioner, cc.respondent, cb.judges, cb.vc_link
FROM causelist_case cc JOIN causelist_bench cb ON cb.id = cc.bench_id
WHERE cc.court_no = '1' AND cc.serial_no = 7
  AND cc.list_date = CURRENT_DATE;
```

This is the critical query linking monitor (`running_serial` on display board) to causelist data.

---

## 6. API Endpoints

```
GET /causelist/{date}
    → list of benches with case counts

GET /causelist/{date}/court/{court_no}
    → bench metadata + all cases for that court

GET /causelist/{date}/court/{court_no}/serial/{n}
    → single case at that serial (used by notification bot)

GET /causelist/search?case_ref=&party=&advocate=&date_from=&date_to=
    → cross-date search
```

---

## 7. Edge Cases

| Case | Handling |
|------|---------|
| `NOT SITTING ON {date}` | Set `not_sitting=TRUE` on bench; still store listed cases |
| Multi-line petitioner name | Join all lines before `VS` with space |
| Advocate contains `(PETITIONER IN PERSON)` | Store as advocate, set flag `pro_se=TRUE` |
| `IA NO:` appears multiple times per case | Collect all into `ia_numbers[]` array |
| Section header with no subsection | `subsection = NULL` |
| Combined header `GROUP - IX (HEARING)` | Section = "GROUP_IX", hearing_type = "HEARING" |
| Encoding errors (`â€"` = em dash) | Decode with `errors="replace"` then fix: `s.replace("â€"", "–")` |
| Court `NOT SITTING` — zero cases | Store bench row, return empty cases list |
| Weekend / holiday — 404 | Return `None` from fetch; log INFO not WARNING |
| Same serial appears twice (amended list) | `ON CONFLICT (bench_id, serial_no) DO UPDATE` |
| Non-standard court numbers (237, 655, 759) | `court_no TEXT` — never cast to int |
| IA case with no main case | Should not occur; if it does, skip and log |
| Advocate name in mixed case (`Ali Ahsan Alamgir`) | Normalize to UPPER for storage + search |

---

## 8. Dependencies

```toml
# Add to pyproject.toml
"beautifulsoup4>=4.12",
"lxml>=5.0",
```

`httpx` already present. No Playwright for causelist — static HTML.

---

## 9. Implementation Order

1. `pip install beautifulsoup4 lxml` + add to `pyproject.toml`
2. Save a real HTML file locally for dev: `curl -o sample.html <url>`
3. Write `causelist_full_scraper.py`: fetch → text → block split → header parse → case parse
4. Unit-test parser against `sample.html` — print all cases as JSON, verify against known list
5. Add schema to `db.py` (`causelist_bench`, `causelist_case`)
6. Wire parser output → DB upserts (idempotent — re-runnable same day)
7. Add API endpoints
8. Schedule daily scrape at 20:00 IST (8:00 PM) in `run_monitor.py` — court publishes next day's list ~8 PM
9. Add trigram indexes after first week of data
