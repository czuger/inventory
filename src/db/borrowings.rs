//! Borrow/return events. They are the record; an item's status is its latest event.

use sqlx::{SqliteExecutor, SqlitePool};

use super::models::User;
use super::types::utcnow_text;
use crate::kinds::ItemKind;

#[derive(Debug, Clone)]
pub struct Borrowing {
    pub id: i64,
    pub action: String,
    /// As stored: SQLAlchemy's `YYYY-MM-DD HH:MM:SS.ffffff` (see `db::types`).
    pub date: String,
    pub borrower: User,
}

/// An item's events, latest first; `id` breaks ties within the same microsecond. Not
/// scoped to the association, as in Python: the item is.
pub async fn history(pool: &SqlitePool, kind: ItemKind, item_id: i64) -> Result<Vec<Borrowing>, sqlx::Error> {
    let item_type = kind.item_type();
    let rows = sqlx::query!(
        r#"SELECT b.id, b.action, b.date, u.id AS borrower_id, u.discord_id, u.username, u.display_name,
                  u.is_admin AS "is_admin: bool", u.login, u.password_hash
           FROM borrowings b JOIN users u ON u.id = b.borrower_id
           WHERE b.item_id = ? AND b.item_type = ?
           ORDER BY b.date DESC, b.id DESC"#,
        item_id,
        item_type
    )
    .fetch_all(pool)
    .await?;
    Ok(rows
        .into_iter()
        .map(|row| Borrowing {
            id: row.id,
            action: row.action,
            date: row.date,
            borrower: User {
                id: row.borrower_id,
                discord_id: row.discord_id,
                username: row.username,
                display_name: row.display_name,
                is_admin: row.is_admin,
                login: row.login,
                password_hash: row.password_hash,
            },
        })
        .collect())
}

/// Records a `borrow` or `return` event, dated now.
pub async fn record<'e>(
    executor: impl SqliteExecutor<'e>,
    association_id: i64,
    borrower_id: i64,
    kind: ItemKind,
    item_id: i64,
    action: &str,
) -> Result<(), sqlx::Error> {
    let item_type = kind.item_type();
    let date = utcnow_text();
    sqlx::query!(
        "INSERT INTO borrowings (association_id, borrower_id, item_id, item_type, action, date) VALUES (?, ?, ?, ?, ?, ?)",
        association_id,
        borrower_id,
        item_id,
        item_type,
        action,
        date
    )
    .execute(executor)
    .await?;
    Ok(())
}
