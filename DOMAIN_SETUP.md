# Domain Setup — legal.supersahayak.com

Target: `legal.supersahayak.com` → Firebase Hosting (frontend)

---

## Step 1 — Add domain to Firebase Hosting

Go to Firebase Console → Hosting → Add custom domain:
`https://console.firebase.google.com/project/legalsupersahayak/hosting`

1. Click **Add custom domain**
2. Enter `legal.supersahayak.com`
3. Firebase shows **2 TXT records** (ownership verification) + **2 A records** (traffic)
4. Copy all 4 records — needed for GoDaddy

---

## Step 2 — Add DNS records in GoDaddy

Go to: `https://dcc.godaddy.com/manage/supersahayak.com/dns`

Add these (exact values come from Firebase in Step 1):

| Type | Name | Value |
|------|------|-------|
| TXT | `legal` | `firebase=xxx...` (from Firebase) |
| A | `legal` | `151.101.1.195` (from Firebase) |
| A | `legal` | `151.101.65.195` (from Firebase) |

> Delete any existing conflicting records for `legal` before adding.

---

## Step 3 — Wait + Verify

- DNS propagation: **5 min – 48 hours** (usually under 1 hour with GoDaddy)
- Firebase auto-provisions SSL certificate once DNS verified
- Firebase Console status progression: **Needs verification → Certificate provisioning → Connected**

---

## Optional: api.supersahayak.com → Cloud Run API

If you want `api.supersahayak.com` pointing to the Cloud Run API:

1. Add CNAME in GoDaddy:

   | Type | Name | Value |
   |------|------|-------|
   | CNAME | `api` | `ghs.googlehosted.com` |

2. Map domain in Cloud Run:
   ```bash
   gcloud beta run domain-mappings create \
     --service supersahayak-api \
     --domain api.supersahayak.com \
     --region asia-south1 \
     --project supersahayak
   ```

3. Cloud Run gives you DNS records — add them to GoDaddy same as above.

4. Update `_VITE_API_URL` in `cloudbuild.yaml` to `https://api.supersahayak.com`.
