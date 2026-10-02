//! Rows as the app uses them. Field names are the column names, so templates can use
//! them as the Jinja templates did (`current_user.username`, `item.location.room`).

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct User {
    pub id: i64,
    /// `None` for an account made on the sign-up form.
    pub discord_id: Option<String>,
    /// The display name: Discord's username, or the name chosen at sign-up.
    pub username: String,
    pub display_name: Option<String>,
    pub is_admin: bool,
    /// The name typed on the login form, if the user has a password.
    pub login: Option<String>,
    /// argon2id, as a PHC string. Never sent to a template.
    #[serde(skip)]
    pub password_hash: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Association {
    pub id: i64,
    pub name: String,
    pub slug: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Game {
    pub id: i64,
    pub name: String,
}

/// `spot` is `''`, never NULL, when there is none (see `inventory/db/location.py`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Location {
    pub id: i64,
    pub association_id: i64,
    pub room: String,
    pub spot: String,
}

impl Location {
    /// `_loc()` in `item_labels.py`: `Room – Spot`, or just the room.
    pub fn label(&self) -> String {
        if self.spot.is_empty() { self.room.clone() } else { format!("{} – {}", self.room, self.spot) }
    }
}
