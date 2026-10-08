# Deploy shortcuts. Everything real lives in deploy/ — see deploy/config.sh for the
# server settings, all overridable from the environment:
#
#   make deploy SSH_HOST=ced@other-box
#
# Every target acts on production unless told otherwise. ENV=staging targets the
# separate staging instance (its own directory, database, systemd unit, socket and URL
# prefix — see deploy/config.sh):
#
#   make setup ENV=staging      # once
#   make deploy ENV=staging
#   make logs ENV=staging
#
.PHONY: help setup nginx deploy rollback logs status versions test

# Only from the command line: ENV is also a shell variable (sh's startup file), and
# one inherited from the environment must not pick the instance. Unset, the
# scripts default to production; DEPLOY_ENV=staging in the environment works too.
ifeq ($(origin ENV),command line)
export DEPLOY_ENV := $(ENV)
endif

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-10s %s\n", $$1, $$2}'
	@echo
	@echo "  Add ENV=staging to act on the staging instance instead of production."

setup:  ## One-time server preparation (directories, systemd check, nginx config)
	@./deploy/setup_server.sh

nginx:  ## Re-install the nginx snippet and reload nginx (no deploy)
	@./deploy/nginx.sh

deploy:  ## Build, ship and start the new version, then health check it
	@./deploy/deploy.sh

rollback:  ## Switch back to the previously deployed version
	@./deploy/rollback.sh

logs:  ## Follow the app's logs (Ctrl-C to stop)
	@./deploy/server.sh logs

status:  ## Running unit + /health, as seen from the server
	@./deploy/server.sh status

versions:  ## List the versions kept on the server
	@./deploy/server.sh versions

test:  ## Run the test suite and the linter locally
	@cargo test
	@cargo clippy --all-targets -- -D warnings
