#!/usr/bin/env bash
# THE SERVER SIDE of the deploy. Never run this from your laptop.
#
# deploy.sh and rollback.sh upload this file before every run and then call one of
# its subcommands over SSH. It exists so that the `docker run` line lives in exactly
# one place: a rollback must relaunch the app with the same mounts, networks and
# restart policy as a deploy, and duplicating those flags is how they drift.
#
# Usage: bash remote.sh <init | nginx_reload | activate VERSION | rollback
#                        | prune | status | health | versions>
set -euo pipefail

# Defaults mirror deploy/config.sh; the caller normally overrides them via env.
REMOTE_DIR="${REMOTE_DIR:-/home/ced/python/inventory}"
CONTAINER_NAME="${CONTAINER_NAME:-app-inventory}"
IMAGE_NAME="${IMAGE_NAME:-inventory}"
APP_PORT="${APP_PORT:-8000}"
DOCKER_NETWORK="${DOCKER_NETWORK:-nginx-common-network}"
MONGO_NETWORK="${MONGO_NETWORK:-mongo-network}"
URL_PREFIX="${URL_PREFIX:-/inventory}"
KEEP_RELEASES="${KEEP_RELEASES:-3}"
NGINX_CONTAINER="${NGINX_CONTAINER:-nginx-proxy}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/home/ced/services/nginx_proxy/sites/apps}"
NGINX_CONF_NAME="${NGINX_CONF_NAME:-inventory.conf}"

RELEASES_DIR="$REMOTE_DIR/releases"
CONFIG_DIR="$REMOTE_DIR/config"
DATA_DIR="$REMOTE_DIR/data"
UPLOADS_DIR="$DATA_DIR/uploads"
CURRENT_FILE="$REMOTE_DIR/current_version.txt"
PREVIOUS_FILE="$REMOTE_DIR/previous_version.txt"

# The uid the image's `appuser` runs as; the uploads directory must be writable
# by it.
APP_UID=10001

die() { echo "error: $*" >&2; exit 1; }

read_version() { [ -f "$1" ] && cat "$1" || true; }

# --- network ---------------------------------------------------------------

# The nginx network belongs to nginx and is shared by every app it fronts — we
# only join it. Deliberately NOT created here: a network we invented would exist,
# accept the container, and 502 every request because nginx is not on it.
check_network() {
  docker network inspect "$DOCKER_NETWORK" >/dev/null 2>&1 || die \
    "docker network '$DOCKER_NETWORK' does not exist — it is nginx's. Existing ones:
$(docker network ls --format '  {{.Name}}')"

  # Same reasoning for Mongo's network when one is configured: joining a network
  # mongod is not on would fail at the first query, not at start-up.
  if [ -n "$MONGO_NETWORK" ]; then
    docker network inspect "$MONGO_NETWORK" >/dev/null 2>&1 || die \
      "docker network '$MONGO_NETWORK' does not exist. Set MONGO_NETWORK='' in
       deploy/config.sh if MongoDB runs on the host instead."
  fi
}

# --- container -------------------------------------------------------------

# Start (or restart) the app on a given version. This is the single source of
# truth for how the container is run.
# Make the bind-mounted uploads/ writable by the image's non-root uid.
#
# Docker creates a missing host directory as root:root, and `make setup` can only
# chown it when passwordless sudo happens to be available — so the directory can
# end up unwritable while every deploy still looks perfectly healthy, and the
# failure only shows up as an EACCES the first time someone uploads a photo.
#
# No host privileges are needed to fix it: the docker daemon runs as root, so a
# throwaway container running as uid 0 can chown the very directory that is about
# to be mounted. The image used is the one being started, which start_container
# has just checked is loaded.
ensure_uploads_writable() {
  local image="$1"

  # -v creates the host directory (as root) if it does not exist yet, which is
  # exactly the case this then repairs.
  docker run --rm --user 0 -v "$UPLOADS_DIR:/mnt/uploads" "$image" \
    chown -R "$APP_UID:$APP_UID" /mnt/uploads >/dev/null \
    || die "could not make $UPLOADS_DIR writable by uid $APP_UID"
}

start_container() {
  local version="$1"

  docker image inspect "$IMAGE_NAME:$version" >/dev/null 2>&1 \
    || die "image $IMAGE_NAME:$version is not loaded on this server"

  # Before the mount, not after: the app has to find it writable on first request.
  ensure_uploads_writable "$IMAGE_NAME:$version"

  # Both are server-owned and never in the image. Without secret_key.txt the app
  # falls back to a random key per process, which silently logs everyone out on
  # every deploy and every worker restart.
  [ -f "$CONFIG_DIR/config.json" ] || die "$CONFIG_DIR/config.json is missing — scp it there first"
  [ -f "$CONFIG_DIR/secret_key.txt" ] || die "$CONFIG_DIR/secret_key.txt is missing — scp it there first"

  check_network

  # -f: also covers a container left in a stopped/created state.
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

  # `create` + `network connect` + `start` rather than plain `run`: `docker run`
  # takes a single --network, and this app needs two (nginx's and Mongo's). Doing
  # it in that order means the container has never run with only one of them.
  docker create \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    `# No published port at all: on this network the app answers at` \
    `# http://$CONTAINER_NAME:$APP_PORT through docker's internal DNS, and` \
    `# nothing at all is bound on the host.` \
    --network "$DOCKER_NETWORK" \
    `# Lets the server's config.json point at a MongoDB running on the HOST` \
    `# (mongo.server = "host.docker.internal") when MONGO_NETWORK is empty.` \
    --add-host=host.docker.internal:host-gateway \
    `# The sub-path nginx serves the app under. It comes from deploy/config.sh,` \
    `# the same file that renders the nginx snippet, so the proxy's location and` \
    `# the app's generated links cannot disagree.` \
    -e "URL_PREFIX=$URL_PREFIX" \
    `# Config is the server's, read-only, and never part of the image.` \
    -v "$CONFIG_DIR/config.json:/app/config.json:ro" \
    -v "$CONFIG_DIR/secret_key.txt:/app/secret_key.txt:ro" \
    `# Uploaded item photos. THE reason this has to be a volume: the image is` \
    `# rebuilt from scratch every release, so anything written inside the` \
    `# container is gone at the next deploy — these are user data.` \
    -v "$UPLOADS_DIR:/app/inventory/api/static/uploads" \
    "$IMAGE_NAME:$version" >/dev/null

  if [ -n "$MONGO_NETWORK" ]; then
    docker network connect "$MONGO_NETWORK" "$CONTAINER_NAME"
  fi

  docker start "$CONTAINER_NAME" >/dev/null

  echo "started $CONTAINER_NAME on $IMAGE_NAME:$version"
}

# Hit /health from *inside* the container. Nothing is published on the host, so
# the probe cannot come from outside; `docker exec` is the way in, and python is
# already there (the slim image has no curl).
#
# /health is registered at the app root and URL_PREFIX only affects generated
# URLs (SCRIPT_NAME), not routing — so the path is the same with or without a
# prefix, which is what makes this probe independent of the proxy.
probe_health() {
  docker exec "$CONTAINER_NAME" python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$APP_PORT/health', timeout=3)" \
    >/dev/null 2>&1
}

# Poll until gunicorn is actually answering (a fresh container needs a second or
# two). Returns non-zero if it never does.
wait_for_health() {
  local attempts="${1:-15}"
  for _ in $(seq 1 "$attempts"); do
    if probe_health; then
      echo "health check ok (/health inside $CONTAINER_NAME)"
      return 0
    fi
    sleep 2
  done
  echo "health check FAILED (/health inside $CONTAINER_NAME)" >&2
  docker logs --tail 40 "$CONTAINER_NAME" >&2 || true
  return 1
}

# --- subcommands -----------------------------------------------------------

# Load the freshly uploaded .tar, switch to it, and record the version swap.
cmd_activate() {
  local version="${1:?activate needs a version}"
  local tarball="$RELEASES_DIR/$version.tar"

  [ -f "$tarball" ] || die "$tarball not found"
  docker load -i "$tarball"

  # Version bookkeeping happens *before* the restart: if the new container fails
  # to come up, previous_version.txt already points at what to roll back to.
  local current
  current="$(read_version "$CURRENT_FILE")"
  if [ -n "$current" ]; then          # absent on the very first deploy
    echo "$current" > "$PREVIOUS_FILE"
  fi
  echo "$version" > "$CURRENT_FILE"

  start_container "$version"
  wait_for_health
}

# Swap back to previous_version.txt. The two version files trade places, so a
# second rollback returns to where you started.
cmd_rollback() {
  local current previous
  current="$(read_version "$CURRENT_FILE")"
  previous="$(read_version "$PREVIOUS_FILE")"

  [ -n "$previous" ] || die "no previous version recorded — nothing to roll back to"
  if [ "$previous" = "$current" ]; then
    die "previous version is the current one ($current)"
  fi

  start_container "$previous"

  echo "$previous" > "$CURRENT_FILE"
  if [ -n "$current" ]; then
    echo "$current" > "$PREVIOUS_FILE"
  else
    rm -f "$PREVIOUS_FILE"
  fi

  echo "rolled back to $previous (was $current)"
  wait_for_health
}

# Keep the $KEEP_RELEASES newest tarballs and images; never touch what is running
# or what rollback needs.
cmd_prune() {
  local keep="$KEEP_RELEASES" current previous
  current="$(read_version "$CURRENT_FILE")"
  previous="$(read_version "$PREVIOUS_FILE")"

  local kept=0
  # Newest first; anything past the limit goes, unless it is current/previous.
  for tarball in $(ls -1t "$RELEASES_DIR"/*.tar 2>/dev/null); do
    local version
    version="$(basename "$tarball" .tar)"
    kept=$((kept + 1))
    if [ "$kept" -le "$keep" ] || [ "$version" = "$current" ] || [ "$version" = "$previous" ]; then
      continue
    fi
    echo "pruning $version"
    rm -f "$tarball"
    docker image rm "$IMAGE_NAME:$version" >/dev/null 2>&1 || true
  done

  # Images with no tarball left (e.g. loaded by hand) follow the same rule.
  for version in $(docker images --format '{{.Tag}}' "$IMAGE_NAME" | tail -n +$((keep + 1))); do
    if [ "$version" = "$current" ] || [ "$version" = "$previous" ]; then
      continue
    fi
    docker image rm "$IMAGE_NAME:$version" >/dev/null 2>&1 || true
  done
}

cmd_status() {
  echo "current : $(read_version "$CURRENT_FILE")"
  echo "previous: $(read_version "$PREVIOUS_FILE")"
  echo
  # No Ports column: nothing is published, that is the point.
  docker ps --filter "name=^/$CONTAINER_NAME$" \
    --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
  echo
  echo "prefix  : ${URL_PREFIX%/}/"
  echo "network : $DOCKER_NETWORK -> http://$CONTAINER_NAME:$APP_PORT"
  echo "on it   : $(docker network inspect "$DOCKER_NETWORK" \
    --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo '(no such network)')"
  if [ -n "$MONGO_NETWORK" ]; then
    echo "mongo   : $MONGO_NETWORK"
    echo "on it   : $(docker network inspect "$MONGO_NETWORK" \
      --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo '(no such network)')"
  fi
  if probe_health; then
    echo "health  : ok"
  else
    echo "health  : NOT answering"
  fi
}

cmd_versions() {
  echo "current : $(read_version "$CURRENT_FILE")"
  echo "previous: $(read_version "$PREVIOUS_FILE")"
  echo "releases:"
  ls -1t "$RELEASES_DIR"/*.tar 2>/dev/null | xargs -r -n1 basename || echo "  (none)"
}

# One-time server preparation: directory layout + an uploads/ the container can
# write.
cmd_init() {
  mkdir -p "$RELEASES_DIR" "$CONFIG_DIR" "$UPLOADS_DIR" 2>/dev/null || true
  # The app runs as uid 10001 inside the container and saves uploaded images into
  # the bind-mounted uploads/, so that directory has to belong to that uid. Try it
  # here for tidiness only — `sudo -n` so a password prompt can never hang a
  # scripted setup — because every start_container repairs it anyway, from inside
  # docker and without any host privileges.
  sudo -n chown -R "$APP_UID:$APP_UID" "$UPLOADS_DIR" 2>/dev/null \
    || chown -R "$APP_UID:$APP_UID" "$UPLOADS_DIR" 2>/dev/null \
    || echo "note: $UPLOADS_DIR not chowned here — the first deploy will do it" >&2
  chmod 700 "$CONFIG_DIR"
  echo "layout ready under $REMOTE_DIR"

  # Fail here rather than at the first deploy if a network is not around.
  check_network
  echo "network '$DOCKER_NETWORK' found"
  [ -n "$MONGO_NETWORK" ] && echo "network '$MONGO_NETWORK' found"
}

# Validate the snippet setup_server.sh just uploaded, then restart nginx.
#
# `nginx -t` FIRST, and remove the file if it fails: this proxy fronts other
# sites, and a broken include would take them all down at its next restart.
cmd_nginx_reload() {
  local conf="$NGINX_CONF_DIR/$NGINX_CONF_NAME"

  docker container inspect "$NGINX_CONTAINER" >/dev/null 2>&1 \
    || die "no container named '$NGINX_CONTAINER' — is the proxy running?"
  [ -f "$conf" ] || die "$conf was not uploaded"

  echo "==> Validating nginx config"
  if ! docker exec "$NGINX_CONTAINER" nginx -t; then
    rm -f "$conf"
    die "nginx refused the config — removed $conf, nginx left untouched"
  fi

  echo "==> Restarting $NGINX_CONTAINER"
  docker restart "$NGINX_CONTAINER" >/dev/null
  echo "$NGINX_CONTAINER restarted with $conf"
}

command="${1:-}"
shift || true
case "$command" in
  init)         cmd_init "$@" ;;
  nginx_reload) cmd_nginx_reload "$@" ;;
  activate)     cmd_activate "$@" ;;
  rollback)     cmd_rollback "$@" ;;
  prune)        cmd_prune "$@" ;;
  status)       cmd_status "$@" ;;
  health)       wait_for_health "${1:-1}" ;;
  versions)     cmd_versions "$@" ;;
  *)            die "unknown command '$command'" \
                    "(init|nginx_reload|activate|rollback|prune|status|health|versions)" ;;
esac
