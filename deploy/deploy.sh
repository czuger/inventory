#!/usr/bin/env bash
# Build here, ship the binary over SSH, restart there.
# Run it with: make deploy
#
# Steps: cross-compile (version = UTC timestamp) -> scp -> migrate with the new
# binary -> version bookkeeping -> restart the unit -> health check -> prune old ones.
#
# Nothing under $REMOTE_DIR/config is read or written here: server config
# (config.json, secret_key.txt) is not ours to touch, the app only reads it.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/config.sh" "$@"

# UTC so two machines deploying the same day still sort chronologically.
VERSION="$(date -u +%Y%m%d-%H%M%S)"
BINARY="$REPO_ROOT/target/$TARGET/release/inventory"

echo "==> Deploying $APP_NAME $VERSION ($DEPLOY_ENV) to $SSH_HOST:$REMOTE_DIR"

# 1. Cross-compile for the SERVER: zig provides the linker and the musl libc, so a
#    Mac builds a static Linux binary without any VM. Queries compile against the
#    committed .sqlx/ data: no database at build time.
if ! cargo zigbuild --help >/dev/null 2>&1; then
  echo "error: cargo-zigbuild is needed to build for $TARGET. Install it once with:" >&2
  echo "       brew install zig && cargo install cargo-zigbuild && rustup target add $TARGET" >&2
  exit 1
fi
echo "==> Building for $TARGET"
SQLX_OFFLINE=true cargo zigbuild --release --locked --target "$TARGET" --manifest-path "$REPO_ROOT/Cargo.toml"

# Confirm what actually came out before shipping it.
expected_arch="${TARGET%%-*}"
case "$expected_arch" in x86_64) expected_arch="x86-64" ;; aarch64) expected_arch="aarch64" ;; esac
file "$BINARY" | grep -q "ELF.*$expected_arch" \
  || { echo "error: $BINARY is not a $expected_arch Linux binary:" >&2; file "$BINARY" >&2; exit 1; }
du -h "$BINARY" | cut -f1 | xargs echo "    binary size:"

# 2. Ship it. remote.sh goes first so the server side always matches this checkout.
echo "==> Uploading"
upload_remote_script
ssh "$SSH_HOST" "mkdir -p '$REMOTE_DIR/releases/$VERSION'"
scp -C "$BINARY" "$SSH_HOST:$REMOTE_DIR/releases/$VERSION/inventory"

# 3. Migrate, record the version swap, restart, wait for /health. Any failure here
#    stops the script (set -e) with the old version still recorded as previous,
#    so `make rollback` is the immediate way out.
echo "==> Activating $VERSION on the server"
if ! remote activate "$VERSION"; then
  echo >&2
  echo "error: $VERSION did not come up. Roll back with: make rollback$MAKE_ENV" >&2
  exit 1
fi

# 4. Housekeeping — only after a healthy start, so a failed deploy never deletes
#    the release we might need to go back to.
echo "==> Pruning old releases (keeping $KEEP_RELEASES)"
remote prune

echo
echo "Deployed $APP_NAME $VERSION"
remote versions
