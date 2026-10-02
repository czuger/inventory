use sqlx::SqlitePool;

use super::models::User;

pub async fn find(pool: &SqlitePool, id: i64) -> Result<Option<User>, sqlx::Error> {
    sqlx::query_as!(
        User,
        r#"SELECT id, discord_id, username, display_name, is_admin AS "is_admin: bool", login, password_hash
           FROM users WHERE id = ?"#,
        id
    )
    .fetch_optional(pool)
    .await
}

pub async fn find_by_discord_id(pool: &SqlitePool, discord_id: &str) -> Result<Option<User>, sqlx::Error> {
    sqlx::query_as!(
        User,
        r#"SELECT id, discord_id, username, display_name, is_admin AS "is_admin: bool", login, password_hash
           FROM users WHERE discord_id = ?"#,
        discord_id
    )
    .fetch_optional(pool)
    .await
}

/// The user who logs in as `login`, whatever the letter case (the column is NOCASE).
pub async fn find_by_login(pool: &SqlitePool, login: &str) -> Result<Option<User>, sqlx::Error> {
    sqlx::query_as!(
        User,
        r#"SELECT id, discord_id, username, display_name, is_admin AS "is_admin: bool", login, password_hash
           FROM users WHERE login = ?"#,
        login
    )
    .fetch_optional(pool)
    .await
}

/// Every user with this display name (the command line looks users up by it).
pub async fn find_by_username(pool: &SqlitePool, username: &str) -> Result<Vec<User>, sqlx::Error> {
    sqlx::query_as!(
        User,
        r#"SELECT id, discord_id, username, display_name, is_admin AS "is_admin: bool", login, password_hash
           FROM users WHERE username = ? ORDER BY id"#,
        username
    )
    .fetch_all(pool)
    .await
}

/// A user's first Discord login: never an admin (that is granted from the command line).
pub async fn insert_discord_user(
    pool: &SqlitePool,
    discord_id: &str,
    username: &str,
    display_name: Option<&str>,
) -> Result<i64, sqlx::Error> {
    sqlx::query_scalar!(
        r#"INSERT INTO users (discord_id, username, display_name, is_admin) VALUES (?, ?, ?, 0) RETURNING id AS "id!""#,
        discord_id,
        username,
        display_name
    )
    .fetch_one(pool)
    .await
}

/// A sign-up: the chosen name is both the login and the display name. Not an admin.
pub async fn insert_password_user(pool: &SqlitePool, login: &str, password_hash: &str) -> Result<i64, sqlx::Error> {
    sqlx::query_scalar!(
        r#"INSERT INTO users (username, is_admin, login, password_hash) VALUES (?, 0, ?, ?) RETURNING id AS "id!""#,
        login,
        login,
        password_hash
    )
    .fetch_one(pool)
    .await
}

pub async fn update_names(
    pool: &SqlitePool,
    id: i64,
    username: &str,
    display_name: Option<&str>,
) -> Result<(), sqlx::Error> {
    sqlx::query!("UPDATE users SET username = ?, display_name = ? WHERE id = ?", username, display_name, id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn set_password(pool: &SqlitePool, id: i64, login: &str, password_hash: &str) -> Result<(), sqlx::Error> {
    sqlx::query!("UPDATE users SET login = ?, password_hash = ? WHERE id = ?", login, password_hash, id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn set_admin(pool: &SqlitePool, id: i64, is_admin: bool) -> Result<(), sqlx::Error> {
    sqlx::query!("UPDATE users SET is_admin = ? WHERE id = ?", is_admin, id).execute(pool).await?;
    Ok(())
}
