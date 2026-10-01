#!/usr/bin/env bash
# Go back to the previously deployed version, in one command: make rollback
#
# Purely server-side: the previous image is already loaded there, so this builds
# and transfers nothing. The two version files trade places, which means running
# it twice returns you to where you started.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/config.sh" "$@"

echo "==> Rolling back $DEPLOY_ENV on $SSH_HOST:$REMOTE_DIR"
remote versions
echo

# Uploaded every time so deploy and rollback share the same `docker run` options.
upload_remote_script

if ! remote rollback; then
  echo >&2
  echo "error: rollback failed — check 'make status$MAKE_ENV' and 'make logs$MAKE_ENV'" >&2
  exit 1
fi

echo
remote versions
