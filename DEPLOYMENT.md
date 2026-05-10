# SuperSahayak — Deployment Guide

## Architecture Overview

```
GitHub push → Cloud Build (12 steps)
                ├── Build Docker images (api, scraper)
                ├── Push to Artifact Registry
                ├── Run Alembic DB migration (Cloud Run Job)
                ├── Deploy Cloud Run services (api, monitor, scheduler)
                └── Build + deploy React frontend (Firebase Hosting)
```

**Live URLs:**
- API: `https://supersahayak-api-1085288406739.asia-south1.run.app`
- Frontend: Firebase Hosting (`legalsupersahayak` project)

---

## How Deployments Work

Every `git push` to `main` triggers the Cloud Build trigger `supersahayak-deploy` automatically.

### Pipeline steps (cloudbuild.yaml)

| Step | What it does |
|------|-------------|
| 0: build-api | Docker build from `Dockerfile.api` |
| 1: build-scraper | Docker build from `Dockerfile.scraper` |
| 2: push-api | Push api image to Artifact Registry |
| 3: push-scraper | Push scraper image to Artifact Registry |
| 4: deploy-migrate-job | Update the `supersahayak-migrate` Cloud Run Job definition |
| 5: run-migrate | Execute the job — runs `alembic upgrade head` against Cloud SQL |
| 6: deploy-api | Deploy API service (public, port 8080) |
| 7: deploy-monitor | Deploy monitor service (internal, min 1 instance) |
| 8: deploy-scheduler | Deploy scheduler service (internal, min 1 instance) |
| 9: clone-web | Clone `ayushhCreator/EventTrace-Web` using GH_PAT secret |
| 10: build-web | `npm ci && npm run build` with `VITE_API_URL` injected |
| 11: deploy-firebase | Deploy built frontend to Firebase Hosting |

### Trigger daily deploy manually

```bash
gcloud builds triggers run supersahayak-deploy \
  --branch=main \
  --project=supersahayak \
  --region=global
```

Or push any commit to `main` — build fires automatically.

### Check build status

```bash
# CLI
gcloud builds list --project=supersahayak --limit=5 \
  --format="table(id,status,createTime,duration)"

# Logs for a specific build
gcloud builds log BUILD_ID --project=supersahayak
```

Browser: https://console.cloud.google.com/cloud-build/builds?project=supersahayak

---

## Secrets Management

All secrets live in **Google Cloud Secret Manager** (project: `supersahayak`).

### Current secrets

| Secret name | Used by | Description |
|-------------|---------|-------------|
| `DATABASE_URL` | api, monitor, scheduler, migrate job | Postgres connection string (Cloud SQL via Unix socket) |
| `JWT_SECRET` | api | Signs auth tokens |
| `MSG91_AUTH_KEY` | api | MSG91 OTP delivery |
| `MSG91_TEMPLATE_ID` | api | MSG91 OTP template |
| `OTP_HMAC_SECRET` | api | HMAC key for OTP signing |
| `GH_PAT` | Cloud Build (clone-web step) | GitHub Personal Access Token to clone EventTrace-Web |
| `FIREBASE_SERVICE_ACCOUNT` | Cloud Build (deploy-firebase step) | Firebase service account JSON |

### Add a new secret (e.g. MSG91_AUTH_KEY)

```bash
# 1. Create the secret
gcloud secrets create MSG91_AUTH_KEY \
  --project=supersahayak \
  --replication-policy=automatic

# 2. Set its value
echo -n "your_actual_value_here" | gcloud secrets versions add MSG91_AUTH_KEY \
  --project=supersahayak \
  --data-file=-
```

> Use `echo -n` (no newline) — a trailing newline breaks the value.

### Update an existing secret (rotate / change value)

```bash
echo -n "new_value_here" | gcloud secrets versions add SECRET_NAME \
  --project=supersahayak \
  --data-file=-
```

Secret Manager keeps all versions. Cloud Run and Cloud Build always fetch `latest`.

### Add secret to a Cloud Run service

After creating the secret, add it to the relevant service in `cloudbuild.yaml`:

```yaml
--set-secrets DATABASE_URL=DATABASE_URL:latest,NEW_SECRET=NEW_SECRET:latest
```

Then push — next build redeploys the service with the new secret mounted as an env var.

### Grant Cloud Run SA access to a new secret

If you create a new secret, the service account must have access:

```bash
gcloud secrets add-iam-policy-binding NEW_SECRET \
  --project=supersahayak \
  --member="serviceAccount:supersahayak-run-sa@supersahayak.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## Database Migrations

Migration runs automatically in every build (step 5). Uses Alembic.

### How it works

- Migration file: `alembic/versions/0001_create_all_tables.py`
- Uses `Base.metadata.create_all(checkfirst=True)` — safe to run on existing DB (won't drop/recreate tables)
- Connects via Cloud SQL Unix socket: `/cloudsql/supersahayak:asia-south1:supersahayak-pg`

### Run migration manually

```bash
gcloud run jobs execute supersahayak-migrate \
  --region=asia-south1 \
  --wait \
  --project=supersahayak
```

### Add a new migration (schema change)

```bash
# Generate
alembic revision --autogenerate -m "add_column_xyz"

# Test locally
alembic upgrade head

# Commit — runs automatically on next push
git add alembic/versions/
git commit -m "feat(db): add xyz column"
git push
```

---

## Errors Encountered During Initial Setup

### 1. `PERMISSION_DENIED: run.jobs.get`
**Cause:** Service account `supersahayak-run-sa` lacked `roles/run.admin`.  
**Fix:**
```bash
gcloud projects add-iam-policy-binding supersahayak \
  --member="serviceAccount:supersahayak-run-sa@supersahayak.iam.gserviceaccount.com" \
  --role="roles/run.admin"
```

### 2. `No 'script_location' key found in configuration` (exit 255)
**Cause:** `Dockerfile.api` didn't copy `alembic.ini` or `alembic/` into the image — Alembic couldn't find its config.  
**Fix:** Added to `Dockerfile.api`:
```dockerfile
COPY alembic.ini .
COPY alembic/ alembic/
```

### 3. `password authentication failed for user "supersahayak"`
**Cause:** DB password contained `@` and `#` characters. psycopg2 URL parser treated `@` as the host separator, truncating the password.  
**Fix:** Changed DB password to alphanumeric only (`SuperSahayak74db`), updated Cloud SQL user and `DATABASE_URL` secret.

### 4. `DATABASE_URL` truncated in Secret Manager
**Cause:** Terminal line-wrapping truncated the long URL when using `echo` or heredoc to pipe into `gcloud secrets versions add`.  
**Fix:** Wrote the value via a Python script file to avoid shell line-wrapping:
```bash
python3 -c "open('/tmp/db_url.txt', 'w').write('postgresql://...')"
gcloud secrets versions add DATABASE_URL --data-file=/tmp/db_url.txt
```

### 5. `table "profiles" does not exist` (ProgrammingError)
**Cause:** The original Alembic migration was auto-generated as a *diff* from a dev SQLite DB. It assumed tables already existed and started with `op.drop_table('profiles')`. On a fresh empty Cloud SQL Postgres DB, this fails immediately.  
**Fix:** Deleted both old diff migrations. Created a single clean migration (`0001_create_all_tables.py`) using `Base.metadata.create_all(checkfirst=True)` — creates all tables from scratch on any empty DB.

---

## Infrastructure Reference

| Resource | Value |
|----------|-------|
| GCP Project | `supersahayak` |
| Region | `asia-south1` |
| Artifact Registry | `asia-south1-docker.pkg.dev/supersahayak/supersahayak` |
| Cloud SQL instance | `supersahayak:asia-south1:supersahayak-pg` (Postgres 16) |
| Cloud SQL DB | `supersahayak` |
| Cloud SQL user | `supersahayak` |
| Service account | `supersahayak-run-sa@supersahayak.iam.gserviceaccount.com` |
| Firebase project | `legalsupersahayak` |
| Cloud Build trigger | `supersahayak-deploy` |

---

## Adding a New Environment Variable to Production

1. **Create secret** in Secret Manager (see above)
2. **Grant SA access** to the secret (see above)  
3. **Add to `cloudbuild.yaml`** in the `--set-secrets` flag of the relevant service(s)
4. **Read it in code** via `os.environ["SECRET_NAME"]`
5. **Push** — build redeploys with the new env var injected

Example — adding `MSG91_AUTH_KEY`:
```bash
# Step 1+2: create and grant
gcloud secrets create MSG91_AUTH_KEY --project=supersahayak --replication-policy=automatic
echo -n "your_msg91_key" | gcloud secrets versions add MSG91_AUTH_KEY --project=supersahayak --data-file=-
gcloud secrets add-iam-policy-binding MSG91_AUTH_KEY \
  --project=supersahayak \
  --member="serviceAccount:supersahayak-run-sa@supersahayak.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

```yaml
# Step 3: in cloudbuild.yaml deploy-api step
--set-secrets DATABASE_URL=DATABASE_URL:latest,MSG91_AUTH_KEY=MSG91_AUTH_KEY:latest,...
```
