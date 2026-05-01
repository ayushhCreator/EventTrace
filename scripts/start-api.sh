#!/bin/sh
set -e
echo "==> Starting backfill in background…"
(chd-backfill --days 7 || echo "Backfill failed (non-fatal)") &
echo "==> Starting API…"
exec chd-api
