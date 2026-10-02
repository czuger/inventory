//! The schema and the connection settings (ported from `tests/test_database.py`), and
//! `inventory migrate` against databases Alembic built.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use std::borrow::Cow;
use std::path::Path;

use sqlx::migrate::{Migration, MigrationType, Migrator};
use sqlx::{AssertSqlSafe, SqlSafeStr as _};
use sqlx::{Row, SqlitePool};

use common::TestDb;
use inventory::{db, migrate};

type MasterRow = (String, String, String, Option<String>);

/// The schema `alembic upgrade head` built, as `sqlite_master` rows in creation order.
fn alembic_schema() -> Vec<MasterRow> {
    serde_json::from_str(include_str!("fixtures/alembic_schema.json")).unwrap()
}

async fn schema(pool: &SqlitePool) -> Vec<MasterRow> {
    sqlx::query_as(
        "SELECT type, name, tbl_name, sql FROM sqlite_master \
         WHERE tbl_name NOT IN ('_sqlx_migrations', 'alembic_version') ORDER BY rowid",
    )
    .fetch_all(pool)
    .await
    .unwrap()
}

/// A database as the Python app's deploy left it: Alembic's schema and version table.
async fn alembic_database(path: &Path, revision: &str) -> SqlitePool {
    let pool = db::connect(path).await.unwrap();
    sqlx::raw_sql(
        "CREATE TABLE alembic_version (\n\tversion_num TEXT NOT NULL, \n\t\
         CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)\n)",
    )
    .execute(&pool)
    .await
    .unwrap();
    for (_, _, _, sql) in alembic_schema() {
        if let Some(sql) = sql.filter(|sql| !sql.starts_with("CREATE TABLE sqlite_sequence")) {
            // The `;` keeps the statement's trailing whitespace in sqlite_master, as Alembic's did.
            sqlx::raw_sql(AssertSqlSafe(sql + ";")).execute(&pool).await.unwrap();
        }
    }
    sqlx::query("INSERT INTO alembic_version VALUES (?)").bind(revision).execute(&pool).await.unwrap();
    pool
}

async fn seed(pool: &SqlitePool) {
    sqlx::raw_sql(
        "INSERT INTO associations (name, slug) VALUES ('Test Asso', 'test');
         INSERT INTO games (name) VALUES ('Test Game');
         INSERT INTO locations (association_id, room, spot) VALUES (1, 'Room 1', '');
         INSERT INTO users (discord_id, username, is_admin) VALUES ('100', 'admin_user', 1);
         INSERT INTO miniatures (association_id, category, type, game_id, scale, quantity, borrowing_count,
                                 sticker_printed, location_id, images)
             VALUES (1, 'Miniature', 'Infantry', 1, '28mm', 2, 0, 0, 1, '[]');",
    )
    .execute(pool)
    .await
    .unwrap();
}

async fn count(pool: &SqlitePool, table: &str) -> i64 {
    sqlx::query_scalar(AssertSqlSafe(format!("SELECT count(*) FROM {table}"))).fetch_one(pool).await.unwrap()
}

async fn applied_versions(pool: &SqlitePool) -> Vec<i64> {
    sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version").fetch_all(pool).await.unwrap()
}

/// Every migration's version, in order.
fn all_versions() -> Vec<i64> {
    migrate::MIGRATOR.iter().map(|m| m.version).collect()
}

/// Migration 0001 alone: the schema Alembic built.
fn alembic_equivalent() -> Migrator {
    Migrator::with_migrations(migrate::MIGRATOR.iter().take(1).cloned().collect())
}

/// `MIGRATOR` plus one more migration.
fn with_extra_migration(sql: &'static str) -> Migrator {
    let mut migrations: Vec<Migration> = migrate::MIGRATOR.iter().cloned().collect();
    migrations.push(Migration::new(
        9999,
        Cow::Borrowed("extra"),
        MigrationType::Simple,
        AssertSqlSafe(sql).into_sql_str(),
        false,
    ));
    Migrator::with_migrations(migrations)
}

#[tokio::test]
async fn test_models_match_migrations() {
    // Migration 0001 builds exactly what Alembic built: same tables, columns,
    // constraints, indexes, in the same order and with the same SQL text.
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("inventory.sqlite3");
    migrate::run_with(&alembic_equivalent(), &path).await.unwrap();
    assert_eq!(schema(&db::connect(&path).await.unwrap()).await, alembic_schema());
}

#[tokio::test]
async fn test_connection_pragmas() {
    let db = TestDb::new().await;
    let mut conn = db.pool.acquire().await.unwrap();
    let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode").fetch_one(&mut *conn).await.unwrap();
    let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys").fetch_one(&mut *conn).await.unwrap();
    let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous").fetch_one(&mut *conn).await.unwrap();
    let busy_timeout: i64 = sqlx::query_scalar("PRAGMA busy_timeout").fetch_one(&mut *conn).await.unwrap();
    assert_eq!(journal_mode, "wal");
    assert_eq!(foreign_keys, 1);
    assert_eq!(synchronous, 1); // NORMAL
    assert_eq!(busy_timeout, 5000);
}

#[tokio::test]
async fn test_every_app_table_is_strict() {
    let db = TestDb::new().await;
    let rows = sqlx::query(
        "SELECT name, strict FROM pragma_table_list \
         WHERE schema = 'main' AND name NOT LIKE 'sqlite_%' AND name != '_sqlx_migrations'",
    )
    .fetch_all(&db.pool)
    .await
    .unwrap();
    assert_eq!(rows.len(), 15);
    for row in rows {
        let (name, strict): (String, i64) = (row.get(0), row.get(1));
        assert_eq!(strict, 1, "{name} is not STRICT");
    }
}

#[tokio::test]
async fn test_strict_rejects_wrong_type() {
    let db = TestDb::new().await;
    seed(&db.pool).await;
    let err = sqlx::query("UPDATE users SET is_admin = 'yes'").execute(&db.pool).await.unwrap_err();
    assert!(err.to_string().contains("cannot store TEXT value in INTEGER column"), "{err}");
}

#[tokio::test]
async fn test_foreign_keys_are_enforced() {
    let db = TestDb::new().await;
    let err = sqlx::query("INSERT INTO locations (association_id, room, spot) VALUES (999999, 'Nowhere', '')")
        .execute(&db.pool)
        .await
        .unwrap_err();
    assert!(err.to_string().contains("FOREIGN KEY constraint failed"), "{err}");
}

#[tokio::test]
async fn test_ids_are_not_reused() {
    let db = TestDb::new().await;
    seed(&db.pool).await;
    let first_id: i64 = sqlx::query_scalar("SELECT max(id) FROM miniatures").fetch_one(&db.pool).await.unwrap();
    sqlx::query("DELETE FROM miniatures WHERE id = ?").bind(first_id).execute(&db.pool).await.unwrap();
    let next_id: i64 = sqlx::query_scalar(
        "INSERT INTO miniatures (association_id, category, type, game_id, scale, quantity, borrowing_count, \
         sticker_printed, location_id, images) VALUES (1, 'Miniature', 'Cavalry', 1, '28mm', 1, 0, 0, 1, '[]') \
         RETURNING id",
    )
    .fetch_one(&db.pool)
    .await
    .unwrap();
    assert!(next_id > first_id);
}

#[tokio::test]
async fn alembic_database_is_baselined_not_rebuilt() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("inventory.sqlite3");
    let pool = alembic_database(&path, "7b1fd3535193").await;
    seed(&pool).await;

    // Recorded, not rebuilt (later migrations are tested on their own).
    let report = migrate::run_with(&alembic_equivalent(), &path).await.unwrap();
    assert!(report.baselined);
    assert_eq!(report.applied, Vec::<i64>::new());
    assert_eq!(report.backup, None, "nothing was pending, so nothing to back up");

    assert_eq!(applied_versions(&pool).await, vec![1]);
    let checksum: Vec<u8> = sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations").fetch_one(&pool).await.unwrap();
    assert_eq!(checksum, migrate::MIGRATOR.iter().next().unwrap().checksum.to_vec());
    // Data and schema untouched; Alembic's table left for the Python app.
    assert_eq!(count(&pool, "miniatures").await, 1);
    assert_eq!(count(&pool, "alembic_version").await, 1);
    assert_eq!(schema(&pool).await, alembic_schema());

    // A second run has nothing to do.
    let again = migrate::run_with(&alembic_equivalent(), &path).await.unwrap();
    assert!(!again.baselined);
    assert_eq!(again.previous, Some(1));
    assert!(again.applied.is_empty());
}

#[tokio::test]
async fn unknown_alembic_revision_is_refused_untouched() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("inventory.sqlite3");
    let pool = alembic_database(&path, "0123456789ab").await;

    let err = migrate::run(&path).await.unwrap_err();
    assert!(matches!(err, migrate::MigrateError::UnknownAlembicRevision(ref rev) if rev == "0123456789ab"), "{err}");
    let has_sqlx_table: bool =
        sqlx::query_scalar("SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE name = '_sqlx_migrations')")
            .fetch_one(&pool)
            .await
            .unwrap();
    assert!(!has_sqlx_table);
}

#[tokio::test]
async fn fresh_database_is_built_without_backup() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("inventory.sqlite3");
    let report = migrate::run(&path).await.unwrap();
    assert!(!report.baselined);
    assert_eq!(report.previous, None);
    assert_eq!(report.applied, all_versions());
    assert_eq!(report.backup, None);
    assert!(!dir.path().join("backups").exists());
}

#[tokio::test]
async fn pending_migration_is_backed_up_first() {
    let db = TestDb::new().await;
    seed(&db.pool).await;

    let migrator = with_extra_migration("CREATE TABLE extra (id INTEGER PRIMARY KEY) STRICT;");
    let report = migrate::run_with(&migrator, &db.path).await.unwrap();
    assert_eq!(report.previous, all_versions().last().copied());
    assert_eq!(report.applied, vec![9999]);

    let backup = report.backup.unwrap();
    assert_eq!(backup.parent().unwrap(), db.dir.path().join("backups"));
    assert!(backup.file_name().unwrap().to_string_lossy().ends_with("-before-9999.sqlite3"));
    // The backup is the database as it was: the data, and not the new table.
    let copy = db::connect(&backup).await.unwrap();
    assert_eq!(count(&copy, "miniatures").await, 1);
    assert_eq!(applied_versions(&copy).await, all_versions());
    assert_eq!(applied_versions(&db.pool).await, [all_versions(), vec![9999]].concat());
}

#[tokio::test]
async fn migration_leaving_dangling_foreign_keys_is_rolled_back() {
    let db = TestDb::new().await;
    // Foreign keys are off while migrating, so the insert itself succeeds...
    let migrator = with_extra_migration(
        "CREATE TABLE extra (id INTEGER PRIMARY KEY) STRICT;
         INSERT INTO locations (association_id, room, spot) VALUES (999, 'Nowhere', '');",
    );
    // ...but the check before commit catches it.
    let err = migrate::run_with(&migrator, &db.path).await.unwrap_err();
    assert!(matches!(err, migrate::MigrateError::ForeignKeys { version: 9999, .. }), "{err}");
    assert_eq!(count(&db.pool, "locations").await, 0);
    assert_eq!(applied_versions(&db.pool).await, all_versions());
    let extra: bool = sqlx::query_scalar("SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE name = 'extra')")
        .fetch_one(&db.pool)
        .await
        .unwrap();
    assert!(!extra);
}

#[tokio::test]
async fn edited_migration_is_refused() {
    let db = TestDb::new().await;
    let mut migrations: Vec<Migration> = migrate::MIGRATOR.iter().cloned().collect();
    migrations[0] = Migration::new(
        1,
        migrations[0].description.clone(),
        MigrationType::Simple,
        AssertSqlSafe("SELECT 1;").into_sql_str(),
        false,
    );
    let err = migrate::run_with(&Migrator::with_migrations(migrations), &db.path).await.unwrap_err();
    assert!(matches!(err, migrate::MigrateError::ChecksumMismatch(1)), "{err}");
}

// --- migration 0002: password login ------------------------------------------------

#[tokio::test]
async fn password_login_migration_keeps_every_user() {
    // A production-like database: Alembic-built, with users (one deleted), borrowings
    // pointing at them, then upgraded by `inventory migrate`.
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("inventory.sqlite3");
    let pool = alembic_database(&path, "7b1fd3535193").await;
    seed(&pool).await;
    sqlx::raw_sql(
        "INSERT INTO users (discord_id, username, display_name, is_admin) VALUES ('200', 'plain', 'Plain', 0);
         INSERT INTO users (discord_id, username, is_admin) VALUES ('300', 'gone', 0);
         DELETE FROM users WHERE discord_id = '300';
         INSERT INTO borrowings (association_id, borrower_id, item_id, item_type, action, date)
             VALUES (1, 2, 1, 'miniature', 'borrow', '2026-01-01 10:00:00.000000');",
    )
    .execute(&pool)
    .await
    .unwrap();
    let users_before: Vec<(i64, String, String, Option<String>, i64)> =
        sqlx::query_as("SELECT id, discord_id, username, display_name, is_admin FROM users ORDER BY id")
            .fetch_all(&pool)
            .await
            .unwrap();
    pool.close().await;

    let report = migrate::run(&path).await.unwrap();
    assert!(report.baselined);
    assert_eq!(report.applied, vec![2, 3]);
    assert!(report.backup.is_some(), "an upgrade of a real database is backed up first");

    let pool = db::connect(&path).await.unwrap();
    let users_after: Vec<(i64, String, String, Option<String>, i64)> =
        sqlx::query_as("SELECT id, discord_id, username, display_name, is_admin FROM users ORDER BY id")
            .fetch_all(&pool)
            .await
            .unwrap();
    assert_eq!(users_after, users_before);
    let borrower: i64 = sqlx::query_scalar("SELECT borrower_id FROM borrowings").fetch_one(&pool).await.unwrap();
    assert_eq!(borrower, 2);
    let violations = sqlx::query("PRAGMA foreign_key_check").fetch_all(&pool).await.unwrap();
    assert!(violations.is_empty());
    // Alembic's bookkeeping is gone (migration 0003).
    let alembic: bool =
        sqlx::query_scalar("SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE name = 'alembic_version')")
            .fetch_one(&pool)
            .await
            .unwrap();
    assert!(!alembic);

    // The deleted user's id (3) is still never handed out again.
    let next: i64 = sqlx::query_scalar(
        "INSERT INTO users (username, is_admin, login, password_hash) VALUES ('new', 0, 'new', 'h') RETURNING id",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(next, 4);
}

#[tokio::test]
async fn users_need_a_way_in_and_unique_logins() {
    let db = TestDb::new().await;
    // No Discord id and no password: refused.
    let err = sqlx::query("INSERT INTO users (username, is_admin) VALUES ('nobody', 0)").execute(&db.pool).await;
    assert!(err.unwrap_err().to_string().contains("ck_users_has_credentials"));
    sqlx::query("INSERT INTO users (username, is_admin, login, password_hash) VALUES ('Bob', 0, 'Bob', 'h')")
        .execute(&db.pool)
        .await
        .unwrap();
    // Logins are unique whatever the letter case; Discord-only users may share none.
    let clash =
        sqlx::query("INSERT INTO users (username, is_admin, login, password_hash) VALUES ('bob', 0, 'BOB', 'h')")
            .execute(&db.pool)
            .await;
    assert!(clash.unwrap_err().to_string().contains("UNIQUE constraint failed: users.login"));
    sqlx::raw_sql(
        "INSERT INTO users (discord_id, username, is_admin) VALUES ('1', 'a', 0);
         INSERT INTO users (discord_id, username, is_admin) VALUES ('2', 'a', 0);",
    )
    .execute(&db.pool)
    .await
    .unwrap();
}
