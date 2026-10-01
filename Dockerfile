# Image for the Flask app.
#
# It carries code only: config.json and secret_key.txt are mounted from the
# server's config/ directory at run time — see deploy/remote.sh. Nothing here ever
# bakes in a credential, which is why .dockerignore drops both files. Nor any data:
# the SQLite database lives in the server's data/db/, mounted at /app/data.
#
# No `--platform` is pinned here on purpose: deploy.sh passes the *server's*
# architecture on the build command line (TARGET_PLATFORM, default linux/amd64),
# so building on an Apple Silicon Mac still yields an x86_64 image. Building this
# file by hand on a Mac gives you an arm64 image the Linux server cannot run.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes, so
# editing the app is a fast rebuild. Pillow and reportlab ship manylinux wheels,
# so no build toolchain is needed here.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The application itself. misc/set_admin.py comes along so admin rights can be
# granted with `docker exec` — it is the only supported way to get the first
# admin, since the flag exists nowhere in the UI.
COPY inventory/ ./inventory/
COPY misc/set_admin.py ./misc/set_admin.py

# The migrations. A deploy runs them from this image (`python -m
# inventory.db.migrate`, see deploy/remote.sh) before starting it.
COPY alembic.ini ./
COPY alembic/ ./alembic/

# inventory/libs/initialization.py locates the project root by walking up until it
# finds one of requirements.txt / .git / README.md, and then reads config.json and
# secret_key.txt from there. requirements.txt above lands in /app, which is what
# makes /app the root — and what makes the two mounts in remote.sh land where the
# app looks for them.

# Non-root. The uid is fixed (not auto-assigned) because the server bind-mounts
# data/uploads and data/db onto the two directories below and has to chown them to
# the same uid — remote.sh does it before every container start, from a throwaway
# root container so no host privileges are needed. Without that, saving a photo
# fails with EACCES, and SQLite cannot even open the database (it creates its
# -wal and -shm files next to it, so it needs the directory, not just the file).
RUN useradd --system --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/inventory/api/static/uploads /app/data \
    && chown -R appuser:appuser /app/inventory/api/static/uploads /app/data
USER appuser

# No EXPOSE and no published port anywhere: the container runs on its own docker
# network (deploy/remote.sh) and is reached by container name over it. Nothing is
# bound on the host.

# No curl in the slim image — urllib does the same job with what is already here.
# /health is registered at the app root, so this probe is unaffected by URL_PREFIX.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# 2 workers, threads left at 1: the work here is short request/response, apart
# from PDF generation which is CPU-bound and gains nothing from threads. Two
# processes sharing one SQLite file is fine in WAL mode — readers never block, and
# a writer waits (busy_timeout) for the other's write to finish.
#
# --forwarded-allow-ips is what makes `url_for(..., _external=True)` build https://
# URLs: gunicorn only honours nginx's X-Forwarded-Proto when the client IP is
# trusted, and the default (127.0.0.1) never matches here — nginx is a *separate
# container*, so it comes from a 172.x address on the shared docker network. Left
# untrusted, the Discord redirect URI comes out as http:// and no longer matches
# the one registered on the Discord application.
# `*` rather than a list: the container publishes no port and is only reachable by
# name over the docker networks, so nginx is the only client that can reach it at
# all — and pinning IPs would break at the first nginx container recreation.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--timeout", "120", \
     "--forwarded-allow-ips", "*", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "inventory.api.app:app"]
