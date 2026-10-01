#!/usr/bin/env bash
# ONE-TIME server preparation. Run from your laptop: make setup
#
# Creates the directory layout, checks Docker is usable over SSH, and tells you
# which config files you still have to copy by hand. It never touches config/ if
# it already exists — that is the whole point of the code/config split.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/config.sh" "$@"

echo "==> Target ($DEPLOY_ENV): $SSH_HOST:$REMOTE_DIR"

# 1. Docker must be there, and usable by this SSH user without sudo.
echo "==> Checking Docker on the server"
if ! ssh "$SSH_HOST" 'command -v docker >/dev/null'; then
  echo "error: docker is not installed on $SSH_HOST" >&2
  exit 1
fi
if ! ssh "$SSH_HOST" 'docker info >/dev/null 2>&1'; then
  echo "error: 'docker info' fails on $SSH_HOST — add the SSH user to the docker group:" >&2
  echo "       sudo usermod -aG docker \$USER   (then log out and back in)" >&2
  exit 1
fi
ssh "$SSH_HOST" 'docker --version'

# 2. Directory layout: releases/ (tarballs), config/ (secrets, ours to never touch),
#    data/uploads/ (the item photos) and data/db/ (the SQLite database) — the only
#    two things the container writes.
echo "==> Creating $REMOTE_DIR/{releases,config,data/uploads,data/db}"
ssh "$SSH_HOST" "mkdir -p '$REMOTE_DIR'"
upload_remote_script
remote init

# 3. The nginx snippet: rendered from deploy/nginx/, dropped in the proxy's config
#    directory, validated there, and only then does nginx restart. Setup-only —
#    routing does not change from one deploy to the next.
echo "==> Installing the nginx config ($NGINX_CONF_NAME -> $NGINX_CONF_DIR)"
install_nginx_conf

# 4. What is still missing before the first deploy.
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
  releases/     deployed .tar images (last $KEEP_RELEASES kept)
  config/       config.json + secret_key.txt — server-owned, no deploy writes here
  data/uploads/ the item photos, mounted at /app/inventory/api/static/uploads
  data/db/      the SQLite database (+ backups/ taken before each migration),
                mounted at /app/data — every deploy migrates it before starting

The app publishes no port. It joins nginx's shared '$DOCKER_NETWORK' network and
answers there at http://$CONTAINER_NAME:$APP_PORT, which is what
$NGINX_CONF_DIR/$NGINX_CONF_NAME proxies ${URL_PREFIX%/}/ to.

Unlike the config files, the URL prefix is NOT server-owned: URL_PREFIX in
deploy/config.sh renders the nginx snippet and is handed to the container, so the
two always agree.

EOF2

if [ "$missing" -eq 1 ]; then
  cat <<EOF2
Still to do, once, by hand:

  scp config.json    $SSH_HOST:$REMOTE_DIR/config/config.json
  scp secret_key.txt $SSH_HOST:$REMOTE_DIR/config/secret_key.txt

If you have no secret_key.txt yet, generate one first — without it the app picks a
random key per worker, so nobody stays logged in:
  python3 -c "import secrets; print(secrets.token_hex(32))" > secret_key.txt

In that server-side config.json, remember to:
  - set discord.client_id / client_secret, and add the redirect URI
      https://<your-host>${URL_PREFIX%/}/auth/discord/callback
    to the Discord application — OAuth rejects any callback not listed there.

Then grant yourself admin, after logging in through Discord once:
  ssh $SSH_HOST "docker exec $CONTAINER_NAME python misc/set_admin.py <discord_username>"

EOF2
fi

echo "Next: make deploy$MAKE_ENV — then the site answers at https://<your-host>${URL_PREFIX%/}"
