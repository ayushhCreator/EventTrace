#!/bin/sh
set -e
echo "==> Starting causelist scheduler…"
exec chd-schedule-causelist
