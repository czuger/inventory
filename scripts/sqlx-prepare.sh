#!/bin/sh
# Regenerate .sqlx/, the offline data the sqlx query macros compile against.
#
# Builds a throwaway database from migrations/ with the sqlite3 CLI (no need for the
# app to compile first), then type-checks every query against it while sqlx writes
# one .sqlx/query-*.json per query. Commit the result.
set -eu
cd "$(dirname "$0")/.."

db=target/sqlx-prepare.sqlite3
mkdir -p target
rm -f "$db" "$db-wal" "$db-shm"
for migration in migrations/*.sql; do
    sqlite3 "$db" < "$migration"
done

rm -rf .sqlx
mkdir .sqlx
# Force the macros to run again even if nothing else changed.
touch src/lib.rs
SQLX_DATABASE_URL="sqlite:$db" SQLX_OFFLINE=false SQLX_OFFLINE_DIR="$PWD/.sqlx" \
    cargo check --all-targets --quiet
echo "wrote $(ls .sqlx | wc -l | tr -d ' ') query files to .sqlx/"
