# EventTrace — Product Overview &  Time line Launch Plan

> For: Stakeholder / Management Review  
> Phase 1 Target: 2 weeks to live product  
> Date: May 2026

---

## What Is EventTrace?

**EventTrace is a real-time court tracking platform for the High Court.**

Right now, lawyers, clerks, and clients have no easy way to know what is happening in court unless they are physically present or keep calling the court. EventTrace solves this by:

- Automatically reading the court's live display board every 15 seconds
- Storing a complete history of every case update
- Showing the daily Cause List (the schedule of hearings for each court)
- Allowing anyone to search by advocate name, party name, or case number
- Sending alerts on WhatsApp or email when a case is listed for hearing

**Who it is for:** Advocates, junior counsel, clerks, and clients who want to track cases without being physically at court.

---

## What Users Will See — Screen by Screen

### Screen 1 — Live Display Board

This is the main screen. It shows what is happening right now in every courtroom — updated automatically every 15 seconds. No refresh needed.

```
╔══════════════════════════════════════════════════════════════════════╗
║  EventTrace                                    Updated 11:32:05 AM  ║
║  Live Display Board                        Auto-refreshes every 15s ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ┌──────────┬──────────┬──────────────────────────┬────────────┐   ║
║  │  Court   │  Serial  │  Status / Case           │  Last Seen │   ║
║  ├──────────┼──────────┼──────────────────────────┼────────────┤   ║
║  │  Court 1 │   14     │  WPA(P)/172/2026         │  11:31 AM  │   ║
║  │  Court 2 │   27     │  Hearing in progress     │  11:30 AM  │   ║
║  │  Court 3 │    —     │  NOT SITTING             │  10:15 AM  │   ║
║  │  Court 4 │    8     │  CWP/5678/2025           │  11:32 AM  │   ║
║  │  Court 5 │   33     │  Order passed            │  11:28 AM  │   ║
║  │  ...     │  ...     │  ...                     │  ...       │   ║
║  └──────────┴──────────┴──────────────────────────┴────────────┘   ║
║                                                                      ║
║  What does this show?                                                ║
║  → Which court is active right now                                   ║
║  → Which serial number (case) is being heard                        ║
║  → Current status of each courtroom                                 ║
║  → When it was last updated                                         ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Already built and working.** Data comes from the court's own system every 15 seconds.

---

### Screen 2 — Cause List (Daily Schedule)

The Cause List is the official schedule of cases for each court for a given day. This screen lets users browse it by date and court.

```
╔══════════════════════════════════════════════════════════════════════╗
║  EventTrace                                                          ║
║  Cause List    [ Date: 01 May 2026 ▼ ]                              ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ┌─────────────────────┐  ┌─────────────────────────────────────┐  ║
║  │  COURTS             │  │  CASES — Court 1                    │  ║
║  │─────────────────────│  │  Justice A.K. Sharma                │  ║
║  │  Court 1   42 cases │  │─────────────────────────────────────│  ║
║  │  Court 2   31 cases │  │  #  │ Case No.     │ Party   │ Adv  │  ║
║  │  Court 3   28 cases │  │─────┼──────────────┼─────────┼──────│  ║
║  │  Court 4   NOT SIT  │  │  1  │ WP/101/2024  │ Singh v │ Kumar│  ║
║  │  Court 5   19 cases │  │  2  │ CWP/234/2025 │ Sharma v│ Gupta│  ║
║  │  Court 6   55 cases │  │  3  │ CRL/88/2026  │ State v │ Singh│  ║
║  │  ...                │  │  4  │ WPA/172/2026 │ Roy v   │ Mehta│  ║
║  │  [ Click any court ]│  │  ...│ ...          │ ...     │ ...  │  ║
║  └─────────────────────┘  └─────────────────────────────────────┘  ║
║                                                                      ║
║  What does this show?                                                ║
║  → Full list of cases scheduled for today (or any past date)        ║
║  → Which judge is sitting in each court                             ║
║  → Case number, parties, and advocate for each case                 ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Already built and working.** Historical dates also available — users can look back at past cause lists.

---

### Screen 3 — Search

Any user (no login needed) can search across all stored cause lists by advocate name, party name, or case number.

```
╔══════════════════════════════════════════════════════════════════════╗
║  EventTrace                                                          ║
║  Search Cause Lists                                                  ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ┌─────────────────────────────────────────────────────────────┐   ║
║  │  Advocate Name    │  Party Name          │  Case Number     │   ║
║  │  [ Sharma      ]  │  [                 ] │  [            ]  │   ║
║  │                                                 [ Search ]  │   ║
║  └─────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║  14 results found                                                    ║
║  ┌──────────┬─────────┬────┬──────────────┬────────────┬────────┐  ║
║  │  Date    │  Court  │  # │  Case No.    │  Party     │  Adv.  │  ║
║  ├──────────┼─────────┼────┼──────────────┼────────────┼────────┤  ║
║  │ 01 May   │ Court 3 │  7 │ WP/101/2024  │ Singh v UOI│ Sharma │  ║
║  │ 28 Apr   │ Court 1 │ 12 │ CWP/234/2025 │ Roy v State│ Sharma │  ║
║  │ 25 Apr   │ Court 7 │  3 │ WPA/88/2026  │ Kumar v MCD│ Sharma │  ║
║  │  ...     │  ...    │ ...│  ...         │  ...       │  ...   │  ║
║  └──────────┴─────────┴────┴──────────────┴────────────┴────────┘  ║
║                                                                      ║
║  Most common searches: Advocate name / Case number / Party name     ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Already built and working.** Searches across all stored cause list data.

---

### Screen 4 — Personal Dashboard (Planned — Phase 1)

After signing up, users get a personal dashboard where they can track their specific cases and receive alerts.

```
╔══════════════════════════════════════════════════════════════════════╗
║  EventTrace                              Hello, Adv. Sharma  [ ▼ ] ║
║  My Dashboard                                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  MY TRACKED CASES                              [ + Add a Case ]     ║
║  ┌──────────────────────────────────┐  ┌───────────────────────┐   ║
║  │  WP/101/2024                     │  │  CWP/234/2025         │   ║
║  │  Singh v Union of India          │  │  Sharma v State       │   ║
║  │  ● Listed TODAY — Court 3, 10 AM │  │  Next: 08 May 2026    │   ║
║  │  [View History]  [Remove]        │  │  [View History] [Rem] │   ║
║  └──────────────────────────────────┘  └───────────────────────┘   ║
║                                                                      ║
║  TODAY'S HEARINGS (My Cases Only)                                   ║
║  ┌──────────┬────────────┬──────────────┬────────┬──────────────┐  ║
║  │  Court   │  Time      │  Case        │ Serial │  Status      │  ║
║  ├──────────┼────────────┼──────────────┼────────┼──────────────┤  ║
║  │  Court 3 │  10:30 AM  │ WP/101/2024  │   7    │  Pending     │  ║
║  └──────────┴────────────┴──────────────┴────────┴──────────────┘  ║
║                                                                      ║
║  CASE HISTORY — WP/101/2024                                         ║
║  Apr 25 ──●── Adjourned                                              ║
║  Apr 28 ──●── Listed, not taken up                                  ║
║  May 01 ──●── Listed TODAY ← you are here                           ║
║                                                                      ║
║  NOTIFICATIONS                                                       ║
║  ✓ WhatsApp alerts: ON    ✓ Email alerts: ON                        ║
║  "WP/101/2024 listed tomorrow at 10:30 AM — Court 3"               ║
╚══════════════════════════════════════════════════════════════════════╝
```

**To be built in Phase 1.** This is the core value-add for paid users.

---

## How Everything Is Connected

Think of it as three separate parts that talk to each other:

```
┌──────────────────────────────────────────────────────────────── ─┐
│                                                                  │
│   COURT WEBSITE  ──scrapes every 15 seconds──▶  BACKGROUND       │
│   (public data)                                  WORKERS         │
│                                                  (on Railway)    │
│                                                      │           │
│                                                      │ saves     │
│                                                      ▼           │
│                                                  DATABASE        │
│                                                  (Supabase)      │
│                                                      │           │
│                                              ┌───────┴──────┐    │
│                                         reads│              │push│
│                                              ▼              ▼    │
│                                          BACKEND        REAL-TIME│
│                                          (Railway)       updates │
│                                              │              │    │
│                                              └──────┬───────┘    │
│                                                     │            │
│                                                     ▼            │
│                                               WEBSITE / APP      │
│                                               (Vercel)           │
│                                               What user sees     │
│                                                                  │
│                                                     │            │
│                                         NOTIFICATIONS│           │
│                                                     ▼            │
│                                         WhatsApp / Email         │
│                                         sent to user             │
└──────────────────────────────────────────────────────────────── ─┘
```

**In simple words:**

- A background program runs 24/7, reading the court's website and saving any changes into a database.
- The database stores everything permanently — all case updates, cause lists, hearing history.
- When a user opens the website, it fetches data from the database through a backend server.
- For live updates, the website is also connected in real-time — so the board refreshes automatically.
- Every evening, the system checks tomorrow's cause list and sends WhatsApp / email alerts to users who have signed up.

---

## Technology Stack — Where Each Part Lives

| What | Technology Used | Where It Runs | Monthly Cost |
|---|---|---|---|
| Website (what user sees) | React, TypeScript | Vercel | Free |
| Backend server (data delivery) | Python FastAPI | Railway | ~$5/month |
| Court scraper (runs 24/7) | Python, Playwright | Railway | ~$5/month |
| Cause list downloader | Python scheduler | Railway | ~$5/month |
| Database (stores everything) | PostgreSQL | Supabase | Free (up to 500 MB) |
| User login / accounts | Supabase Auth | Supabase | Free (up to 50,000 users) |
| WhatsApp alerts | WATI (BSP provider) | WATI cloud | ₹2,499/month |
| Email alerts | Resend | Resend cloud | Free (3,000 emails/month) |
| Custom domain | — | DNS provider | ~₹1,000/year |
| Error monitoring | Sentry | Sentry cloud | Free |

**Total running cost (Month 1): approximately ₹5,000–6,000/month**

This covers all infrastructure. No upfront hardware. Scales up as users grow.

---

## Who Uses It and What They Can Do

```
FREE (no account needed)
  ├── View the live display board
  ├── Browse the daily cause list
  └── Search by advocate / party / case number

BASIC USER (free sign-up, Phase 1 launch)
  ├── Everything in Free
  ├── Track their own case numbers
  ├── Get WhatsApp alert when case is listed for hearing
  ├── Get email alert the evening before hearing date
  └── View case history timeline

ADVANCED (future — Phase 2)
  ├── Everything in Basic
  ├── Track unlimited cases
  ├── Export data as PDF or Excel
  ├── Dashboard for multiple clients (for advocates / clerks)
  └── Shared workspace for law firms
```

---

## Two-Week Build Plan

### Week 1 — Foundation (Behind the scenes)

| Day | Work | What It Means |
|---|---|---|
| Day 1 | Move database to Supabase | Data stored safely with daily backups |
| Day 2 | Set up user accounts (sign up / log in) | Google login also supported |
| Day 3 | Make search faster across all data | Results in under 1 second |
| Day 4 | Build "track a case" feature | Users can save cases to their account |
| Day 5 | Build alert system | System checks tomorrow's cause list, sends WhatsApp |
| Day 6 | Set up automatic code checks | No broken code goes live |
| Day 7 | Testing + fixes | Buffer day |

### Week 2 — What Users See

| Day | Work | What It Means |
|---|---|---|
| Day 8 | Landing page + search bar | First thing any visitor sees |
| Day 8 | Cause list page with filters | Browse by date and court |
| Day 9 | Sign up / log in screens | Google login button |
| Day 9 | Personal dashboard | My Cases panel, today's hearings |
| Day 10 | Case history timeline chart | Visual history of each case |
| Day 11 | Error monitoring + custom domain | Professional URL, alerts if system breaks |
| Day 12 | WhatsApp notification settings | User turns alerts on/off |
| Day 13 | Full test from start to finish | Simulate a real user signing up and tracking a case |
| Day 14 | Go live | Announce, share link |

---

## What Is Already Done (Before This Two-Week Plan)

| Feature | Status |
|---|---|
| Live display board | Done — working in production |
| Cause list browse | Done — working in production |
| Search by advocate / party / case | Done — working in production |
| Backend server deployed | Done — Railway, live URL |
| Website deployed | Done — Vercel, live URL |
| 7-day historical data backfill | Done — runs on startup |
| Automatic restarts if server crashes | Done |
| HTTPS (secure connection) | Done — on both Railway and Vercel |

The two-week plan builds the user-facing product on top of a working, deployed technical foundation.

---

## Risks and How We Handle Them

| Risk | How We Handle It |
|---|---|
| Court website changes its format | Scraper detects column names dynamically — does not break on layout changes |
| Server crashes | Railway auto-restarts within seconds. Telegram alert sent to admin. |
| Database failure | Supabase has daily automated backups. Restore is one click. |
| WhatsApp approval delay | WATI template submitted Day 5. Meta typically approves in 24–48 hours. |
| More users than expected | Supabase free tier handles 50,000 users. Railway scales up with one slider. |

---

## Summary

- **What we have built:** A live court tracking system that reads data every 15 seconds, stores it, and serves it through a website.
- **What we are building:** User accounts, case tracking, WhatsApp/email alerts, and a personal dashboard.
- **Timeline:** 2 weeks to a fully working product that users can sign up for.
- **Cost:** ~₹5,000–6,000/month to run everything on professional cloud infrastructure.
- **Scale:** No code changes needed to go from 10 users to 10,000 users.
