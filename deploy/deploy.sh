#!/usr/bin/env bash
# Build here, ship the image over SSH, restart there. No registry involved.
# Run it with: make deploy
#
# Steps: build (tag = UTC timestamp) -> docker save -> scp -> docker load ->
# version bookkeeping -> restart the container -> health check -> prune old ones.
#
# Nothing under $REMOTE_DIR/config is read or written here: server config
# (config.json, secret_key.txt) is not ours to touch, it is only mounted into the
# container.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

# UTC so two machines deploying the same day still sort chronologically.
VERSION="$(date -u +%Y%m%d-%H%M%S)"
TARBALL="$REPO_ROOT/dist/$VERSION.tar"

# The tarball is a build artefact: gone whether we succeed or fail.
cleanup() { rm -f "$TARBALL"; }
trap cleanup EXIT

echo "==> Deploying $IMAGE_NAME:$VERSION to $SSH_HOST:$REMOTE_DIR"

# 1. Build for the SERVER's architecture, not the laptop's: an Apple Silicon Mac
#    builds linux/arm64 by default, and the x86_64 server would then refuse it
#    ("the requested image's platform does not match the detected host platform").
#    --pull so a stale local python:3.13-slim doesn't ship security fixes late.
echo "==> Building the image for $TARGET_PLATFORM"
docker build --pull --platform "$TARGET_PLATFORM" -t "$IMAGE_NAME:$VERSION" "$REPO_ROOT"

# Confirm what actually came out: a builder without the emulator installed can
# silently hand back the host architecture, and the mismatch would only show up
# on the server, after a multi-hundred-MB transfer.
expected_arch="$(echo "$TARGET_PLATFORM" | cut -d/ -f2)"
built_arch="$(docker image inspect --format '{{.Architecture}}' "$IMAGE_NAME:$VERSION")"
if [ "$built_arch" != "$expected_arch" ]; then
  echo "error: built a $built_arch image but the server needs $expected_arch." >&2
  echo "       Docker Desktop ships the emulator; elsewhere install it with:" >&2
  echo "       docker run --privileged --rm tonistiigi/binfmt --install $expected_arch" >&2
  exit 1
fi
echo "    architecture: $built_arch (ok)"

# 2. Freeze it into a file. Plain .tar (docker load reads it as-is); scp -C
#    compresses on the wire, which is where the size actually costs us.
echo "==> Saving the image to $TARBALL"
mkdir -p "$REPO_ROOT/dist"
docker save "$IMAGE_NAME:$VERSION" -o "$TARBALL"
du -h "$TARBALL" | cut -f1 | xargs echo "    image size:"

# 3. Ship it. remote.sh goes first so the server side always matches this checkout.
echo "==> Uploading"
upload_remote_script
ssh "$SSH_HOST" "mkdir -p '$REMOTE_DIR/releases'"
scp -C "$TARBALL" "$SSH_HOST:$REMOTE_DIR/releases/$VERSION.tar"

# 4. Load, record the version swap, restart, wait for /health. Any failure here
#    stops the script (set -e) with the old version still recorded as previous,
#    so `make rollback` is the immediate way out.
echo "==> Activating $VERSION on the server"
if ! remote activate "$VERSION"; then
  echo >&2
  echo "error: $VERSION did not come up. Roll back with: make rollback" >&2
  exit 1
fi

# 5. Housekeeping — only after a healthy start, so a failed deploy never deletes
#    the release we might need to go back to.
echo "==> Pruning old releases (keeping $KEEP_RELEASES)"
remote prune

echo
echo "Deployed $IMAGE_NAME:$VERSION"
remote versions
