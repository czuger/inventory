//! MongoDB ObjectId -> integer id of every item imported from MongoDB. Stickers printed
//! before the move encode `/<slug>/<items>/<ObjectId>` in their QR code.

use sqlx::SqlitePool;

use crate::kinds::ItemKind;

/// The new id of the `kind` item that had this ObjectId (`resolve_legacy_id`).
pub async fn resolve(pool: &SqlitePool, kind: ItemKind, object_id: &str) -> Result<Option<i64>, sqlx::Error> {
    let row = sqlx::query!("SELECT item_type, item_id FROM legacy_object_ids WHERE object_id = ?", object_id)
        .fetch_optional(pool)
        .await?;
    Ok(row.filter(|row| row.item_type == kind.item_type()).map(|row| row.item_id))
}

/// `[0-9a-f]{24}`: the `objectid` URL converter.
pub fn is_object_id(segment: &str) -> bool {
    segment.len() == 24 && segment.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
