#!/usr/bin/env bash
# ONE-TIME server preparation. Run from your laptop: make setup
#
# Creates the directory layout, checks systemd can run the app as this SSH user and
# that the nginx container sees the socket directory, installs the nginx snippet, and tells you which config files you still have to
# copy by hand. It never touches config/ if it already exists — that is the whole
# point of the code/config split.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/config.sh" "$@"

echo "==> Target ($DEPLOY_ENV): $SSH_HOST:$REMOTE_DIR"

# nginx runs in a container: every nginx and socket check goes through docker.
ssh "$SSH_HOST" 'docker info >/dev/null 2>&1' || {
  echo "error: 'docker info' fails on $SSH_HOST — the SSH user must be in the docker group." >&2
  exit 1
}

# 1. Directory layout: releases/ (binaries), config/ (secrets, ours to never touch),
#    data/uploads/ (the item photos) and data/db/ (the SQLite database) — the only
#    two things the app writes. Also checks the systemd user manager, lingering, and
#    that the nginx container mounts the socket directory.
echo "==> Creating $REMOTE_DIR/{releases,config,data/uploads,data/db}"
ssh "$SSH_HOST" "mkdir -p '$REMOTE_DIR'"
upload_remote_script
remote init

# 2. The nginx snippet: rendered from deploy/nginx/, dropped in nginx's config
#    directory, validated there, and only then does nginx reload. Setup-only —
#    routing does not change from one deploy to the next.
echo "==> Installing the nginx config ($NGINX_CONF_NAME -> $NGINX_CONF_DIR)"
install_nginx_conf

# 3. What is still missing before the first deploy.
echo "==> Checking server config"
missing=0
for file in config.json secret_key.txt; do
  if ssh "$SSH_HOST" "test -f '$REMOTE_DIR/config/$file'"; then
    echo "    ok      config/$file"
  else
    echo "    MISSING config/$file"
    missing=1
  fi
done

cat <<EOF2

Layout ready on $SSH_HOST:$REMOTE_DIR
  releases/     deployed binaries (last $KEEP_RELEASES kept); current -> the running one
  config/       config.json + secret_key.txt — server-owned, no deploy writes here
  data/uploads/ the item photos
  data/db/      the SQLite database (+ backups/ taken before each migration) —
                every deploy migrates it before starting
  app.env       the app's environment, written by each deploy (do not edit)
  run           runs the current binary with that environment

The app runs as the systemd user unit '$SERVICE_NAME' and opens no port: it
listens on $SOCKET_DIR/$SOCKET_NAME, which $NGINX_CONTAINER
sees as $NGINX_SOCKET_DIR/$SOCKET_NAME and serves under ${URL_PREFIX%/}/.

Unlike the config files, the URL prefix is NOT server-owned: URL_PREFIX in
deploy/config.sh renders the nginx snippet and is handed to the app, so the two
always agree.

EOF2

if [ "$missing" -eq 1 ]; then
  cat <<EOF2
Still to do, once, by hand:

  scp config.json    $SSH_HOST:$REMOTE_DIR/config/config.json
  scp secret_key.txt $SSH_HOST:$REMOTE_DIR/config/secret_key.txt

If you have no secret_key.txt yet, generate one first — without it the app picks a
random key per process, so nobody stays logged in:
  openssl rand -hex 32 > secret_key.txt

In that server-side config.json, remember to:
  - set discord.client_id / client_secret, and add the redirect URI
      https://<your-host>${URL_PREFIX%/}/auth/discord/callback
    to the Discord application — OAuth rejects any callback not listed there.

EOF2
fi

cat <<EOF2
After the first deploy, grant yourself admin once you have logged in (through
Discord, or after signing up on the login page):
  ssh $SSH_HOST "$REMOTE_DIR/run set-admin <username>"

A Discord member can also get a password (prompted, so -t):
  ssh -t $SSH_HOST "$REMOTE_DIR/run set-password <username>"

EOF2

echo "Next: make deploy$MAKE_ENV — then the site answers at https://<your-host>${URL_PREFIX%/}"
