//! `inventory migrate`: back up the database, then apply the pending migrations.
//!
//! What `python -m inventory.db.migrate` and `alembic/env.py` did, on sqlx's migration
//! table:
//!
//! - **Baseline.** A database built by Alembic already has the schema of migration 0001.
//!   When it is at Alembic's only revision and sqlx has recorded nothing yet, 0001 is
//!   recorded as applied without running. Any other Alembic revision is refused: its
//!   schema is unknown here.
//! - **Backup** with `VACUUM INTO` before applying anything to a database that already
//!   had a schema: a rollback never downgrades, so this copy is the way back. It is
//!   consistent while the app writes, and includes what is still in the -wal file.
//! - **Foreign keys off** for the whole run. SQLite cannot ALTER most of a table, so a
//!   migration rebuilds it (copy, drop, rename), and dropping a table other rows point at
//!   fails with foreign keys on. The check they would have made runs before each commit
//!   instead (`PRAGMA foreign_key_check`), and a violation rolls the migration back.
//!
//! Each migration and its bookkeeping row commit together, in the format sqlx's own
//! migrator writes, so `sqlx migrate info` reads the table as usual.

use std::path::{Path, PathBuf};
use std::time::Instant;

use sqlx::migrate::{Migrate, MigrationType, Migrator};
use sqlx::{Connection, Executor, Row, SqliteConnection};

use crate::db;

pub static MIGRATOR: Migrator = sqlx::migrate!();

const TABLE: &str = "_sqlx_migrations";

/// The Alembic revision whose schema is migration 0001.
const ALEMBIC_HEAD: &str = "7b1fd3535193";
const ALEMBIC_HEAD_VERSION: i64 = 1;

#[derive(Debug, thiserror::Error)]
pub enum MigrateError {
    #[error(transparent)]
    Database(#[from] sqlx::Error),
    #[error(transparent)]
    Migrate(#[from] sqlx::migrate::MigrateError),
    #[error("cannot create the backup directory {path}: {source}")]
    BackupDir { path: PathBuf, source: std::io::Error },
    #[error("the database is at Alembic revision {0}, which no migration here corresponds to")]
    UnknownAlembicRevision(String),
    #[error("migration {0} failed partway on a previous run; restore a backup")]
    Dirty(i64),
    #[error("migration {0} is recorded as applied but does not exist here")]
    UnknownApplied(i64),
    #[error("migration {0} was changed after it was applied (checksum mismatch)")]
    ChecksumMismatch(i64),
    #[error("migration {version} left dangling foreign keys, rolled back: {violations:?}")]
    ForeignKeys { version: i64, violations: Vec<String> },
}

#[derive(Debug, Default, PartialEq, Eq)]
pub struct Report {
    /// The Alembic-built schema was recorded as migration 0001.
    pub baselined: bool,
    pub backup: Option<PathBuf>,
    /// The latest version applied before this run, if any.
    pub previous: Option<i64>,
    pub applied: Vec<i64>,
}

pub async fn run(path: &Path) -> Result<Report, MigrateError> {
    run_with(&MIGRATOR, path).await
}

pub async fn run_with(migrator: &Migrator, path: &Path) -> Result<Report, MigrateError> {
    let mut conn = SqliteConnection::connect_with(&db::connect_options(path).foreign_keys(false)).await?;
    let result = migrate(migrator, &mut conn, path).await;
    conn.close().await?;
    result
}

async fn migrate(migrator: &Migrator, conn: &mut SqliteConnection, path: &Path) -> Result<Report, MigrateError> {
    let mut report = Report::default();

    // Checked before anything is written, so a refused database is left untouched.
    let alembic_revision = alembic_revision(conn).await?;
    if let Some(revision) = &alembic_revision
        && revision != ALEMBIC_HEAD
    {
        return Err(MigrateError::UnknownAlembicRevision(revision.clone()));
    }

    conn.ensure_migrations_table(TABLE).await?;
    if let Some(version) = conn.dirty_version(TABLE).await? {
        return Err(MigrateError::Dirty(version));
    }

    let mut applied = conn.list_applied_migrations(TABLE).await?;
    if applied.is_empty()
        && alembic_revision.is_some()
        && let Some(baseline) = migrator.iter().find(|m| m.version == ALEMBIC_HEAD_VERSION)
    {
        conn.skip(TABLE, baseline).await?;
        report.baselined = true;
        applied = conn.list_applied_migrations(TABLE).await?;
    }

    for done in &applied {
        let migration = migrator
            .iter()
            .find(|m| m.version == done.version && !m.migration_type.is_down_migration())
            .ok_or(MigrateError::UnknownApplied(done.version))?;
        if migration.checksum != done.checksum {
            return Err(MigrateError::ChecksumMismatch(done.version));
        }
    }
    report.previous = applied.iter().map(|m| m.version).max();

    let pending: Vec<_> = migrator
        .iter()
        .filter(|m| matches!(m.migration_type, MigrationType::Simple | MigrationType::ReversibleUp))
        .filter(|m| applied.iter().all(|done| done.version != m.version))
        .collect();
    let Some(head) = pending.last().map(|m| m.version) else {
        return Ok(report);
    };

    if report.previous.is_some() {
        report.backup = Some(backup(conn, path, head).await?);
    }

    for migration in pending {
        let start = Instant::now();
        let mut tx = conn.begin().await?;
        tx.execute(migration.sql.clone())
            .await
            .map_err(|e| sqlx::migrate::MigrateError::ExecuteMigration(e, migration.version))?;

        let violations: Vec<String> = sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(&mut *tx)
            .await?
            .iter()
            .map(|row| {
                let table: String = row.get(0);
                let rowid: Option<i64> = row.get(1);
                let parent: String = row.get(2);
                format!("{table} rowid {} -> {parent}", rowid.map_or_else(|| "?".to_owned(), |id| id.to_string()))
            })
            .collect();
        if !violations.is_empty() {
            return Err(MigrateError::ForeignKeys { version: migration.version, violations });
        }

        sqlx::query(
            "INSERT INTO _sqlx_migrations ( version, description, success, checksum, execution_time ) \
             VALUES ( ?1, ?2, TRUE, ?3, -1 )",
        )
        .bind(migration.version)
        .bind(&*migration.description)
        .bind(&*migration.checksum)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;

        #[allow(clippy::cast_possible_truncation)]
        sqlx::query("UPDATE _sqlx_migrations SET execution_time = ?1 WHERE version = ?2")
            .bind(start.elapsed().as_nanos() as i64)
            .bind(migration.version)
            .execute(&mut *conn)
            .await?;
        report.applied.push(migration.version);
    }
    Ok(report)
}

async fn alembic_revision(conn: &mut SqliteConnection) -> Result<Option<String>, sqlx::Error> {
    let has_table: bool = sqlx::query_scalar(
        "SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version')",
    )
    .fetch_one(&mut *conn)
    .await?;
    if !has_table {
        return Ok(None);
    }
    sqlx::query_scalar("SELECT version_num FROM alembic_version").fetch_optional(&mut *conn).await
}

/// `<db dir>/backups/<UTC timestamp>-before-<version>.sqlite3`, beside the database (so
/// in the server's `data/db/backups/`).
async fn backup(conn: &mut SqliteConnection, path: &Path, head: i64) -> Result<PathBuf, MigrateError> {
    let dir = path.parent().unwrap_or_else(|| Path::new(".")).join("backups");
    std::fs::create_dir_all(&dir).map_err(|source| MigrateError::BackupDir { path: dir.clone(), source })?;
    let file = dir.join(format!("{}-before-{head:04}.sqlite3", chrono::Utc::now().format("%Y%m%d-%H%M%S")));
    sqlx::query("VACUUM INTO ?").bind(file.to_string_lossy().into_owned()).execute(&mut *conn).await?;
    Ok(file)
}
