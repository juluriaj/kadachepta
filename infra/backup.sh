#!/bin/sh
# Nightly PostgreSQL dump with rotation. Runs inside the "backup" compose service.
set -eu
KEEP_DAYS="${KEEP_DAYS:-14}"

backup() {
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  target="/backups/kathachepta-$stamp.dump"
  if pg_dump -h postgres -U kathachepta -d kathachepta -Fc -f "$target.partial"; then
    mv "$target.partial" "$target"
    echo "$(date -u) backup ok: $target ($(du -h "$target" | cut -f1))"
  else
    rm -f "$target.partial"
    echo "$(date -u) BACKUP FAILED" >&2
  fi
  find /backups -name 'kathachepta-*.dump' -mtime +"$KEEP_DAYS" -delete
}

backup
while true; do
  # Sleep until 02:30 UTC (08:00 IST).
  now=$(date -u +%s)
  next=$(date -u -d "$(date -u +%Y-%m-%d) 02:30" +%s 2>/dev/null || echo $((now + 86400)))
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  backup
done
