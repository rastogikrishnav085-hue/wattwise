#!/usr/bin/env bash
# backup_db.sh — nightly backup of wattwise.db to a separate location.
#
# Run via cron (e.g. `0 2 * * * /app/scripts/backup_db.sh`) or as a
# scheduled task in whatever orchestrator runs the docker-compose stack.
# This was a real gap in the previous version: forecast_runs and
# training_runs were the only record of every run ever made, with
# nothing copying that file anywhere else.
#
# Uses SQLite's own backup command (not a raw file copy) so a backup
# taken mid-write doesn't produce a corrupted copy.

set -e

DB_PATH="${WATTWISE_DB_PATH:-/app/data/wattwise.db}"
BACKUP_DIR="${WATTWISE_BACKUP_DIR:-/app/backups}"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
BACKUP_FILE="${BACKUP_DIR}/wattwise_${TIMESTAMP}.db"
RETENTION_DAYS="${WATTWISE_BACKUP_RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
    echo "[ERROR] No database found at $DB_PATH — nothing to back up."
    exit 1
fi

sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
echo "[OK] Backed up $DB_PATH -> $BACKUP_FILE"

# Prune backups older than retention window
find "$BACKUP_DIR" -name "wattwise_*.db" -mtime "+${RETENTION_DAYS}" -delete
echo "[OK] Pruned backups older than ${RETENTION_DAYS} days."

# NOTE: this backs up locally, which protects against DB corruption but
# not against the whole host being lost. For real production use, add a
# step here to copy $BACKUP_FILE to off-host storage (S3-compatible
# bucket, etc.) — left out here since bucket/credentials are
# deployment-specific and shouldn't be guessed at.
