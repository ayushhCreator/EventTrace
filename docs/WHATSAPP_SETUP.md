# WhatsApp Notification Setup via MSG91 — Complete Guide

## What You're Building

```
Your phone number → WhatsApp Business API (via Meta) → MSG91 manages sending → App calls MSG91 API → Users get WhatsApp notifications
```

---

## PHASE 0: Prerequisites

| Item | Why Needed |
|------|-----------|
| Personal Facebook account | To create Meta Business Portfolio |
| Phone number to use | Must NOT be active on any WhatsApp app right now |
| Business email | Meta sends verification to this |
| Working website URL | For Meta business verification |
| MSG91 account | Already have (used for OTP) |

> **Critical:** If your number is on WhatsApp or WhatsApp Business app on any phone — delete that account first from app settings. After that, the number can only be used via API.

---

## PHASE 1: Fix the Website URL Error

**Why `supersahayak.com` failed:**
- `Server: DPS/2.0.0` = GoDaddy Domain Parking Service. Domain is parked, showing a placeholder page. Meta detects this ≠ real business site.

**Why `legal.supersahayak.com` failed:**
- `content-length: 1111` = React SPA — only 1KB HTML shell. Meta's crawler doesn't execute JavaScript, so it sees near-zero content.

**Fix applied:** Added OG meta tags to `EventTrace-Web/index.html` so Meta's crawler reads page metadata without JS.

**Options if still failing:**

```bash
# Option A: verify root domain actually returns 200
curl -I https://supersahayak.com

# Option D: check robots.txt isn't blocking all crawlers
# https://supersahayak.com/robots.txt — make sure no: Disallow: /
```

- **Option B:** Temporarily disable Cloudflare "Under Attack Mode" / JS challenge during Meta verification
- **Option C:** Use Facebook Business Page URL instead — Meta trusts their own platform

---

## PHASE 2: Create Meta Business Portfolio

1. Go to **business.facebook.com**
2. Log in with personal Facebook account
3. Click **"Create Account"**
4. Fill in: Business name, full name, business email
5. Click verification link in email
6. Business Settings → **Business Info** → enter website URL (`legal.supersahayak.com`)
7. Complete **Business Verification** — upload GST certificate or bank statement

> Unverified = 250 conversations/day limit. Verified = up to 100,000/day.

---

## PHASE 3: Add WhatsApp Number via MSG91

1. Log into **msg91.com**
2. Go to **WhatsApp → Numbers → Add Number**
3. Click **"Connect Facebook"** (opens Meta Embedded Signup)
4. Log in with the Facebook account that owns your Business Portfolio
5. Select Business Portfolio
6. Choose **"Create a new WhatsApp Business Account"**
7. Enter:
   - WABA name: `SuperSahayak Legal`
   - Display name: `SuperSahayak Legal`
   - Business category: `Legal Services`
8. Enter phone number with country code: `+91XXXXXXXXXX`
9. Verify via SMS or Voice Call
10. Done — number connected to MSG91

---

## PHASE 4: Add Credits to WhatsApp Wallet

1. MSG91 dashboard → **WhatsApp → Wallet**
2. Add balance (start ₹500–1000 to test)
3. Set auto-recharge: trigger when balance < ₹200

**Pricing (India 2025):** ~₹0.58/utility message · ~₹0.83/marketing message

---

## PHASE 5: Create a Message Template

WhatsApp requires pre-approved templates for outbound notifications.

1. MSG91 → **WhatsApp → Templates → Create Template**
2. Category: **Utility** (for hearing reminders, case updates)
3. Example template body:

   ```
   Court Update: Your case {{case_number}} is listed for hearing on {{date}} at {{court_name}}, Court No. {{court_no}}. - SuperSahayak Legal
   ```

4. Add sample values for each variable
5. Submit → Meta reviews in minutes to 48 hours
6. Status turns **green** = approved and ready

---

## PHASE 6: Send Notifications via MSG91 API

```python
import httpx

async def send_whatsapp_notification(
    phone: str, case_number: str, date: str, court_name: str, court_no: str
):
    url = "https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/bulk/"
    headers = {
        "authkey": "YOUR_MSG91_AUTHKEY",  # same key used for OTP
        "Content-Type": "application/json",
    }
    payload = {
        "integrated_number": "YOUR_WHATSAPP_NUMBER",
        "content_type": "template",
        "payload": {
            "to": f"91{phone}",  # country code + number, no +
            "type": "template",
            "template": {
                "name": "your_template_name",  # exact name from MSG91 dashboard
                "language": {"code": "en", "policy": "deterministic"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": case_number},
                            {"type": "text", "text": date},
                            {"type": "text", "text": court_name},
                            {"type": "text", "text": court_no},
                        ],
                    }
                ],
            },
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers)
        return resp.json()
```

`MSG91_AUTH_KEY` is already set in env vars — same key used for OTP, no new account needed.

---

## PHASE 7: Add Env Vars

Add to `.env` and GCP Secret Manager:

```bash
WHATSAPP_NUMBER=91XXXXXXXXXX          # your registered number
MSG91_WA_TEMPLATE_HEARING=your_template_name
```

---

## Messaging Limits

| Status | Daily Limit |
|--------|------------|
| New unverified | 250 conversations |
| Business verified | 1,000 |
| After 1k sent + good quality | 10,000 |
| Higher tier | 100,000+ |

---

## Action Order

1. Verify `legal.supersahayak.com` works in Meta setup (OG tags added — already deployed)
2. Create Meta Business Portfolio at business.facebook.com
3. Add WhatsApp number through MSG91 dashboard (Embedded Signup)
4. Add wallet balance
5. Create utility template for hearing reminders
6. Test send to your own number
7. Wire `send_whatsapp_notification()` into the notification system

---

## References

- [MSG91 WhatsApp Help](https://msg91.com/help/whatsapp)
- [MSG91 Onboarding Guide](https://msg91.com/help/whatsapp/whatsapp-number-integration---onboarding)
- [MSG91 Template Creation](https://msg91.com/help/MSG91/how-to-create-a-template-for-whatsapp)
- [Meta WhatsApp Business Docs](https://developers.facebook.com/docs/whatsapp/overview/business-accounts)
