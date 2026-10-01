#!/usr/bin/env bash
# Re-render and re-install the nginx snippet on its own: make nginx
#
# Same code path as the last step of `make setup` — use it after editing
# deploy/nginx/*.template or changing the prefix/port in deploy/config.sh, instead
# of re-running the whole setup. The server validates the file before nginx
# restarts, and drops it if it does not parse.
#
# Changing URL_PREFIX needs BOTH this and a redeploy: the prefix is also passed to
# the container (remote.sh), so the app knows what to build its links under.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/config.sh" "$@"

echo "==> Installing $NGINX_CONF_NAME ($DEPLOY_ENV) on $SSH_HOST:$NGINX_CONF_DIR"
install_nginx_conf
