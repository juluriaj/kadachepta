# shellcheck shell=bash
# Shared by the server scripts (compose.sh, deploy.sh, restore.sh). Sourcing it moves to the checkout root.
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1

export COMPOSE_PATH_SEPARATOR="${COMPOSE_PATH_SEPARATOR:-:}"
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml${COMPOSE_PATH_SEPARATOR}infra/lightsail/docker-compose.prod.yml}"
# Images are tagged with the deployed commit; deploy.sh records it in data/release.
export KC_RELEASE="${KC_RELEASE:-$(cat data/release 2>/dev/null || echo latest)}"

compose() { docker compose "$@"; }

# The build the running API reports, or nothing while it is down.
api_build() {
  local probe="import json, urllib.request as r; print(json.load(r.urlopen('http://127.0.0.1:8000/api/health', timeout=4))['build'])"
  compose exec -T api python -c "$probe" 2>/dev/null || true
}

# wait_for_api <release>: up to 3 minutes, because the first start after a deploy runs database migrations.
# A release whose container exits on start (a failing migration, say) keeps restarting: give up after 3 restarts.
wait_for_api() {
  local id
  for _ in $(seq 60); do
    [ "$(api_build)" = "$1" ] && return 0
    id="$(compose ps -a -q api 2>/dev/null)"
    [ -n "$id" ] && [ "$(docker inspect -f '{{.RestartCount}}' "$id" 2>/dev/null || echo 0)" -ge 3 ] && return 1
    sleep 3
  done
  return 1
}

show_failure() {
  echo "!! The API did not report build $1. Containers and the last API log lines:" >&2
  compose ps -a >&2 || true
  compose logs --no-color --tail 60 api >&2 || true
  compose logs --no-color --tail 500 api 2>/dev/null | grep -o -E "Configuration problem: .*" | sort -u | sed 's/^/!! /' >&2 || true
}
