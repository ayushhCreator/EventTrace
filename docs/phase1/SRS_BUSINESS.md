# EventTrace — Phase 1 Software Requirements
## Business & Management Document

> **For:** Management Review  
> **Phase:** 1 — Core Product  
> **Language:** Non-technical  
> **Version:** 1.0 | May 2026  
> **Status:** Living document — add comments in the _Management Comments_ sections

---

## Table of Contents

1. [The Problem We Are Solving](#1-the-problem-we-are-solving)
2. [Who This Is Built For](#2-who-this-is-built-for)
3. [What Makes EventTrace Different](#3-what-makes-eventtrace-different)
4. [Phase 1 — What We Are Building](#4-phase-1--what-we-are-building)
   - 4.1 [Live Display Board](#41-live-display-board)
   - 4.2 [Cause List Browser](#42-cause-list-browser)
   - 4.3 [Case Search](#43-case-search)
   - 4.4 [Personal Dashboard — My Cases](#44-personal-dashboard--my-cases)
   - 4.5 [Alerts — Email Notifications](#45-alerts--email-notifications)
   - 4.6 [User Accounts](#46-user-accounts)
5. [What Is Already Working Today](#5-what-is-already-working-today)
6. [What Still Needs to Be Built](#6-what-still-needs-to-be-built)
7. [How a Typical User Will Use EventTrace](#7-how-a-typical-user-will-use-eventtrace)
8. [Who Can Use What — Access Levels](#8-who-can-use-what--access-levels)
9. [Running Cost for Phase 1](#9-running-cost-for-phase-1)
10. [Risks and How We Handle Them](#10-risks-and-how-we-handle-them)
11. [What Phase 2 Will Add](#11-what-phase-2-will-add)
12. [Questions for Management Review](#12-questions-for-management-review)

---

## 1. The Problem We Are Solving

### The Current Situation at Calcutta High Court

Every working day at the High Court, hundreds of cases are scheduled across many courtrooms. Advocates, clerks, and clients face the same problem every morning:

**No one knows what is happening in court unless they are physically there.**

The court's own website does have a display board that shows which case is being heard in each courtroom right now — but it has a serious limitation: **you have to be at a computer, staring at the same page, and manually refreshing it every few minutes.** There is no history. There are no alerts. There is no way to search.

Here is what happens in practice today:

| Person | What they do today | Why it is painful |
|---|---|---|
| Junior advocate / clerk | Sits outside the courtroom all morning waiting for their case to be called | Wasted time — the case may be called at 11 AM or not at all |
| Senior advocate | Calls the clerk multiple times asking "has it come up yet?" | Interrupts the clerk who is also waiting outside another court |
| Client | Calls the advocate repeatedly asking for updates | Creates anxiety; advocate cannot give real-time answers without sitting in court |
| Out-of-town litigant | Has no way to know without travelling to Kolkata | Travel and hotel costs just to find out the case was adjourned |

### The Root Cause

The court publishes the data — both the live display board and the daily Cause List (the schedule of all hearings). But the data is only available in a raw, hard-to-use form:
- The live board requires manual refreshing and shows no history
- The Cause List is a long PDF — hundreds of pages — that requires manual searching

**EventTrace solves this by reading that same public data automatically, storing it, and presenting it in a clean, searchable, alert-ready format.**

---

> **Management Comments — Section 1:**
>
> _(Write your comments or questions here after reviewing)_

---

## 2. Who This Is Built For

Phase 1 targets three types of users:

### Primary User: The Advocate and Clerk

Advocates who appear regularly at Calcutta High Court and their clerks and juniors. They typically handle 5–20 cases every week. They need to know:
- Is my case listed today?
- What serial number is my case?
- When will my case approximately be called?
- What happened after the hearing?

### Secondary User: The Litigant (Client)

People who have a case in the High Court and want to track progress without having to call their lawyer every day. They need to know:
- Is my case listed this week?
- Did anything happen in my case today?

### Incidental User: The Researcher / Journalist

People who want to look up past hearings, check what cases a specific judge heard, or search by party name. This group uses the **search** feature without needing an account.

---

> **Management Comments — Section 2:**
>
> _(Write your comments or questions here after reviewing)_

---

## 3. What Makes EventTrace Different

The court's official website already shows some of this data. Why would anyone use EventTrace instead?

| Feature | Court Website | EventTrace Phase 1 |
|---|---|---|
| Live board | Shows, but must manually refresh | Auto-updates every 15 seconds, no action needed |
| History of what happened | No | Yes — every change stored with timestamps |
| Cause List search | No — only PDF download | Yes — search by advocate name, party name, case number |
| Personal case tracking | No | Yes — save your cases, get alerts |
| Email alert night before hearing | No | Yes — Phase 1 (free tier) |
| WhatsApp alert when case is called | No | Phase 2 (premium) |
| Works on mobile | Barely | Yes — built for mobile |
| Past cause lists | No | Yes — historical data kept |
| No login needed for basic use | N/A | Yes — search and board are public |

**The core difference: the court website is a data source. EventTrace is a product built on top of that data, designed for people who need to act on that data.**

---

> **Management Comments — Section 3:**
>
> _(Write your comments or questions here after reviewing)_

---

## 4. Phase 1 — What We Are Building

### 4.1 Live Display Board

**What it does:**
Shows what is happening right now in every courtroom at Calcutta High Court. The screen updates automatically every 15 seconds — no need to refresh.

**What the user sees:**
- Which court number is active
- Which serial number (case position in today's list) is currently being heard
- The case number on the board
- When it was last updated
- Which courts are not sitting today

**Why it matters:**
A junior clerk sitting outside Court 5 can open EventTrace on their phone and see "Court 5, Serial 12, WPA/101/2026" without walking into the courtroom. When the serial changes to 13, they know their case (which was Serial 12) has been heard and they can enter.

**Pain point it solves:**
Eliminates the need to physically sit outside the courtroom all morning. Also eliminates the back-and-forth phone calls between advocate and clerk asking "has it come up yet?"

**Status: Already built and working.**

---

### 4.2 Cause List Browser

**What it does:**
Shows the full schedule of hearings for any day — which cases are listed in which court, which judge is sitting, what the serial numbers are.

**What the user sees:**
- Select a date (today or any past date)
- See all courts for that date
- Click on a court to see all cases listed there
- Each case shows: serial number, case number, party names, advocate name, judge name

**Why it matters:**
The official Cause List is a PDF that can run to 300+ pages. Finding your case in it requires opening the file and using Control+F. EventTrace makes this instant — type a name, see all matching cases across all courts.

**Pain point it solves:**
Advocates and clerks currently either get the PDF early morning and scan it manually, or rely on the court notice board. Both are slow and error-prone.

**Status: Already built and working.** Historical dates are also available — users can look at any past Cause List.

---

### 4.3 Case Search

**What it does:**
A search box where any user (no login needed) can type an advocate name, party name, or case number and immediately see all matching results from the stored Cause Lists.

**What the user sees:**
- Search box with three fields: Advocate Name / Party Name / Case Number
- Results show: date, court, serial number, case number, both party names, advocate name
- Optional filters: date range, type of court (Appellate or Original Side)

**Why it matters:**
A client who wants to know "when is my case next listed?" can type their own name and find all appearances without calling their advocate. An advocate can quickly see "has Advocate Sharma appeared in Court 3 this week?" for conflict-of-interest checks.

**Pain point it solves:**
There is currently no way to search across multiple days of Cause Lists. You would have to download and search each day's PDF individually — a task that takes 20–30 minutes for a week's data.

**Status: Already built and working.**

---

### 4.4 Personal Dashboard — My Cases

**What it does:**
After signing up, users can save specific case numbers to their personal list. The dashboard shows, for each saved case:
- Is it listed today? If yes, in which court and which serial?
- When was it last heard?
- When is the next hearing date?
- A history of all past hearings for this case

**What the user sees:**
A clean card for each tracked case showing its current status, last update, and next scheduled date. Below this, a timeline showing the history: when it appeared in the Cause List, when it was called on the live board, any changes.

**Why it matters:**
An advocate managing 30 cases does not need to search for each case individually every morning. They open their dashboard, and immediately see which of their cases are listed today, what serial numbers they have, and which ones have upcoming dates.

**Pain point it solves:**
Advocates currently maintain manual registers or spreadsheets to track case dates. These get outdated quickly and require manual updating after each hearing.

**Status: Core tracking system is built. Dashboard view and case history timeline are being built in Phase 1.**

---

### 4.5 Alerts — Email Notifications

**What it does (Phase 1):**
One type of automatic alert in Phase 1:

**Alert — Evening before hearing:**
The evening before a case is listed for hearing, EventTrace automatically sends the user an email saying "Your case [Case Number] is listed tomorrow in Court 5, Serial 14."

Users can also set a serial preference ("notify me when Court 5 reaches Serial 10") — this is stored and will fire via email in Phase 1.

**What is NOT in Phase 1 — WhatsApp:**
WhatsApp alerts (the more immediate, push-style notifications) require India's DLT/TRAI regulatory approval for WhatsApp Business messaging. This process takes 1–4 weeks and involves third-party providers (MSG91, WATI). To avoid blocking the Phase 1 launch on an external dependency, **WhatsApp alerts move to Phase 2**.

Email alerts have no such dependency and can launch immediately.

**Why it matters:**
Even email-only alerts are a major improvement over the current situation where advocates have zero automated notification. Phase 2 WhatsApp alerts will be the premium upgrade.

**Pain point it solves:**
Advocates currently miss hearing dates or waste mornings waiting outside courtrooms. Email the night before removes the "surprise listing" problem for Phase 1.

**Status: Infrastructure is built. Email delivery via Resend — no external blockers, ~2–3 days to wire up.**

---

### 4.6 User Accounts

**What it does:**
Simple sign-up and login using a mobile phone number. User receives a 6-digit OTP on their phone to verify. No password required.

Google sign-in will also be available as an option.

**Why it matters:**
The My Cases dashboard and alert features require an account so the system knows which cases belong to which user.

**Pain point it solves:**
Keeps the system simple — no username, no password to forget. Phone number is what advocates use for all professional communication in India anyway.

**Status: Already built and working.** Phone OTP login is functional. Google login to be added in Phase 1 completion.

---

> **Management Comments — Section 4:**
>
> _(Write your comments or questions here after reviewing)_

---

## 5. What Is Already Working Today

| Feature | Status | Notes |
|---|---|---|
| Live Display Board | **Working** | Updates every 15 seconds, shows all courts |
| Cause List Browser | **Working** | Date picker, courts list, cases per court |
| Case Search | **Working** | Search by advocate, party, case number |
| User Login (Phone OTP) | **Working** | SMS OTP in production |
| My Cases — Track/Untrack | **Working** | Users can save and remove cases |
| Set Serial Alert | **Working** | Can set a "notify at Serial X" preference |
| User Profile | **Working** | Update name and email |
| Background data collection | **Working** | Runs 24/7, collects live board + cause lists |
| Database | **Working** | Supabase PostgreSQL — already on cloud |
| Website deployed | **Working** | Live on Vercel (public URL) |
| API deployed | **Working** | Live on Railway |
| HTTPS / Secure connection | **Working** | Both frontend and backend |

---

> **Management Comments — Section 5:**
>
> _(Write your comments or questions here after reviewing)_

---

## 6. What Still Needs to Be Built

These are the remaining items to complete Phase 1:

| Feature | Effort | Notes |
|---|---|---|
| Alert delivery — Email | 2–3 days | No external blocker — launches Phase 1 |
| Alert delivery — WhatsApp | Phase 2 | Requires India DLT regulatory approval; moved out of Phase 1 scope |
| Case history timeline view | 3–4 days | Shows history of past hearings per case |
| My Cases dashboard enrichment | 1 day | Show "last heard" and "next date" on each case card |
| Notification settings UI | 1 day | Let user turn alerts on/off |
| URL routing | 1 day | Makes pages bookmarkable and shareable |
| UI redesign | 3–4 days | Improve visual design across all pages |
| Error monitoring | Half day | Automatic alerts to us if the system breaks |
| Custom domain | Half day | Professional URL instead of default platform URL |

---

> **Management Comments — Section 6:**
>
> _(Write your comments or questions here after reviewing)_

---

## 7. How a Typical User Will Use EventTrace

### Scenario A — Junior Clerk Managing Multiple Cases

Mohan is a clerk for an advocate who has 8 cases listed this week.

**Monday morning:**
1. Opens EventTrace on his phone
2. Goes to My Dashboard — sees which of his advocate's cases are listed today
3. Court 3, Serial 5: "WPA/101/2026" — listed today
4. Has set a serial alert preference: "Notify me when Court 3 reaches Serial 3"
5. The previous evening he received an email: "WPA/101/2024 is listed for Monday, Court 3, Serial 5" — he informed the advocate in advance, no surprises
6. He checks EventTrace on his phone at 10 AM — sees Court 3 is at Serial 3, knows his case is next
7. Rushes to Court 3, arrives before Serial 5 is called
8. Case is heard, advocate gives instructions
9. That evening, EventTrace has already recorded the court appearance in the timeline

*(In Phase 2: step 6 becomes automatic — a WhatsApp push to his phone the moment Serial 3 is called, no need to check manually)*

---

### Scenario B — Client Tracking Their Own Case

Ananya has a property dispute case in the High Court. Her advocate is busy and she cannot get updates easily.

1. Signs up on EventTrace with her phone number
2. Adds her case number: "WP/234/2025"
3. EventTrace immediately shows her: "Last seen: 28 April 2026, Court 7, not taken up"
4. She receives an alert the evening before every time her case is listed
5. She can see the full history of her case — every time it appeared, what happened

She no longer needs to call her advocate just to find out the case status.

---

> **Management Comments — Section 7:**
>
> _(Write your comments or questions here after reviewing)_

---

## 8. Who Can Use What — Access Levels

```
WITHOUT AN ACCOUNT (any visitor)
  ├── View the live display board (all courts, real-time)
  ├── Browse the daily Cause List (any date)
  └── Search by advocate / party name / case number

FREE ACCOUNT (sign up with phone — freemium)
  ├── Everything above
  ├── Save up to 5 cases to personal dashboard
  ├── Receive email alerts (night before hearing)
  └── View case history timeline

PREMIUM ACCOUNT (Phase 2 — paid tier, exact pricing TBD)
  ├── Everything in Free
  ├── Track unlimited cases
  ├── WhatsApp alerts (real-time, when serial is called)
  ├── Serial-based push alerts
  └── Priority support

ADVOCATE PORTAL (Phase 2 — law firm features)
  ├── Everything in Premium
  ├── Billing and invoicing
  ├── Law firm shared workspace
  └── Client management
```

**Phase 1 model is freemium** — free account gives core value (dashboard + email alerts). The case tracking limit and WhatsApp alerts are the upgrade hook for Phase 2 premium tier. Exact pricing and limits to be confirmed by management before Phase 2.

---

> **Management Comments — Section 8:**
>
> _(Write your comments or questions here after reviewing)_

---

## 9. Running Cost for Phase 1

These are the monthly costs to run EventTrace after launch:

| What | Where it runs | Monthly Cost |
|---|---|---|
| Website (what users see) | Vercel | Free |
| Backend server | Railway | ~₹800 |
| Data collection workers | Railway | ~₹800 |
| Database | Supabase | Free (up to 500 MB) |
| Email alerts | Resend | Free (3,000 emails/month) |
| Error monitoring | Sentry | Free |
| Custom domain | Domain registrar | ~₹85/month (₹1,000/year) |

**Total: approximately ₹1,700–2,000/month**

*(Phase 2 adds WhatsApp messaging costs — approximately ₹2,000–3,000/month extra via MSG91/WATI)*

This is the cost to run the full platform. It does not increase unless the user base grows significantly (more than a few thousand users).

---

> **Management Comments — Section 9:**
>
> _(Write your comments or questions here after reviewing)_

---

## 10. Risks and How We Handle Them

| Risk | Likelihood | How We Handle It |
|---|---|---|
| Court website changes its layout | Low | Our system reads column names dynamically — does not break on cosmetic changes |
| Court blocks our scraper | Low | We use the same data endpoint the court's own display board uses. It is public data. |
| Server goes down | Low | Automatic restarts within seconds. Admin gets a Telegram alert. |
| Database fills up | Low | Current data is ~50 MB for one week. Free tier allows 500 MB. We trim unnecessary data. |
| WhatsApp DLT approval (Phase 2) | N/A Phase 1 | WhatsApp moved to Phase 2 — does not affect Phase 1 launch. Start DLT process in parallel. |
| More users than expected | Very Low (Phase 1) | System can handle thousands of users with no code changes. |

---

> **Management Comments — Section 10:**
>
> _(Write your comments or questions here after reviewing)_

---

## 11. What Phase 2 Will Add

Phase 2 is planned but not committed. It includes features for law firms and billing:

- **WhatsApp Alerts** — Real-time push notifications when serial is called on live board (requires DLT/TRAI approval — process to start during Phase 1)
- **Premium Tier** — Unlimited case tracking, WhatsApp alerts, priority support
- **Advocate Portal** — Role-based accounts for law firms (Senior Counsel, Junior, Clerk, Client)
- **Billing System** — Track court appearances and generate GST invoices automatically
- **Matter Management** — Organize cases by client, share access with team members
- **Order Tracking** — Download and search daily court orders (judgments)

Phase 2 builds on top of the Phase 1 foundation. None of Phase 2 is required for Phase 1 to be useful.

---

> **Management Comments — Section 11:**
>
> _(Write your comments or questions here after reviewing)_

---

## 12. Questions for Management Review

The following questions are open for management to answer before or after Phase 1 launch. They do not block Phase 1 development but will shape Phase 2.

### On the Freemium Model

1. What should the free tier case tracking limit be — 5 cases, 10 cases, or unlimited in Phase 1?
2. Should email alerts be free for all users, or gated behind a free account signup minimum?
3. Do we want to allow law firms to sign up as organizations, or only individual advocates in Phase 1?

### On Phase 2 Premium Tier (plan now, build later)

4. What is the target monthly price for a premium account (WhatsApp alerts, unlimited tracking)?
5. Should we offer an annual plan discount from day one of Phase 2 launch?
6. Should we require advocates to verify their Bar Enrollment Number for the premium tier?

### On Email Alerts (Phase 1)

7. Should the evening-before email be sent at a fixed time (e.g., 8 PM) or as soon as the Cause List is scraped (typically 9–10 PM)?
8. Should users be able to add multiple email addresses for alert delivery (e.g., both advocate and their clerk)?

### On WhatsApp Alerts (Phase 2 — plan now)

9. For WhatsApp: should both advocate and clerk get the alert, or one phone number only?
10. What should the WhatsApp template messages say? (Need to finalize for DLT/TRAI submission — start this process during Phase 1 build to have approval ready for Phase 2 launch.)

### On Data and Privacy

7. The Cause List data is public — it includes advocate names, party names, and case numbers. Are there any privacy concerns we need to address before publishing a searchable version?
8. Should we add an "opt-out" mechanism so an advocate can request not to appear in search results?

### On Scaling to Other Courts

11. **EventTrace is currently built for Calcutta High Court only.** The live board, cause list scraper, and search all read from Calcutta HC's specific website format. The question for management is: do we want to eventually expand this to other High Courts (Delhi, Bombay, Madras, Allahabad) or the Supreme Court?

    This matters now because the answer changes how we build Phase 1:
    - **If Calcutta-only forever:** current architecture is fine. No changes needed.
    - **If multi-court in future:** we should design Phase 1 with a `court_registry` concept — each court gets its own scraper config, its own data namespace, and its own cause list format handler. The core logic (change detection, search, alerts) stays the same; only the scraper adapts per court.

    The additional work to make Phase 1 "multi-court ready" is small (1–2 days of refactoring) but grows significantly if done later after data has accumulated.

    **Recommended question to answer before Phase 2 planning:** Should we target one more court (e.g., Delhi HC) as a Phase 2 expansion? If yes, we start building the multi-court adapter in Phase 1 backend.

### On Phase 1 Launch

12. Who are the first users we should onboard — our own team, specific advocates, or a public launch?
13. Is there a specific launch date target for Phase 1?
14. Should we build an admin panel to see how many users are signed up and which features they use?

---

*This document is the Phase 1 Business Requirements for EventTrace. It should be reviewed alongside the Technical Specification document (`TECH_SPEC.md`) which explains the same features from a developer perspective.*
