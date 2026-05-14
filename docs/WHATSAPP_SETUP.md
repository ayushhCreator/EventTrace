# WhatsApp Notification Setup — SuperSahayak Legal

## Overview

WhatsApp alerts are sent via **MSG91** using the WhatsApp Business API.
The same MSG91 account handles both SMS OTP and WhatsApp notifications.

---

## Environment Variables

```env
MSG91_AUTH_KEY=<your-authkey-from-msg91-dashboard>
MSG91_TEMPLATE_ID=<your-sms-otp-template-id>
MSG91_WHATSAPP_NUMBER=15559599221
```

Set these in `.env` locally and in **GCP Cloud Run environment variables** for production.

---

## Step 1 — MSG91 Account Setup

1. Sign up at [msg91.com](https://msg91.com)
2. Go to **API Keys** → create key named `supersahayak`
3. Set **IP Security**:
   - Local dev: whitelist your public IP (`curl api.ipify.org`)
   - Production: **disable IP security** (Cloud Run has dynamic IPs) or set up Cloud NAT for a static IP
4. Copy the auth key → set `MSG91_AUTH_KEY`

---

## Step 2 — SMS OTP Template

1. MSG91 → **OTP** → **Templates** → Create
2. Template body: `Your SuperSahayak Legal OTP is ##OTP##. Valid for 10 minutes. Do not share.`
3. Copy the **Template ID** → set `MSG91_TEMPLATE_ID`

---

## Step 3 — WhatsApp OTP (opens conversation window)

During registration, the user's phone number is used as their WhatsApp number.
An OTP is sent via WhatsApp to open the 24-hour conversation window, enabling
case alert templates to be delivered.

**Enable in MSG91:**
1. MSG91 → **OTP** → **Settings** → enable **WhatsApp** as OTP channel
2. No additional template needed — MSG91 uses their pre-approved authentication template

**How it works in code:**
```python
send_otp_msg91(phone, otp, settings, channel="whatsapp")
# calls POST https://api.msg91.com/api/v5/otp?type=whatsapp
```

---

## Step 4 — WhatsApp Notification Template

Template used for case alerts (hearing, causelist, serial alerts).

| Field | Value |
|---|---|
| Name | `hearing_alert2` |
| Category | **UTILITY** (not Marketing) |
| Language | English |
| Body | `SuperSahayak Legal Alert: {{1}} - SuperSahayak Legal` |

**Create in MSG91:**
1. MSG91 → **WhatsApp** → **Template Manager** → **Create New Template**
2. Fill in the fields above → Submit for Meta review
3. Wait for status **Enabled** (usually a few hours for UTILITY)

---

## Step 5 — Meta Business Verification (Permanent Fix)

Without verification, UTILITY templates only reach users who have messaged the
business number first (24-hour window). After verification, templates reach
anyone without prior contact.

**Steps:**
1. Go to [Meta Business Manager](https://business.facebook.com) → Settings → **Business Info**
2. Click **Start Verification**
3. Provide business documents (GST certificate, registered address)
4. Wait 1–3 business days for approval

Once verified, case alerts deliver to all users without the window restriction.

---

## How the Flow Works

```
User enters phone on signup
  → hint text: "Please enter your WhatsApp number to receive case alerts"
  → same number used for both SMS OTP and WhatsApp
  → OTP sent via SMS (MSG91)
  → OTP verified → phone auto-saved as whatsapp_number, whatsapp_verified = true

Case event fires (causelist, serial, hearing change)
  → notification_dispatch.py → enqueue_notification()
  → notification_retry_worker picks up queue
  → _send_msg91_whatsapp() → POST /whatsapp-outbound-message/bulk/
  → template: hearing_alert2, body_1 = formatted message
  → delivered to user's WhatsApp
```

---

## Delivery Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Error 131049 | No prior conversation / unverified account | Complete Meta Business Verification OR user messages business number first |
| `to_and_components received is Invalid` | Wrong payload format | `to_and_components` must be inside `template`, `components` is an object not array |
| 200 but not delivered | Template still PENDING | Wait for Meta approval (check Template Manager status) |
| MARKETING template fails silently | Wrong category | Recreate as UTILITY |

---

## MSG91 Payload Format (Reference)

```json
{
  "integrated_number": "15559599221",
  "content_type": "template",
  "payload": {
    "messaging_product": "whatsapp",
    "type": "template",
    "template": {
      "name": "hearing_alert2",
      "language": { "code": "en", "policy": "deterministic" },
      "namespace": "67e7d30e_07d9_45d3_9432_f8297495dbf1",
      "to_and_components": [
        {
          "to": ["917464026177"],
          "components": {
            "body_1": { "type": "text", "value": "message text here" }
          }
        }
      ]
    }
  }
}
```
