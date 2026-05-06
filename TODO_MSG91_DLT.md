# MSG91 + DLT Setup — 2026-05-04

## DLT Template
Register this exact text on DLT portal:
```
Your OTP for EventTrace is {#var#}. Valid for 10 minutes. Do not share with anyone.
```
- Category: **Transactional OTP**
- Header (sender ID): `EVNTRC`

## Steps
1. Register on Airtel DLT portal
2. Register Principal Entity
3. Register Header (`EVNTRC`)
4. Register Template (text above) → get DLT template ID
5. MSG91 dashboard → SMS → Templates → add same template → get `template_id`
6. MSG91 dashboard → API → Auth Key → get `authkey`

## Railway Env Vars to Set
```
MSG91_AUTH_KEY=<authkey from MSG91>
MSG91_TEMPLATE_ID=<template_id from MSG91>
JWT_SECRET=<python -c "import secrets; print(secrets.token_hex(32))">
```

---

# Billing System — Steps 4–9

## Step 4 — `billing_entry` table + CRUD API

**What**: New DB table `billing_entry` (id, matter_id, entry_date, description, amount, created_at). API endpoints: `GET /matters/{id}/billing`, `POST /matters/{id}/billing`, `DELETE /matters/{id}/billing/{entry_id}`.

**Why**: Raw billing records per appearance. Each court date where the lawyer appeared = one entry. Amount defaults to `matter.fee_per_appearance` but can be overridden (e.g., adjournment fee differs).

## Step 5 — Auto-trigger billing_entry from causelist scrape

**What**: In `schedule_causelist.py` (or a post-scrape hook), after inserting causelist cases, query `matter` table for any `case_ref` values that appear in today's causelist AND have `status = 'active'`. For each match, insert a `billing_entry` with today's date and the matter's `fee_per_appearance`.

**Why**: Zero manual effort for billing. Lawyer doesn't have to log appearances — the system detects them from the causelist automatically. This is the core value of the billing system.

**Trigger point**: End of `_scrape_and_store` in `causelist_scheduler.py`, after causelist rows are committed to DB.

## Step 6 — Billing entries page (frontend)

**What**: In `MattersPage.tsx`, clicking a matter expands it (or opens a drawer) showing its `billing_entry` rows — date, description, amount. Plus a manual "Add Entry" button for dates not scraped. Running total shown at bottom.

**Why**: Lawyer needs to see the full billing history per case and be able to add ad-hoc entries (out-of-court work, special appearances on non-causelist days).

## Step 7 — Invoice generation

**What**: `POST /matters/{id}/invoice` — aggregates unpaid `billing_entry` rows, creates an `invoice` record (id, matter_id, period_from, period_to, total_amount, status='draft', created_at). Returns the invoice with line items.

**DB**: New `invoice` table (id, matter_id, period_from, period_to, total_amount, status, created_at) + `invoice_entry` join table linking billing_entry → invoice.

**Why**: Separates "recording" from "billing". Multiple appearances accumulate; lawyer generates invoice when ready to send to client.

## Step 8 — PDF receipt / invoice download

**What**: `GET /invoices/{id}/pdf` — renders invoice as HTML (Jinja2 template), converts to PDF with WeasyPrint, returns as `application/pdf`.

**Install**: `pip install weasyprint` (requires system libpango, libcairo — add to Railway's Nixpacks config or use a base Docker image).

**Frontend**: Download button on invoice → hits the endpoint → browser downloads PDF.

**Why**: Lawyers need a printable/shareable document. WhatsApp PDF to client is the typical workflow. WeasyPrint chosen over reportlab because HTML/CSS layout is far easier to maintain and style than low-level PDF drawing calls.

## Step 9 — Original Side eCourts lookup

**What**: Add a second lookup path in `ecourts.py` for Original Side cases (CO, WPO, FA, SA, etc.) that use `court_code=1` instead of `court_code=3`.

**How**: Detect by case type — if `case_type` maps to an Original Side type ID (separate `CASE_TYPE_IDS_OS` dict), use `_BASE_OS` URL with `court_code=1&dist_cd=1&state_cd=16`.

**Why**: Currently `lookup_case('CO/3536/2025')` returns None because CO is an Original Side case type. The eCourts site has separate endpoints for Appellate Side (court_code=3) and Original Side (court_code=1). About 30–40% of Calcutta HC cases are Original Side so this covers a large portion of missing lookups.

---

## Why `requests` and not Playwright for eCourts

**The eCourts form is plain PHP with no client-side JS rendering.** The page at `case_no.php` loads a static HTML form. Submitting it is a standard HTTP POST to `case_no_qry.php`. The response is raw text (tilde-delimited), not HTML that needs rendering.

Playwright would add:
- ~400MB Chromium binary
- 3–5s cold-start per lookup (browser launch)
- Flakiness from browser automation (element selectors, timing)
- No benefit — there is nothing to render

`requests.Session` handles the only thing that matters: maintaining the `PHPSESSID` cookie across 3 requests (page GET → CAPTCHA image GET → form POST). That's it. The CAPTCHA image itself is fetched as raw bytes and sent to Claude Haiku Vision — no browser needed for that either.
