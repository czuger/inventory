//! The SQLite connection settings every connection gets, the app's and `migrate`'s alike
//! (what `inventory/db/base.py` does with its `Engine` connect listener).

pub mod borrowings;
pub mod duplicates;
pub mod items;
pub mod legacy;
pub mod models;
pub mod refs;
pub mod types;
pub mod users;

use std::path::Path;
use std::time::Duration;

use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePool, SqlitePoolOptions, SqliteSynchronous};

/// - `journal_mode=WAL`: readers and the writer no longer block each other.
/// - `synchronous=NORMAL`: the recommended setting with WAL; only a power loss can drop
///   the last commits, and it never corrupts the database.
/// - `foreign_keys=ON`: SQLite ships with them off, per connection.
/// - `busy_timeout=5s`: a write that finds the database locked waits instead of failing.
///
/// A missing database file is created, as sqlite3 does in Python.
pub fn connect_options(path: &Path) -> SqliteConnectOptions {
    SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Normal)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5))
}

pub async fn connect(path: &Path) -> Result<SqlitePool, sqlx::Error> {
    SqlitePoolOptions::new().max_connections(8).connect_with(connect_options(path)).await
}
