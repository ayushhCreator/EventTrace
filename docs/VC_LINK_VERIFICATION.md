# VC Link Mapping — Verification Report

**Date verified:** 2026-04-23  
**Display board date:** 2026-04-21 (Monday)  
**Total courts in display:** 32

---

## Source: Which Cause List

**URL scraped:**
```
https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla21042026.html
```

- `AS` = Appellate Side (principal bench daily cause list — covers both Appellate and Original Side courts)
- `cla21042026` = `cla{DD}{MM}{YYYY}` → 21 April 2026
- **Scraped at:** 2026-04-23 08:51 IST (manual test run)
- **VC links found in cause list:** 34 rooms

**Extraction method:** Playwright fetches the HTML, `inner_text("body")` strips tags, regex matches:
```
COURT NO. <N> ... VC LINK: https://...
```
between consecutive court blocks.

---

## Mapping Result: 32 Display Courts → 27 Got VC Link

| Room | Side | List Type | Serial | Judge(s) | VC Mapped | Notes |
|------|------|-----------|--------|----------|-----------|-------|
| 1 | AD | Daily | 92 | HON'BLE CHIEF JUSTICE SUJOY PAUL, HON'BLE JUSTICE CHAITALI CHATTERJEE (DAS) | ✅ | |
| 2 | AD | Daily | 33 | HON'BLE JUSTICE DINESH KUMAR SHARMA | ✅ | |
| 3 | AD | Daily | 9 | HON'BLE JUSTICE RAJA BASU CHOWDHURY | ✅ | |
| 5 | AD | Daily | 17 | HON'BLE JUSTICE SAUGATA BHATTACHARYYA | ✅ | |
| 8 | AD | Daily | 135 | HON'BLE JUSTICE ARIJIT BANERJEE, HON'BLE JUSTICE APURBA SINHA RAY | ✅ | |
| 9 | AD | Daily | 5-6 | HON'BLE JUSTICE BISWAROOP CHOWDHURY | ✅ | |
| 11 | AM | Monthly | 50 | HON'BLE JUSTICE TAPABRATA CHAKRABORTY, HON'BLE JUSTICE PARTHA SARATHI CHATTERJEE | ✅ | |
| 12 | AD | Daily | 1 | HON'BLE JUSTICE SHAMPA SARKAR, HON'BLE JUSTICE AJAY KUMAR GUPTA | ✅ | |
| 14 | AD | Daily | 5 | HON'BLE JUSTICE BIVAS PATTANAYAK | ✅ | |
| 15 | AD | Daily | 64 | HON'BLE JUSTICE SUVRA GHOSH | ✅ | |
| 18 | AD | Daily | 26 | HON'BLE JUSTICE AMRITA SINHA | ✅ | |
| 19 | AD | Daily | 203 | HON'BLE JUSTICE HIRANMAY BHATTACHARYYA | ✅ | |
| 23 | OD | Daily | 2 | HON'BLE JUSTICE ARINDAM MUKHERJEE | ❌ | IP Rights + general — no VC in cause list (in-person) |
| 23 | OD | Daily | 2 | HON'BLE JUSTICE ARINDAM MUKHERJEE | ❌ | Same bench, two benches on same room |
| 24 | AD | Daily | 21-25 | HON'BLE JUSTICE REETOBROTO KUMAR MITRA | ✅ | |
| 25 | AD | Daily | 22 | HON'BLE JUSTICE KRISHNA RAO | ✅ | |
| 28 | AD | Daily | 9 | HON'BLE JUSTICE JAY SENGUPTA | ✅ | |
| 29 | AD | Daily | 129-130 | HON'BLE Dr. JUSTICE AJOY KUMAR MUKHERJEE | ✅ | |
| 30 | AD | Daily | 20 | HON'BLE JUSTICE SHAMPA DUTT (PAUL) | ✅ | |
| 35 | AD | Daily | 71 | HON'BLE JUSTICE TIRTHANKAR GHOSH | ✅ | |
| 36 | OS | Supplementary | 1 | HON'BLE JUSTICE GAURANG KANTH | ❌ | Commercial — no VC in cause list |
| 36 | OD | Daily | 30 | HON'BLE JUSTICE GAURANG KANTH | ❌ | No VC in cause list |
| 37 | AD | Daily | 9 | HON'BLE JUSTICE DEBANGSU BASAK, HON'BLE JUSTICE MD. SHABBAR RASHIDI | ✅ | Same Zoom link for both benches in room 37 |
| 37 | OM | Monthly | 62-66 | HON'BLE JUSTICE DEBANGSU BASAK, HON'BLE JUSTICE MD. SHABBAR RASHIDI | ✅ | Same Zoom link as AD bench |
| 38 | OD | Daily | 14 | HON'BLE JUSTICE ANIRUDDHA ROY | ✅ | Commercial matters |
| 40 | AD | Daily | 32 | HON'BLE JUSTICE SUGATO MAJUMDAR | ✅ | Same Zoom link for both benches |
| 40 | OD | Daily | 8 | HON'BLE JUSTICE SUGATO MAJUMDAR | ✅ | Same Zoom link as AD bench |
| 237 | AD | Daily | 3 | HON'BLE JUSTICE KAUSIK CHANDA | ✅ | Non-standard room no. but matched |
| 238 | AD | Daily | 1-5 | HON'BLE JUSTICE RAJARSHI BHARADWAJ, HON'BLE JUSTICE UDAY KUMAR | ✅ | Same Zoom link for both benches |
| 238 | OD | Daily | 1 | HON'BLE JUSTICE RAJARSHI BHARADWAJ, HON'BLE JUSTICE UDAY KUMAR | ✅ | Same Zoom link as AD bench |
| 655 | AD | Daily | 79 | HON'BLE JUSTICE PRASENJIT BISWAS | ✅ | Non-standard room no. but matched |
| 759 | OD | Daily | 29-31 | HON'BLE JUSTICE RAJARSHI BHARADWAJ, HON'BLE JUSTICE UDAY KUMAR | ❌ | Room 759 not in cause list |

---

## Summary

| Metric | Count |
|--------|-------|
| Courts in display board (Apr 21) | 32 |
| Courts with VC link mapped | **27** |
| Courts without VC link | **5** |
| VC links scraped from cause list | 34 |
| Extra links scraped (not in display) | 7 (rooms 4, 21, 22, 32, 33, 34, 236, 550, 551, 652) |

---

## Why Some Courts Have No VC Link

| Room | Reason |
|------|--------|
| 23 | IP Rights + general Original Side — court 23 not present in cause list VC section (in-person) |
| 36 | Court 36 not listed in cause list at all — likely always in-person |
| 759 | Room number 759 does not appear in the cause list (may be a virtual/special bench) |

---

## Mapping Key

```
display_api.json field:  room_no  (e.g. "1", "37", "237")
cause list text:         COURT NO. 1, COURT NO. 37, COURT NO. 237
DB table:                vc_zoom_link (date, room_no, zoom_url)
```

Both Appellate and Original Side benches sharing a room get the **same Zoom link** (e.g. rooms 37, 38, 40, 238) — this is correct, the physical room has one VC session regardless of which bench/side is sitting.

---

## DB State After Test

```sql
SELECT date, COUNT(*) FROM vc_zoom_link GROUP BY date;
-- 2026-04-21 | 34
```
