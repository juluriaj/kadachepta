#!/usr/bin/env bash
# docker compose on the server, with the production files and the deployed release. Examples:
#   bash infra/lightsail/compose.sh ps
#   bash infra/lightsail/compose.sh logs -f --tail 100 api worker-media
#   bash infra/lightsail/compose.sh exec api python -m app.cli create-user ...
set -euo pipefail
source "$(dirname "$0")/lib.sh"
compose "$@"
