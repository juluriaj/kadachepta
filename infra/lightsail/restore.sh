#!/usr/bin/env bash
# Replace the server's database with a pg_dump file: the cutover from the desktop, or a restore drill.
# A safety dump of the current database is taken first.
#
#   bash infra/lightsail/restore.sh data/backups/<file>.dump --yes
set -euo pipefail
source "$(dirname "$0")/lib.sh"

dump="${1:-}"
case "$dump" in
  data/backups/*.dump) ;;
  *) echo "Usage: bash infra/lightsail/restore.sh data/backups/<file>.dump --yes  (the file must be in data/backups/)" >&2
     exit 2 ;;
esac
[ -f "$dump" ] || { echo "Not found: $dump" >&2; exit 2; }
[ "${2:-}" = "--yes" ] || { echo "This replaces the whole database with $dump. Re-run with --yes to continue." >&2; exit 2; }
[ -f data/release ] || { echo "Deploy first (bash infra/lightsail/deploy.sh), then restore." >&2; exit 1; }
name="$(basename "$dump")"
psql() { compose exec -T backup psql -h postgres -U kathachepta -v ON_ERROR_STOP=1 "$@"; }

echo "== Stopping the API and workers"
compose up -d --wait postgres backup
compose stop api worker-media

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
echo "== Safety dump of the current database"
compose exec -T backup pg_dump -h postgres -U kathachepta -d kathachepta -Fc \
  -f "/backups/kathachepta-before-restore-$stamp.dump" || echo "(nothing to save: no current database)"

echo "== Restoring $name"
psql -d postgres -c "DROP DATABASE IF EXISTS kathachepta WITH (FORCE)" -c "CREATE DATABASE kathachepta"
compose exec -T backup pg_restore -h postgres -U kathachepta -d kathachepta --no-owner --exit-on-error "/backups/$name"
psql -d kathachepta -Atc "select 'users: ' || count(*) from users" \
  -c "select 'stories: ' || count(*) from audio_assets" -c "select 'jobs waiting: ' || count(*) from jobs where status = 'queued'"

echo "== Starting the API (it applies any newer migrations) and workers"
compose up -d api worker-media
if ! wait_for_api "$KC_RELEASE"; then
  show_failure "$KC_RELEASE"
  echo "The database before the restore is in data/backups/kathachepta-before-restore-$stamp.dump" >&2
  exit 1
fi
echo "== Restored $name; API up on build $KC_RELEASE"
