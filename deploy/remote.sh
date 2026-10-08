#!/usr/bin/env bash
# THE SERVER SIDE of the deploy. Never run this from your laptop.
#
# deploy.sh and rollback.sh upload this file before every run and then call one of
# its subcommands over SSH. It exists so that how the app is run (its systemd unit
# and environment) lives in exactly one place: a rollback must start the app the
# same way as a deploy, and the CLI (`run set-admin`) must see the same database.
#
# Usage: bash remote.sh <init | nginx_reload | activate VERSION | rollback
#                        | prune | status | health | versions>
set -euo pipefail

# Defaults mirror deploy/config.sh's production ones; the caller always overrides
# them via env, which is also how a staging run gets its own names and directory.
REMOTE_DIR="${REMOTE_DIR:-/home/ced/rust/inventory}"
SERVICE_NAME="${SERVICE_NAME:-inventory}"
URL_PREFIX="${URL_PREFIX:-/inventory}"
KEEP_RELEASES="${KEEP_RELEASES:-3}"
SOCKET_DIR="${SOCKET_DIR:-/home/ced/services/nginx_proxy/sockets}"
NGINX_SOCKET_DIR="${NGINX_SOCKET_DIR:-/sockets}"
SOCKET_NAME="${SOCKET_NAME:-inventory.sock}"
NGINX_CONTAINER="${NGINX_CONTAINER:-nginx-proxy}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/home/ced/services/nginx_proxy/sites/apps}"
NGINX_CONF_NAME="${NGINX_CONF_NAME:-inventory.conf}"

RELEASES_DIR="$REMOTE_DIR/releases"
CONFIG_DIR="$REMOTE_DIR/config"
DATA_DIR="$REMOTE_DIR/data"
UPLOADS_DIR="$DATA_DIR/uploads"
DB_DIR="$DATA_DIR/db"
CURRENT_LINK="$REMOTE_DIR/current"
CURRENT_FILE="$REMOTE_DIR/current_version.txt"
PREVIOUS_FILE="$REMOTE_DIR/previous_version.txt"
ENV_FILE="$REMOTE_DIR/app.env"
RUN_SCRIPT="$REMOTE_DIR/run"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/$SERVICE_NAME.service"
SOCKET_PATH="$SOCKET_DIR/$SOCKET_NAME"

die() { echo "error: $*" >&2; exit 1; }

read_version() { [ -f "$1" ] && cat "$1" || true; }

# --- environment -----------------------------------------------------------

# The app's whole environment, in one file read by the unit (EnvironmentFile) AND by
# `run` and the migrations, so the CLI always acts on the database the server uses.
#
# INVENTORY_ROOT is config/: the app reads config.json and secret_key.txt from its
# root. The database (a bare path: `sqlite:///abs` would read as relative) and the
# photos are given explicitly, as they live in data/. SOCKET_PATH is where the app
# listens (no port), and what `inventory healthcheck` probes.
write_env() {
  cat > "$ENV_FILE.tmp" <<EOF
INVENTORY_ROOT=$CONFIG_DIR
DATABASE_URL=$DB_DIR/inventory.sqlite3
UPLOADS_DIR=$UPLOADS_DIR
SOCKET_PATH=$SOCKET_PATH
URL_PREFIX=$URL_PREFIX
RUST_LOG=info
EOF
  mv "$ENV_FILE.tmp" "$ENV_FILE"

  # `$REMOTE_DIR/run <command>` runs the current binary with that environment:
  #   ssh nuc150 /home/ced/rust/inventory/run set-admin <username>
  cat > "$RUN_SCRIPT" <<EOF
#!/usr/bin/env bash
set -a; . '$ENV_FILE'; set +a
exec '$CURRENT_LINK/inventory' "\$@"
EOF
  chmod +x "$RUN_SCRIPT"
}

# Runs a given binary with the app's environment.
with_env() {
  ( set -a; . "$ENV_FILE"; set +a; "$@" )
}

# The systemd user unit. Rewritten every time, so a change here reaches the server
# with the next deploy or rollback; daemon-reload only when it changed.
write_unit() {
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_FILE.tmp" <<EOF
[Unit]
Description=Inventory ($SERVICE_NAME)
After=network-online.target

[Service]
WorkingDirectory=$REMOTE_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$CURRENT_LINK/inventory serve
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
  if cmp -s "$UNIT_FILE.tmp" "$UNIT_FILE"; then
    rm -f "$UNIT_FILE.tmp"
  else
    mv "$UNIT_FILE.tmp" "$UNIT_FILE"
    systemctl --user daemon-reload
  fi
  systemctl --user enable "$SERVICE_NAME" >/dev/null 2>&1
}

# --- nginx -----------------------------------------------------------------

# The socket directory belongs to nginx_proxy, which bind-mounts it into its
# container — we only use it. Deliberately NOT created here: if it is missing when
# the proxy's compose starts, docker creates it as root and the app can no longer
# write its socket.
check_socket_dir() {
  [ -d "$SOCKET_DIR" ] || die "$SOCKET_DIR does not exist.$(socket_dir_help)"
  [ -w "$SOCKET_DIR" ] || die "$SOCKET_DIR is not writable by $(id -un)."

  local mounted
  mounted="$(docker inspect "$NGINX_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Source "'"$SOCKET_DIR"'"}}{{.Destination}}{{end}}{{end}}' \
    2>/dev/null)" || die "no container named '$NGINX_CONTAINER' — is the proxy running?"
  [ "$mounted" = "$NGINX_SOCKET_DIR" ] || die \
    "$NGINX_CONTAINER does not mount $SOCKET_DIR on $NGINX_SOCKET_DIR (currently: '${mounted:-nothing}').$(socket_dir_help)"
}

socket_dir_help() {
  cat <<HELP

Once, in the nginx_proxy project:
  mkdir -p $SOCKET_DIR        (as $(id -un), BEFORE restarting the proxy)
  docker-compose.yml, service nginx, volumes:
    - $SOCKET_DIR:$NGINX_SOCKET_DIR:ro
  docker compose up -d        (recreates the container with the new mount)
HELP
}

# The app may answer on the host while nginx still cannot see its socket (mount
# missing or pointing elsewhere): check from inside the container too.
probe_nginx_view() {
  docker exec "$NGINX_CONTAINER" test -S "$NGINX_SOCKET_DIR/$SOCKET_NAME" 2>/dev/null
}

# --- app -------------------------------------------------------------------

# Bring the database schema up to what a release expects, with that release's
# binary, BEFORE it is started. `inventory migrate` backs the database up into
# data/db/backups/ first whenever there is something to apply, and does nothing
# otherwise. A migration is a single transaction, so one that fails leaves the
# database as it was — and the running version keeps serving.
#
# Only deploys migrate. A rollback starts the previous binary on the schema as it
# now is: fine for additive migrations, otherwise restore a backup by hand.
run_migrations() {
  local version="$1"
  with_env "$RELEASES_DIR/$version/inventory" migrate \
    || die "migrations failed on $version — nothing was started, the previous version still runs"
}

# Point `current` at a release and (re)start the unit on it. This is the single
# source of truth for how the app is run.
start_version() {
  local version="$1"

  [ -x "$RELEASES_DIR/$version/inventory" ] || die "release $version is not on this server"

  # Both are server-owned and never shipped. Without secret_key.txt the app falls
  # back to a random key per process, which silently logs everyone out on every
  # deploy and every restart.
  [ -f "$CONFIG_DIR/config.json" ] || die "$CONFIG_DIR/config.json is missing — scp it there first"
  [ -f "$CONFIG_DIR/secret_key.txt" ] || die "$CONFIG_DIR/secret_key.txt is missing — scp it there first"
  check_socket_dir

  write_env
  write_unit

  # Replace the symlink atomically: `current` never points nowhere.
  ln -sfn "releases/$version" "$CURRENT_LINK.tmp"
  mv -T "$CURRENT_LINK.tmp" "$CURRENT_LINK"

  systemctl --user restart "$SERVICE_NAME"
  echo "started $SERVICE_NAME on $version"
}

# Ask the running app for /health with its own `inventory healthcheck`, through the
# socket nginx uses.
#
# /health is registered at the app root and URL_PREFIX only affects generated
# URLs, not routing — so the path is the same with or without a prefix, which is
# what makes this probe independent of the proxy.
probe_health() {
  [ -x "$CURRENT_LINK/inventory" ] \
    && SOCKET_PATH="$SOCKET_PATH" "$CURRENT_LINK/inventory" healthcheck >/dev/null 2>&1
}

# Poll until the app is actually answering (a fresh start needs a moment).
# Returns non-zero if it never does.
wait_for_health() {
  local attempts="${1:-15}"
  for _ in $(seq 1 "$attempts"); do
    if probe_health; then
      echo "health check ok (/health on $SOCKET_PATH)"
      if probe_nginx_view; then
        echo "socket visible from $NGINX_CONTAINER ($NGINX_SOCKET_DIR/$SOCKET_NAME)"
      else
        echo "WARNING: $NGINX_CONTAINER does not see $NGINX_SOCKET_DIR/$SOCKET_NAME" >&2
      fi
      return 0
    fi
    sleep 2
  done
  echo "health check FAILED (/health on $SOCKET_PATH)" >&2
  journalctl --user -u "$SERVICE_NAME" -n 40 --no-pager >&2 || true
  return 1
}

# --- subcommands -----------------------------------------------------------

# Switch to the freshly uploaded release and record the version swap.
cmd_activate() {
  local version="${1:?activate needs a version}"
  local binary="$RELEASES_DIR/$version/inventory"

  [ -f "$binary" ] || die "$binary not found"
  chmod +x "$binary"
  write_env

  # Before any bookkeeping: if this fails, nothing about the deploy has happened.
  run_migrations "$version"

  # Version bookkeeping happens *before* the restart: if the new version fails to
  # come up, previous_version.txt already points at what to roll back to.
  local current
  current="$(read_version "$CURRENT_FILE")"
  if [ -n "$current" ]; then          # absent on the very first deploy
    echo "$current" > "$PREVIOUS_FILE"
  fi
  echo "$version" > "$CURRENT_FILE"

  start_version "$version"
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

  start_version "$previous"

  echo "$previous" > "$CURRENT_FILE"
  if [ -n "$current" ]; then
    echo "$current" > "$PREVIOUS_FILE"
  else
    rm -f "$PREVIOUS_FILE"
  fi

  echo "rolled back to $previous (was $current)"
  wait_for_health
}

# Keep the $KEEP_RELEASES newest releases; never touch what is running or what
# rollback needs.
cmd_prune() {
  local keep="$KEEP_RELEASES" current previous kept=0
  current="$(read_version "$CURRENT_FILE")"
  previous="$(read_version "$PREVIOUS_FILE")"

  # Versions are UTC timestamps: newest first is reverse name order.
  for dir in $(ls -1d "$RELEASES_DIR"/*/ 2>/dev/null | sort -r); do
    local version
    version="$(basename "$dir")"
    kept=$((kept + 1))
    if [ "$kept" -le "$keep" ] || [ "$version" = "$current" ] || [ "$version" = "$previous" ]; then
      continue
    fi
    echo "pruning $version"
    rm -f "$RELEASES_DIR/$version/inventory"
    rmdir "$RELEASES_DIR/$version"
  done
}

cmd_status() {
  echo "current : $(read_version "$CURRENT_FILE")"
  echo "previous: $(read_version "$PREVIOUS_FILE")"
  echo
  systemctl --user status "$SERVICE_NAME" --no-pager --lines 0 || true
  echo
  echo "prefix  : ${URL_PREFIX%/}/"
  echo "socket  : $SOCKET_PATH -> $NGINX_CONTAINER:$NGINX_SOCKET_DIR/$SOCKET_NAME"
  if probe_health; then
    echo "health  : ok"
  else
    echo "health  : NOT answering"
  fi
  if probe_nginx_view; then
    echo "nginx   : sees the socket"
  else
    echo "nginx   : does NOT see the socket"
  fi
}

cmd_versions() {
  echo "current : $(read_version "$CURRENT_FILE")"
  echo "previous: $(read_version "$PREVIOUS_FILE")"
  echo "releases:"
  ls -1 "$RELEASES_DIR" 2>/dev/null | sort -r | sed 's/^/  /' || echo "  (none)"
}

# One-time server preparation: directory layout, and a systemd user manager that
# keeps running when nobody is logged in.
cmd_init() {
  mkdir -p "$RELEASES_DIR" "$CONFIG_DIR" "$UPLOADS_DIR" "$DB_DIR"
  chmod 700 "$CONFIG_DIR"
  echo "layout ready under $REMOTE_DIR"

  # The app now runs as this user. Directories left owned by the container's
  # uid 10001 would make every page a 500 (database) or every upload an EACCES.
  local foreign
  foreign="$(find "$DATA_DIR" ! -user "$(id -u)" -print -quit 2>/dev/null || true)"
  if [ -n "$foreign" ]; then
    echo "WARNING: $DATA_DIR holds files not owned by $(id -un) (e.g. $foreign). Fix it once with:" >&2
    echo "  sudo chown -R $(id -un): $DATA_DIR" >&2
  fi

  # Without lingering, user units stop at logout and do not start at boot.
  if [ "$(loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null)" = yes ]; then
    echo "lingering already enabled for $(id -un)"
  elif sudo -n loginctl enable-linger "$(id -un)" 2>/dev/null || loginctl enable-linger "$(id -un)" 2>/dev/null; then
    echo "lingering enabled for $(id -un)"
  else
    echo "WARNING: could not enable lingering; the app would stop at logout. Run once:" >&2
    echo "  sudo loginctl enable-linger $(id -un)" >&2
  fi

  systemctl --user show-environment >/dev/null 2>&1 \
    || die "no systemd user manager for $(id -un) (systemctl --user fails)"
  echo "systemd user manager ok"

  # Fail here rather than at the first deploy.
  check_socket_dir
  echo "$SOCKET_DIR is mounted in $NGINX_CONTAINER on $NGINX_SOCKET_DIR"
}

# Validate the snippet setup_server.sh just uploaded, then reload nginx.
#
# `nginx -t` FIRST, and remove the file if it fails: this proxy fronts other
# sites, and a broken include would take them all down at its next restart.
# Reload rather than restart: the other sites keep their connections.
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

  echo "==> Reloading $NGINX_CONTAINER"
  docker exec "$NGINX_CONTAINER" nginx -s reload
  echo "$NGINX_CONTAINER reloaded with $conf"
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
