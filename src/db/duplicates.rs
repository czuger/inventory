//! "These two items may be the same" links. Undirected: always query both ends.

use sqlx::SqlitePool;

use crate::kinds::ItemKind;

#[derive(Debug, Clone)]
pub struct DuplicateLink {
    pub id: i64,
    pub item1_id: i64,
    pub item1_type: String,
    pub item2_id: i64,
    pub item2_type: String,
}

impl DuplicateLink {
    /// The end that is not `(item_type, item_id)`.
    pub fn other_end(&self, item_type: &str, item_id: i64) -> (&str, i64) {
        if self.item1_id == item_id && self.item1_type == item_type {
            (&self.item2_type, self.item2_id)
        } else {
            (&self.item1_type, self.item1_id)
        }
    }
}

/// The association's links with this item at either end.
pub async fn for_item(
    pool: &SqlitePool,
    association_id: i64,
    kind: ItemKind,
    item_id: i64,
) -> Result<Vec<DuplicateLink>, sqlx::Error> {
    let item_type = kind.item_type();
    sqlx::query_as!(
        DuplicateLink,
        "SELECT id, item1_id, item1_type, item2_id, item2_type FROM duplicate_links
         WHERE association_id = ?
           AND ((item1_id = ? AND item1_type = ?) OR (item2_id = ? AND item2_type = ?))
         ORDER BY id",
        association_id,
        item_id,
        item_type,
        item_id,
        item_type
    )
    .fetch_all(pool)
    .await
}

/// Whether the two items are already linked, in either direction.
pub async fn exists(
    pool: &SqlitePool,
    association_id: i64,
    (a_type, a_id): (&str, i64),
    (b_type, b_id): (&str, i64),
) -> Result<bool, sqlx::Error> {
    sqlx::query_scalar!(
        r#"SELECT EXISTS (
             SELECT 1 FROM duplicate_links WHERE association_id = ?
               AND ((item1_id = ? AND item1_type = ? AND item2_id = ? AND item2_type = ?)
                 OR (item1_id = ? AND item1_type = ? AND item2_id = ? AND item2_type = ?))
           ) AS "linked: bool""#,
        association_id,
        a_id,
        a_type,
        b_id,
        b_type,
        b_id,
        b_type,
        a_id,
        a_type
    )
    .fetch_one(pool)
    .await
}

pub async fn insert(
    pool: &SqlitePool,
    association_id: i64,
    (a_type, a_id): (&str, i64),
    (b_type, b_id): (&str, i64),
) -> Result<(), sqlx::Error> {
    let created_at = super::types::utcnow_text();
    sqlx::query!(
        "INSERT INTO duplicate_links (association_id, item1_id, item1_type, item2_id, item2_type, created_at)
         VALUES (?, ?, ?, ?, ?, ?)",
        association_id,
        a_id,
        a_type,
        b_id,
        b_type,
        created_at
    )
    .execute(pool)
    .await?;
    Ok(())
}

/// Deletes the association's link `id`; `false` if there was none.
pub async fn delete(pool: &SqlitePool, association_id: i64, id: i64) -> Result<bool, sqlx::Error> {
    let result = sqlx::query!("DELETE FROM duplicate_links WHERE id = ? AND association_id = ?", id, association_id)
        .execute(pool)
        .await?;
    Ok(result.rows_affected() > 0)
}
