# 📘 Real-Time Court Display Scraper & Change Tracking System

---

# 🧾 1. Project Overview

## 🎯 Objective

Build a system that:

* Scrapes data from the Calcutta High Court Display Board
* Tracks **changes in table fields over time**
* Records:

  * What data was present
  * When it appeared
  * When it changed
  * How long it remained unchanged (duration)
* Outputs structured **change logs**

---

## 🌐 Target Website

* Display Board: https://display.calcuttahighcourt.gov.in/principal.php

### ⚠️ Important Characteristics

* Requires CAPTCHA validation
* Data loads dynamically after CAPTCHA
* Page auto-refreshes every ~15 seconds ([Calcutta High Court][1])
* Table structure may change over time
* Anti-scraping protections may exist (CAPTCHA, JS rendering) ([Vidhi Legal Policy][2])

---

# 🧠 2. Problem Definition

We are NOT building a simple scraper.

We are building a:

> ⚡ **Real-time state monitoring + change detection system**

---

## 📊 Input

Dynamic HTML table like:

* Court
* Judge(s) Coram
* Serial No(s)
* (Fields may change)

---

## 📤 Output

Example:

```
Case: Court 5

History:
----------------------------------
10:00 → 10:02 → Serial: 12
10:02 → 10:05 → Serial: 15
----------------------------------

Changes:
12 → 15 (3 minutes)
```

---

# 🏗️ 3. System Architecture

```
[ Browser Automation ]
        ↓
[ Data Extractor ]
        ↓
[ Data Normalizer ]
        ↓
[ Change Detection Engine ]
        ↓
[ Database ]
        ↓
[ API / Output Layer ]
        ↓
[ Dashboard / Logs / Alerts ]
```

---

# 🧰 4. Tech Stack

## 🔹 Scraping Layer

* Python
* Playwright (REQUIRED)

  * Handles:

    * CAPTCHA session
    * JavaScript rendering
    * Auto-refresh content

---

## 🔹 Backend

* FastAPI (API layer)
* Python core logic

---

## 🔹 Database

* PostgreSQL (recommended)
* Alternative: SQLite (for prototype)

---

## 🔹 Scheduler

* Simple: Python loop (`time.sleep`)
* Advanced:

  * Celery + Redis
  * Cron jobs

---

## 🔹 Frontend (Optional)

* React / Next.js dashboard

---

# 🔍 5. Data Extraction Strategy

## ❗ Key Requirement

Do NOT hardcode fields.

👉 Use **dynamic header detection**

---

## ✅ Step 1: Extract Headers

```python
headers = [th.text.strip() for th in page.query_selector_all("table th")]
```

---

## ✅ Step 2: Extract Rows

```python
rows = []
for tr in page.query_selector_all("table tr")[1:]:
    cols = [td.inner_text().strip() for td in tr.query_selector_all("td")]
    row_dict = dict(zip(headers, cols))
    rows.append(row_dict)
```

---

## ✅ Output Format

```json
[
  {
    "Court": "Court 1",
    "Judge(s) Coram": "Justice ABC",
    "Serial No(s).": "12"
  }
]
```

---

# 🔄 6. Change Detection Engine

## 🎯 Goal

Detect when any field changes.

---

## 🧠 Strategy

Use:

* Previous snapshot
* Current snapshot

---

## ✅ Example

```python
if old_data[key] != new_data[key]:
    detect_change()
```

---

## 🔑 Unique Identifier

Use:

* "Court" as primary key (or combination)

```python
data["Court 5"] = {...}
```

---

# ⏱️ 7. Time Tracking Logic

## Data Model

```json
{
  "value": "12",
  "start_time": "10:00:00",
  "end_time": "10:02:30"
}
```

---

## Logic

1. When value first appears:
   → store start_time

2. When value changes:
   → set end_time
   → calculate duration

---

# 🗄️ 8. Database Design

## Table: current_state

```
id
court_id
data_json
last_updated
```

---

## Table: change_history

```
id
court_id
field_name
old_value
new_value
start_time
end_time
duration
```

---

# ⚙️ 9. Scraping Loop

## Basic Version

```python
while True:
    new_data = scrape()
    compare_with_old(new_data)
    sleep(10)
```

---

## Recommended Interval

* 10–30 seconds
  (because site auto-refreshes ~15 sec)

---

# 🤖 10. Playwright Flow

## Steps

1. Launch browser
2. Open site
3. Solve CAPTCHA manually (first time)
4. Save session
5. Reuse session
6. Extract table every interval

---

# 📊 11. Output Layer

## Options

### CLI Logs

```
[10:05:30] Court 5 → Serial changed 12 → 15
```

---

### API (FastAPI)

Endpoints:

```
GET /current-state
GET /history
GET /changes
```

---

### Dashboard

* Live table
* Change timeline
* Filters

---

# 🔔 12. Optional Features

* Telegram alerts
* Email notifications
* Webhooks

---

# ⚠️ 13. Challenges & Solutions

## ❗ CAPTCHA

Problem:

* Blocks automated scraping

Solution:

* Manual solve + session reuse

---

## ❗ Dynamic Content

Problem:

* Data not in raw HTML

Solution:

* Use Playwright (browser automation)

---

## ❗ Anti-Scraping

Problem:

* IP blocking

Solution:

* Add delays
* Avoid aggressive scraping

---

# 🚀 14. Future Improvements

* WebSocket live updates
* AI-based anomaly detection
* Multi-court scraping
* Distributed workers

---

# 🧠 15. Final Summary

This system is:

> ❌ NOT just scraping
> ✅ A real-time monitoring + event tracking system

Core pillars:

* Dynamic scraping
* State comparison
* Time tracking
* Persistent storage

---

# 📌 16. Implementation Checklist

✅ Setup Playwright
✅ Extract table dynamically
✅ Build JSON structure
✅ Store previous state
✅ Compare changes
✅ Track timestamps
✅ Save history
✅ Build API / logs

---

# 🏁 End of Document

[1]: https://www.calcuttahighcourt.gov.in/Display-Board-New?utm_source=chatgpt.com "Display Board at Principal Bench,CHC"
[2]: https://vidhilegalpolicy.in/wp-content/uploads/2020/06/OpenCourts_digital16dec.pdf?utm_source=chatgpt.com "Open Courts in the Digital Age : A Prescription for an ..."
