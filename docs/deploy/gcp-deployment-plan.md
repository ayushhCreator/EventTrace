# GCP Deployment Plan

## What was done and why

### 1. SQLAlchemy ORM + Alembic migrations
**Files:** `src/eventtrace/storage/models.py`, `src/eventtrace/storage/repositories/*_alchemy.py`, `alembic.ini`, `alembic/`
**Old files deleted:** `storage/repositories/{auth,causelist,events,subscriptions,timeline}.py`

Raw psycopg2 SQL repos were hand-rolled and duplicated schema logic across Postgres and SQLite backends. Replaced with:
- `models.py` — single source of truth for DB schema (SQLAlchemy declarative)
- Five `*_alchemy.py` repos — same interface, ORM-backed, work with both backends
- Alembic for schema migrations — `alembic upgrade head` runs before each deploy, no more `ensure_schema()` on startup
- `alembic/env.py` reads `DATABASE_URL` from env, falls back to SQLite in `alembic.ini`

### 2. HMAC OTP, rate limiting, structlog
**Files:** `src/eventtrace/routes/auth.py`, `src/eventtrace/services/auth.py`, `src/eventtrace/core/logging_setup.py`

- OTP is HMAC-signed (OTP_HMAC_SECRET) — prevents brute-force enumeration without a DB lookup
- slowapi rate limiting on OTP send/verify endpoints
- structlog replaces print/logging — JSON output in prod, colored console in dev
- httpOnly cookies for JWT (not just Authorization header)

### 3. Causelist + monitor wired to SQLAlchemy repos
All causelist scrapers, parser, scheduler, monitor, init_session updated to use `*_alchemy.py` repos instead of deleted raw repos.

### 4. GCP Cloud Run deployment infrastructure
**Files:** `Dockerfile.api`, `Dockerfile.scraper`, `.github/workflows/deploy.yml`, `gcloud-setup.sh`

Split single Dockerfile into three images:
- `Dockerfile.api` — FastAPI only, no Playwright, port 8080 (Cloud Run requirement)
- `Dockerfile.scraper` — Playwright + Chromium; deployed as two Cloud Run services (`eventtrace-monitor` min-instances=1, `eventtrace-scheduler` min-instances=1) using same image with different CMD
- `Dockerfile.web` (in EventTrace-Web) — multi-stage Node build → nginx, port 8080

GitHub Actions workflow (`.github/workflows/deploy.yml`) — 4 jobs:
1. `build-backend` — build + push `api` and `scraper` images to Artifact Registry
2. `migrate` — deploys + executes `eventtrace-migrate` Cloud Run Job (`alembic upgrade head`) against Cloud SQL via Unix socket
3. `deploy-backend` — deploys `eventtrace-api`, `eventtrace-monitor`, `eventtrace-scheduler` with secrets from Secret Manager
4. `deploy-web` — checks out EventTrace-Web repo, `npm run build`, deploys to Firebase Hosting

Cloud SQL connection uses Unix socket (`/cloudsql/PROJECT:REGION:INSTANCE`) — no proxy needed. `--add-cloudsql-instances` flag wired on all four Cloud Run services.

### 5. CORS updated for Firebase Hosting
Added to `api.py` defaults: `eventtrace.web.app`, `eventtrace.firebaseapp.com`, `eventtrace.in`, `www.eventtrace.in`.
Existing `CHD_CORS_ORIGINS` env var still works for arbitrary additions.

### 6. Frontend deploy config (EventTrace-Web)
- `.env.production` — `VITE_API_URL=https://api.eventtrace.in`
- `firebase.json` — SPA rewrites + asset cache headers
- `nginx.conf` — for Cloud Run alternative hosting (SPA routing + gzip)

---

## What you need to do

### Locally (one-time setup)

1. **Edit `gcloud-setup.sh`** — fill in:
   ```
   PROJECT_ID="your-gcp-project-id"
   SQL_PASSWORD="a-real-strong-password"
   ```

2. **Run it:**
   ```bash
   gcloud auth login
   bash gcloud-setup.sh
   ```
   Takes ~5 min (Cloud SQL provisioning). At the end it prints all GitHub Secrets you need.

3. **Generate deploy service account key** (printed at end of script):
   ```bash
   gcloud iam service-accounts keys create /tmp/deploy-key.json \
     --iam-account eventtrace-deploy@PROJECT_ID.iam.gserviceaccount.com
   cat /tmp/deploy-key.json   # copy this
   rm /tmp/deploy-key.json
   ```

4. **Update MSG91 secrets** (script sets placeholder values):
   ```bash
   echo -n "YOUR_REAL_MSG91_AUTH_KEY" | gcloud secrets versions add MSG91_AUTH_KEY --data-file=-
   echo -n "YOUR_REAL_MSG91_TEMPLATE_ID" | gcloud secrets versions add MSG91_TEMPLATE_ID --data-file=-
   ```

5. **Firebase init** (in EventTrace-Web):
   ```bash
   npm install -g firebase-tools
   firebase login
   cd /home/ayush-raj/The_Base/EventTrace-Web
   firebase init hosting
   # public dir: dist
   # SPA rewrite: yes
   # overwrite index.html: no
   ```
   Update `firebase.json` project ID if different from GCP project ID.

### In GCP Console (cannot script)

| What | Where |
|------|-------|
| Enable billing on project | Billing → link account |
| Verify Cloud SQL instance is running | SQL → eventtrace-pg |
| First manual migration run (before first deploy) | Cloud Run Jobs → eventtrace-migrate → Execute |
| Map custom domain `eventtrace.in` to Firebase Hosting | Firebase console → Hosting → Add custom domain |
| Map `api.eventtrace.in` to Cloud Run API service | Cloud Run → eventtrace-api → Manage Custom Domains |
| Firebase project: add Google Analytics (optional) | Firebase console |

### In GitHub (one-time)

Go to repo Settings → Secrets and variables → Actions → New repository secret:

| Secret name | Value |
|-------------|-------|
| `GCP_PROJECT_ID` | your GCP project ID |
| `GCP_SA_KEY` | JSON from deploy service account key |
| `GCP_RUN_SA_EMAIL` | `eventtrace-runtime@PROJECT_ID.iam.gserviceaccount.com` |
| `VITE_API_URL` | Cloud Run API URL (get after first deploy) — or `https://api.eventtrace.in` if custom domain ready |
| `WEB_REPO` | `your-github-username/EventTrace-Web` |
| `FIREBASE_SERVICE_ACCOUNT` | Firebase service account JSON (Firebase console → Project Settings → Service Accounts → Generate new private key) |

### After first deploy

1. Get API service URL:
   ```bash
   gcloud run services describe eventtrace-api --region asia-south1 --format 'value(status.url)'
   ```
2. Set `VITE_API_URL` GitHub secret to that URL (or your custom domain once mapped)
3. Push any commit to trigger a re-deploy — now the frontend will point to the live API

---

## Deploy order (first time)

```
bash gcloud-setup.sh
          ↓
Set GitHub Secrets
          ↓
firebase init hosting (local, one-time)
          ↓
git push main → GitHub Actions fires:
  build-backend → migrate → deploy-backend → deploy-web
          ↓
Verify: curl https://YOUR-API-URL/current-state
          ↓
Map custom domains in GCP console + Firebase console
          ↓
Update VITE_API_URL secret → push again to redeploy frontend with final URL
```
