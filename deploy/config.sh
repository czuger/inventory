#!/usr/bin/env bash
# Shared settings for the deploy scripts, sourced by all of them (never run alone).
#
# Every value can be overridden from the environment without editing this file:
#   SSH_HOST=ced@other-box make deploy
#
# This file is versioned on purpose: it describes *where* the app goes, which is
# not a secret. Actual secrets live only in $REMOTE_DIR/config/ on the server
# (config.json and secret_key.txt), which no deploy step reads or writes.

# Which instance every script acts on: `production` (the default) or `staging`, a
# second, fully separate copy of the app on the same server:
#   make deploy ENV=staging        ./deploy/deploy.sh --env staging
#
# Staging is production with APP_NAME suffixed `_staging`, and every per-instance
# name below derives from APP_NAME: its own directory next to production's (so its
# own config/, database and uploads), its own systemd unit, socket, nginx snippet and
# URL prefix. Nothing is shared but the server and the nginx proxy — a staging
# deploy, rollback or prune never sees a production file.
DEPLOY_ENV="${DEPLOY_ENV:-production}"

# Scripts source this file with their own arguments; --env is the only one.
while [ $# -gt 0 ]; do
  case "$1" in
    --env)   DEPLOY_ENV="${2:?--env needs production or staging}"; shift 2 ;;
    --env=*) DEPLOY_ENV="${1#--env=}"; shift ;;
    *)       echo "error: unknown argument '$1' (only --env production|staging)" >&2; exit 1 ;;
  esac
done

case "$DEPLOY_ENV" in
  production) APP_NAME="inventory" ;;
  staging)    APP_NAME="inventory_staging" ;;
  *)          echo "error: unknown environment '$DEPLOY_ENV' (production or staging)" >&2; exit 1 ;;
esac

# Where to deploy.
SSH_HOST="${SSH_HOST:-ced@nuc150}"
REMOTE_DIR="${REMOTE_DIR:-/home/ced/rust/$APP_NAME}"

# The systemd *user* unit running the app (~/.config/systemd/user/$SERVICE_NAME.service
# on the server): a user unit, so deploys need no sudo.
SERVICE_NAME="${SERVICE_NAME:-$APP_NAME}"

# The app opens no port: nginx runs in a container (nginx_proxy's `nginx-proxy`), so
# the app listens on a Unix socket in a host directory that container bind-mounts.
# That directory belongs to the nginx_proxy project (wiki_to_text uses it too) — we
# only put our socket in it, and refuse to start if nginx does not see it there (a
# socket nginx cannot reach would look fine here and 502 at request time).
#   SOCKET_DIR        the directory, as seen on the host (remote.sh hands the app
#                     SOCKET_PATH=$SOCKET_DIR/$SOCKET_NAME)
#   NGINX_SOCKET_DIR  the same directory, as seen inside the nginx container (the
#                     nginx snippet proxies to $NGINX_SOCKET_DIR/$SOCKET_NAME)
SOCKET_DIR="${SOCKET_DIR:-/home/ced/services/nginx_proxy/sockets}"
NGINX_SOCKET_DIR="${NGINX_SOCKET_DIR:-/sockets}"
SOCKET_NAME="${SOCKET_NAME:-$APP_NAME.sock}"

# The SERVER's target, not your laptop's: the binary is cross-compiled with
# cargo-zigbuild. musl makes it static, so it runs whatever the server's glibc is.
# On an ARM server (a Pi, an ARM VPS): TARGET=aarch64-unknown-linux-musl make deploy
TARGET="${TARGET:-x86_64-unknown-linux-musl}"

# The dockerized nginx: its container, and the host directory its config includes
# from (sites/apps.conf includes /etc/nginx/sites/apps/*.conf inside its server{}).
# `make setup` / `make nginx` render the snippet below into that directory and have
# the container validate and reload it; a deploy never touches nginx.
NGINX_CONTAINER="${NGINX_CONTAINER:-nginx-proxy}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/home/ced/services/nginx_proxy/sites/apps}"
NGINX_CONF_NAME="${NGINX_CONF_NAME:-$APP_NAME.conf}"

# Sub-path the site is served under, i.e. https://<host>$URL_PREFIX — /inventory
# for production, /inventory_staging for staging. Neither location swallows the
# other: nginx's `location /inventory/` needs the slash right after the name.
#
# Unlike the app's other settings this one is NOT server-owned: it renders the
# nginx snippet AND is passed to the app as the URL_PREFIX env var by remote.sh,
# so the proxy's path and the app's generated links come from this one line and
# cannot drift apart. Set it to "/" to serve at the site root.
URL_PREFIX="${URL_PREFIX:-/$APP_NAME}"

# How many releases stay on the server. 3 means "current, previous, and one more"
# — rollback only ever needs the previous one.
KEEP_RELEASES="${KEEP_RELEASES:-3}"

# Everything below is derived; no need to touch it.
# Appended to the `make` commands the scripts suggest, so a hint printed during a
# staging run never points at production.
MAKE_ENV=""
[ "$DEPLOY_ENV" = production ] || MAKE_ENV=" ENV=$DEPLOY_ENV"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_SCRIPT="$REMOTE_DIR/remote.sh"

# The server side of every script lives in deploy/remote.sh and is uploaded before
# each run, so deploy and rollback can never drift apart on how the app is run.
upload_remote_script() {
  scp -q "$REPO_ROOT/deploy/remote.sh" "$SSH_HOST:$REMOTE_SCRIPT"
  ssh "$SSH_HOST" "chmod +x '$REMOTE_SCRIPT'"
}

# Render the nginx snippet from deploy/nginx/, ship it, and have the server
# validate it before reloading nginx. Used by setup_server.sh and `make nginx`;
# no deploy ever calls it — routing does not change between versions.
install_nginx_conf() {
  # One template for every instance: all that differs between them is in the
  # placeholders. Only the deployed file is named after the instance.
  local template="$REPO_ROOT/deploy/nginx/inventory.conf.template"
  [ -f "$template" ] || { echo "error: $template not found" >&2; return 1; }

  local rendered
  rendered="$(mktemp)"
  # Trailing slash trimmed so "/inventory/" and "/inventory" both render the same
  # block; a bare "/" trims to "", which is exactly what the root case needs.
  sed -e "s|__PREFIX__|${URL_PREFIX%/}|g" \
      -e "s|__SOCKET__|$NGINX_SOCKET_DIR/$SOCKET_NAME|g" \
      "$template" > "$rendered"

  ssh "$SSH_HOST" "mkdir -p '$NGINX_CONF_DIR'"
  scp -q "$rendered" "$SSH_HOST:$NGINX_CONF_DIR/$NGINX_CONF_NAME"
  rm -f "$rendered"

  upload_remote_script
  remote nginx_reload
}

# Runs remote.sh on the server with this file's settings passed through, so the
# server never keeps its own stale copy of them.
remote() {
  ssh "$SSH_HOST" \
    "REMOTE_DIR='$REMOTE_DIR' SERVICE_NAME='$SERVICE_NAME' \
     URL_PREFIX='$URL_PREFIX' KEEP_RELEASES='$KEEP_RELEASES' \
     SOCKET_DIR='$SOCKET_DIR' NGINX_SOCKET_DIR='$NGINX_SOCKET_DIR' SOCKET_NAME='$SOCKET_NAME' \
     NGINX_CONTAINER='$NGINX_CONTAINER' \
     NGINX_CONF_DIR='$NGINX_CONF_DIR' NGINX_CONF_NAME='$NGINX_CONF_NAME' \
     bash '$REMOTE_SCRIPT' $*"
}
