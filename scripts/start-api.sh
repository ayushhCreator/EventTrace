#!/bin/sh
set -e
echo "==> Backfilling last 7 days of causelist data…"
chd-backfill --days 7 || echo "Backfill failed (non-fatal), continuing…"
echo "==> Starting API…"
exec chd-api
