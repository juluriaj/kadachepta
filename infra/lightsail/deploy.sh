#!/usr/bin/env bash
# Deploy a git ref on the Lightsail VM: build, back up the database, restart, and roll back automatically if
# the API doesn't come up on the new build. Runs on the server (the desktop runs it via scripts/lightsail.ps1).
#
#   bash infra/lightsail/deploy.sh               # latest origin/main
#   bash infra/lightsail/deploy.sh <branch|tag|commit>
set -euo pipefail
source "$(dirname "$0")/lib.sh"

# Everything runs from main() so checking out another commit can't change this script mid-run.
main() {
  local ref="${1:-origin/main}" previous release
  [ -f .env ] || { echo "Missing .env. Create it first: python3 scripts/setup_local.py --server app.kathachepta.com" >&2; exit 1; }
  previous="$(cat data/release 2>/dev/null || true)"

  git fetch --quiet --prune origin
  if ! git checkout --quiet --detach "$ref"; then
    echo "!! Can't check out $ref. Local edits on the server? See: git status" >&2
    exit 1
  fi
  release="$(git rev-parse --short=10 HEAD)"
  export KC_RELEASE="$release"
  echo "== Deploying $release ($(git log -1 --format=%s)); running now: ${previous:-nothing}"

  sudo install -d -o 10001 -g 10001 data/media   # the API container's user writes uploads here
  mkdir -p data/backups audio

  echo "== Building images"
  compose build --pull api worker-media

  if [ -n "$previous" ] && [ -n "$(compose ps -q postgres 2>/dev/null)" ]; then
    echo "== Database backup before the restart"
    compose exec -T backup pg_dump -h postgres -U kathachepta -d kathachepta -Fc \
      -f "/backups/kathachepta-predeploy-$(date -u +%Y%m%dT%H%M%SZ)-$release.dump"
  fi

  echo "== Starting $release"
  compose up -d --remove-orphans
  if ! wait_for_api "$release"; then
    show_failure "$release"
    if [ -n "$previous" ] && [ "$previous" != "$release" ]; then
      echo "== Rolling back to $previous" >&2
      git checkout --quiet --detach "$previous"
      export KC_RELEASE="$previous"
      compose up -d --remove-orphans
      wait_for_api "$previous" && echo "Rolled back to $previous. Database migrations from $release are not undone;" \
        "the pre-deploy dump is in data/backups (restore with infra/lightsail/restore.sh)." >&2
    fi
    exit 1
  fi
  echo "$release" > data/release

  # Keep this release and the one before it for rollbacks; drop older images and build cache.
  for image in kathachepta/api kathachepta/worker; do
    docker image ls "$image" --format '{{.Tag}}' | grep -v -x -e "$release" -e "${previous:-none}" \
      | xargs -r -I{} docker image rm "$image:{}" >/dev/null || true
  done
  docker builder prune -f --filter until=168h >/dev/null || true

  compose ps
  compose logs --no-color --since 5m api 2>/dev/null | grep -o -E "Configuration (problem|warning): .*" | sort -u || true
  local url
  url="$(grep -E '^KC_PUBLIC_BASE_URL=' .env | cut -d= -f2-)"
  if curl -fsS --max-time 10 "$url/api/health" >/dev/null 2>&1; then
    echo "== Live: $url (build $release)"
  else
    echo "== Running build $release, but $url/api/health isn't reachable from here yet (DNS or certificate pending?)."
    echo "   Caddy's certificate log: bash infra/lightsail/compose.sh logs --tail 50 caddy"
  fi
}

main "$@"
