# Image for the Rust app: one binary, built in a throwaway stage.
#
# It carries code only, like the Python image did: config.json and secret_key.txt are
# mounted from the server's config/ directory at run time, the database lives in the
# server's data/db/ (mounted at /app/data) and the photos in data/uploads (mounted at
# /app/inventory/api/static/uploads). Those are the paths deploy/remote.sh already mounts,
# so switching images needs only its migrate command changed (`inventory migrate`).
#
# No `--platform` is pinned: deploy.sh passes the server's architecture at build time.

FROM rust:1-slim-bookworm AS build
WORKDIR /src

# Dependencies first, so editing the app does not rebuild them: build a stub with the real
# manifests, then throw the stub away.
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs && echo '' > src/lib.rs \
    && printf 'fn main() {}\n' > build.rs \
    && cargo build --release --locked \
    && rm -rf src build.rs target/release/.fingerprint/inventory-*

# The app. Queries compile against the committed .sqlx/ data: no database at build time.
COPY build.rs sqlx.toml ./
COPY .sqlx .sqlx
COPY migrations migrations
COPY templates templates
COPY static static
COPY i18n i18n
COPY src src
ENV SQLX_OFFLINE=true
RUN cargo build --release --locked

FROM debian:bookworm-slim
# The system CA bundle: Discord's certificate is checked against it.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /src/target/release/inventory /usr/local/bin/inventory

# The app finds its root (config.json, secret_key.txt, data/) by walking up to the first
# directory holding README.md, requirements.txt or .git: this marker makes it /app.
# Non-root with a fixed uid, which remote.sh chowns the mounted directories to.
RUN touch /app/README.md \
    && useradd --system --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/inventory/api/static/uploads /app/data \
    && chown -R appuser:appuser /app/inventory/api/static/uploads /app/data
USER appuser

ENV BIND_ADDR=0.0.0.0:8000 \
    RUST_LOG=info

# Probes /health from inside the container (there is no curl in the image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["inventory", "healthcheck"]

# No EXPOSE: the container is reached by name over the nginx docker network.
CMD ["inventory", "serve"]
