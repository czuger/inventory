#!/usr/bin/env bash
# Shared settings for the deploy scripts, sourced by all of them (never run alone).
#
# Every value can be overridden from the environment without editing this file:
#   SSH_HOST=ced@other-box make deploy
#
# This file is versioned on purpose: it describes *where* the app goes, which is
# not a secret. Actual secrets live only in $REMOTE_DIR/config/ on the server
# (config.json and secret_key.txt), which no deploy step reads or writes.

# Which instance every script acts on: `production` (the default, and what all the
# commands did before staging existed) or `staging`, a second, fully separate copy
# of the app on the same server:
#   make deploy ENV=staging        ./deploy/deploy.sh --env staging
#
# Staging is production with APP_NAME suffixed `_staging`, and every per-instance
# name below derives from APP_NAME: its own directory next to production's (so its
# own config/, database and uploads), its own image, container, nginx snippet and
# URL prefix. Nothing is shared but the server, docker and the nginx proxy — a
# staging deploy, rollback or prune never sees a production file or image.
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
REMOTE_DIR="${REMOTE_DIR:-/home/ced/python/$APP_NAME}"

# What runs there. IMAGE_NAME is also the local build tag, the version is appended.
# Each instance needs its own: prune removes every tag of IMAGE_NAME that is not
# its own current/previous, so a shared image name would let one instance delete
# the other's rollback target.
CONTAINER_NAME="${CONTAINER_NAME:-app-$APP_NAME}"
IMAGE_NAME="${IMAGE_NAME:-$APP_NAME}"

# The port gunicorn listens on INSIDE the container. It is never published to the
# host — the app is reached over the docker network below, as
# http://$CONTAINER_NAME:$APP_PORT. Changing this means changing the gunicorn
# --bind and the HEALTHCHECK in the Dockerfile too.
APP_PORT="${APP_PORT:-8000}"

# The shared docker network nginx sits on. It belongs to nginx, not to us: the
# scripts only join it and refuse to run if it is missing (creating one nginx is
# not attached to would look fine and 502 at request time).
DOCKER_NETWORK="${DOCKER_NETWORK:-nginx-common-network}"

# MongoDB's network, joined in addition to the one above. The app now runs on
# SQLite and never talks to Mongo; this only keeps `make rollback` working towards
# a release from before that move, which still reads Mongo through it. Set it to
# '' once no such release is left on the server (KEEP_RELEASES deploys later).
#
# Leave empty too if Mongo runs on the HOST instead; the container is always
# started with --add-host=host.docker.internal:host-gateway for that case.
#
# Staging never had a MongoDB release, so it never joins. `-` rather than `:-` so
# that MONGO_NETWORK='' from the environment means "none" instead of the default.
if [ "$DEPLOY_ENV" = production ]; then
  MONGO_NETWORK="${MONGO_NETWORK-mongo-network}"
else
  MONGO_NETWORK="${MONGO_NETWORK-}"
fi

# The dockerized nginx: its container, and the directory its config includes from.
# `make setup` / `make nginx` render the snippet below into that directory and
# restart the container; a deploy never touches either.
NGINX_CONTAINER="${NGINX_CONTAINER:-nginx-proxy}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/home/ced/services/nginx_proxy/sites/apps}"
NGINX_CONF_NAME="${NGINX_CONF_NAME:-$APP_NAME.conf}"

# Sub-path the site is served under, i.e. https://<host>$URL_PREFIX — /inventory
# for production, /inventory_staging for staging. Neither location swallows the
# other: nginx's `location /inventory/` needs the slash right after the name.
#
# Unlike the app's other settings this one is NOT server-owned: it renders the
# nginx snippet AND is passed to the container as the URL_PREFIX env var by
# remote.sh, so the proxy's path and the app's generated links come from this one
# line and cannot drift apart. Set it to "/" to serve at the site root.
URL_PREFIX="${URL_PREFIX:-/$APP_NAME}"

# Architecture of the SERVER, not of your laptop. Building on an Apple Silicon Mac
# defaults to linux/arm64, which the x86_64 server can only run (badly) under
# emulation — hence pinning it here. deploy.sh checks the built image matches.
# On an ARM server (a Pi, an ARM VPS): TARGET_PLATFORM=linux/arm64 make deploy
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"

# How many releases (.tar + loaded image) stay on the server. 3 means "current,
# previous, and one more" — rollback only ever needs the previous one.
KEEP_RELEASES="${KEEP_RELEASES:-3}"

# Everything below is derived; no need to touch it.
# Appended to the `make` commands the scripts suggest, so a hint printed during a
# staging run never points at production.
MAKE_ENV=""
[ "$DEPLOY_ENV" = production ] || MAKE_ENV=" ENV=$DEPLOY_ENV"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_SCRIPT="$REMOTE_DIR/remote.sh"

# The server side of every script lives in deploy/remote.sh and is uploaded before
# each run, so deploy and rollback can never drift apart on `docker run` options.
upload_remote_script() {
  scp -q "$REPO_ROOT/deploy/remote.sh" "$SSH_HOST:$REMOTE_SCRIPT"
  ssh "$SSH_HOST" "chmod +x '$REMOTE_SCRIPT'"
}

# Render the nginx snippet from deploy/nginx/, ship it, and have the server
# validate it before restarting nginx. Used by setup_server.sh and `make nginx`;
# no deploy ever calls it — routing does not change between versions.
install_nginx_conf() {
  local template="$REPO_ROOT/deploy/nginx/$NGINX_CONF_NAME.template"
  local rendered="$REPO_ROOT/dist/$NGINX_CONF_NAME"

  [ -f "$template" ] || { echo "error: $template not found" >&2; return 1; }

  mkdir -p "$REPO_ROOT/dist"
  # nginx variable names take [A-Za-z0-9_] only, so the container name cannot be
  # used as-is (app-inventory -> app_inventory).
  local container_var="${CONTAINER_NAME//[^a-zA-Z0-9]/_}"
  # Trailing slash trimmed so "/inventory/" and "/inventory" both render the same
  # block; a bare "/" trims to "", which is exactly what the root case needs.
  sed -e "s|__PREFIX__|${URL_PREFIX%/}|g" \
      -e "s|__CONTAINER_VAR__|$container_var|g" \
      -e "s|__CONTAINER__|$CONTAINER_NAME|g" \
      -e "s|__APP_PORT__|$APP_PORT|g" \
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
    "REMOTE_DIR='$REMOTE_DIR' CONTAINER_NAME='$CONTAINER_NAME' IMAGE_NAME='$IMAGE_NAME' \
     APP_PORT='$APP_PORT' DOCKER_NETWORK='$DOCKER_NETWORK' MONGO_NETWORK='$MONGO_NETWORK' \
     URL_PREFIX='$URL_PREFIX' KEEP_RELEASES='$KEEP_RELEASES' \
     NGINX_CONTAINER='$NGINX_CONTAINER' NGINX_CONF_DIR='$NGINX_CONF_DIR' \
     NGINX_CONF_NAME='$NGINX_CONF_NAME' \
     bash '$REMOTE_SCRIPT' $*"
}
