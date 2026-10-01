# Deploy shortcuts. Everything real lives in deploy/ — see deploy/config.sh for the
# server settings, all overridable from the environment:
#
#   make deploy SSH_HOST=ced@other-box
#
.PHONY: help setup nginx deploy rollback logs status versions test

# Read the same settings the scripts use, so logs/status can talk to the server
# without duplicating them here.
SSH_HOST ?= ced@nuc150
REMOTE_DIR ?= /home/ced/python/inventory
CONTAINER_NAME ?= app-inventory
APP_PORT ?= 8000

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup:  ## One-time server preparation (directories, Docker check, nginx config)
	@./deploy/setup_server.sh

nginx:  ## Re-install the nginx snippet and restart the proxy (no deploy)
	@./deploy/nginx.sh

deploy:  ## Build, ship and start the new version, then health check it
	@./deploy/deploy.sh

rollback:  ## Switch back to the previously deployed version
	@./deploy/rollback.sh

logs:  ## Follow the container logs (Ctrl-C to stop)
	@ssh -t $(SSH_HOST) "docker logs -f --tail 100 $(CONTAINER_NAME)"

status:  ## Running container + /health, as seen from the server
	@ssh $(SSH_HOST) "docker ps --filter 'name=^/$(CONTAINER_NAME)$$' \
		--format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'; \
		echo; \
		cat $(REMOTE_DIR)/current_version.txt 2>/dev/null | sed 's/^/current : /'; \
		cat $(REMOTE_DIR)/previous_version.txt 2>/dev/null | sed 's/^/previous: /'; \
		echo; \
		docker exec $(CONTAINER_NAME) python -c \
			\"import urllib.request; urllib.request.urlopen('http://127.0.0.1:$(APP_PORT)/health', timeout=3)\" \
			> /dev/null 2>&1 \
			&& echo 'health  : ok' \
			|| echo 'health  : NOT answering'"

versions:  ## List the versions kept on the server
	@ssh $(SSH_HOST) "ls -1t $(REMOTE_DIR)/releases/*.tar 2>/dev/null | xargs -r -n1 basename"

test:  ## Run the test suite locally
	@python -m pytest
