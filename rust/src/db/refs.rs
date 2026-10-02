//! The reference rows items point at: associations, games, locations.

use sqlx::SqlitePool;

use super::models::{Association, Game, Location};

pub async fn association_by_slug(pool: &SqlitePool, slug: &str) -> Result<Option<Association>, sqlx::Error> {
    sqlx::query_as!(Association, "SELECT id, name, slug FROM associations WHERE slug = ?", slug)
        .fetch_optional(pool)
        .await
}

/// Every game, by name: games are shared by all associations.
pub async fn games(pool: &SqlitePool) -> Result<Vec<Game>, sqlx::Error> {
    sqlx::query_as!(Game, "SELECT id, name FROM games ORDER BY name").fetch_all(pool).await
}

pub async fn game(pool: &SqlitePool, id: i64) -> Result<Option<Game>, sqlx::Error> {
    sqlx::query_as!(Game, "SELECT id, name FROM games WHERE id = ?", id).fetch_optional(pool).await
}

/// An association's locations, in insertion order (Python issued no ORDER BY).
pub async fn locations(pool: &SqlitePool, association_id: i64) -> Result<Vec<Location>, sqlx::Error> {
    sqlx::query_as!(
        Location,
        "SELECT id, association_id, room, spot FROM locations WHERE association_id = ? ORDER BY id",
        association_id
    )
    .fetch_all(pool)
    .await
}

pub async fn location(pool: &SqlitePool, id: i64) -> Result<Option<Location>, sqlx::Error> {
    sqlx::query_as!(Location, "SELECT id, association_id, room, spot FROM locations WHERE id = ?", id)
        .fetch_optional(pool)
        .await
}

/// The association `/` sends visitors to: the oldest.
pub async fn first_association_slug(pool: &SqlitePool) -> Result<Option<String>, sqlx::Error> {
    sqlx::query_scalar!("SELECT slug FROM associations ORDER BY id LIMIT 1").fetch_optional(pool).await
}
