#!/usr/bin/env bash
# GCP one-time setup script for EventTrace
# Run locally: bash gcloud-setup.sh
# Prerequisites: gcloud CLI installed + authenticated (gcloud auth login)
#
# Fill in the variables below before running.

set -euo pipefail

# ── EDIT THESE ────────────────────────────────────────────────────────────────
PROJECT_ID="supersahayak"
REGION="asia-south1"                      # Mumbai — closest to India
SQL_INSTANCE="eventtrace-pg"
SQL_DB="eventtrace"
SQL_USER="eventtrace"
SQL_PASSWORD="changeme-use-a-real-secret" # also store this in Secret Manager below
FIREBASE_PROJECT_ID="${PROJECT_ID}"       # usually same as GCP project ID
# ─────────────────────────────────────────────────────────────────────────────

echo "==> Setting active project: ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

# ── Enable required APIs ──────────────────────────────────────────────────────
echo "==> Enabling APIs…"
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  compute.googleapis.com

# ── Artifact Registry ─────────────────────────────────────────────────────────
echo "==> Creating Artifact Registry repo…"
gcloud artifacts repositories create eventtrace \
  --repository-format docker \
  --location "${REGION}" \
  --description "EventTrace container images" \
  || echo "(already exists, skipping)"

# ── Cloud SQL PostgreSQL 16 ───────────────────────────────────────────────────
echo "==> Creating Cloud SQL instance (takes ~5 min)…"
gcloud sql instances create "${SQL_INSTANCE}" \
  --database-version POSTGRES_16 \
  --edition ENTERPRISE \
  --tier db-f1-micro \
  --region "${REGION}" \
  --storage-type SSD \
  --storage-size 10GB \
  --no-backup \
  || echo "(already exists, skipping)"

echo "==> Creating database and user…"
gcloud sql databases create "${SQL_DB}" --instance "${SQL_INSTANCE}" || echo "(already exists)"
gcloud sql users create "${SQL_USER}" \
  --instance "${SQL_INSTANCE}" \
  --password "${SQL_PASSWORD}" \
  || echo "(already exists)"

# Cloud Run connects via Unix socket: /cloudsql/PROJECT:REGION:INSTANCE
# psycopg2 treats host starting with / as a Unix socket directory.
DATABASE_URL="postgresql://${SQL_USER}:${SQL_PASSWORD}@/${SQL_DB}?host=/cloudsql/${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

# ── Service Accounts ──────────────────────────────────────────────────────────
echo "==> Creating service accounts…"

# Deploy SA: used by GitHub Actions to push images + deploy Cloud Run
gcloud iam service-accounts create eventtrace-deploy \
  --display-name "EventTrace CI/CD deploy" \
  || echo "(already exists)"

# Runtime SA: used by Cloud Run services at runtime
gcloud iam service-accounts create eventtrace-runtime \
  --display-name "EventTrace Cloud Run runtime" \
  || echo "(already exists)"

DEPLOY_SA="eventtrace-deploy@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA="eventtrace-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

# ── IAM bindings ─────────────────────────────────────────────────────────────
echo "==> Granting IAM roles…"

# Deploy SA roles (GitHub Actions)
for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/secretmanager.viewer \
  roles/iam.serviceAccountUser \
  roles/cloudsql.client; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${DEPLOY_SA}" \
    --role "${ROLE}" --quiet
done

# Runtime SA roles (Cloud Run services)
for ROLE in \
  roles/secretmanager.secretAccessor \
  roles/cloudsql.client; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${RUNTIME_SA}" \
    --role "${ROLE}" --quiet
done

# Allow deploy SA to act as runtime SA (needed for --service-account flag)
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member "serviceAccount:${DEPLOY_SA}" \
  --role roles/iam.serviceAccountUser --quiet

# ── Secret Manager ────────────────────────────────────────────────────────────
echo "==> Creating secrets in Secret Manager…"
echo "    (edit values before storing — or update via GCP console)"

create_secret() {
  local NAME=$1
  local VALUE=$2
  if gcloud secrets describe "${NAME}" &>/dev/null; then
    echo "    ${NAME}: adding new version"
    echo -n "${VALUE}" | gcloud secrets versions add "${NAME}" --data-file=-
  else
    echo "    ${NAME}: creating"
    echo -n "${VALUE}" | gcloud secrets create "${NAME}" --data-file=- --replication-policy automatic
  fi
}

create_secret "DATABASE_URL"        "${DATABASE_URL}"
create_secret "JWT_SECRET"          "REPLACE_WITH_$(openssl rand -hex 32)"
create_secret "OTP_HMAC_SECRET"     "REPLACE_WITH_$(openssl rand -hex 32)"
create_secret "MSG91_AUTH_KEY"      "REPLACE_WITH_MSG91_AUTH_KEY"
create_secret "MSG91_TEMPLATE_ID"   "REPLACE_WITH_MSG91_TEMPLATE_ID"

# ── Output GitHub Secrets needed ─────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Add these as GitHub repository secrets:"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  GCP_PROJECT_ID     = ${PROJECT_ID}"
echo "  GCP_RUN_SA_EMAIL   = ${RUNTIME_SA}"
echo ""
echo "  GCP_SA_KEY         = (paste JSON key — generate below):"
echo "    gcloud iam service-accounts keys create /tmp/deploy-key.json \\"
echo "      --iam-account ${DEPLOY_SA}"
echo "    cat /tmp/deploy-key.json   # paste this as GCP_SA_KEY"
echo "    rm /tmp/deploy-key.json    # delete after copying"
echo ""
echo "  VITE_API_URL       = (Cloud Run API service URL — set after first deploy)"
echo "  WEB_REPO           = your-github-org/EventTrace-Web"
echo "  FIREBASE_SERVICE_ACCOUNT = (see Firebase console → Project settings → Service accounts)"
echo ""
echo "  Cloud SQL instance connection name (for --add-cloudsql-instances):"
echo "    ${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Firebase: run these once locally after gcloud setup:"
echo "    npm install -g firebase-tools"
echo "    firebase login"
echo "    cd /path/to/EventTrace-Web"
echo "    firebase init hosting   # select existing project: ${FIREBASE_PROJECT_ID}"
echo "    # choose dist/ as public dir, yes to SPA rewrite"
echo "════════════════════════════════════════════════════════════════"
