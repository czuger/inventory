#!/usr/bin/env bash
# Read-only looks at what runs on the server: make logs | status | versions
#
# Lives here rather than in the Makefile so it reads the same deploy/config.sh as
# every other script — including ENV=staging — instead of a second copy of the
# host, directory and container name.
#
# Usage: deploy/server.sh <logs | status | versions> [--env production|staging]
set -euo pipefail

command="${1:-}"
shift || true

source "$(dirname "${BASH_SOURCE[0]}")/config.sh" "$@"

case "$command" in
  logs)
    ssh -t "$SSH_HOST" "docker logs -f --tail 100 '$CONTAINER_NAME'"
    ;;
  status|versions)
    # The server's copy may predate this checkout (or not exist yet, before the
    # first deploy of this instance); status/versions only read, so refresh it.
    upload_remote_script
    remote "$command"
    ;;
  *)
    echo "usage: $0 <logs|status|versions> [--env production|staging]" >&2
    exit 1
    ;;
esac
