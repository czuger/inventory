//! The eight item tables, through one set of functions.
//!
//! These are the only queries built at runtime rather than checked by sqlx's macros: the
//! macros need literal SQL, so eight tables would mean eight copies of each query. One
//! spec per type drives them instead, and the integration tests run every one of them
//! against every table (`tests/items.rs`).

use serde::Serialize;
use sqlx::sqlite::SqliteRow;
use sqlx::{AssertSqlSafe, Row, SqliteExecutor, SqlitePool};

use super::models::{Game, Location};
use super::types::{images_from_json, images_to_json};
use crate::kinds::ItemKind;

/// An item as the templates see it: the shared columns, its location and game loaded
/// (`lazy='joined'` in the models), and the type's own fields flattened in.
#[derive(Debug, Clone, Serialize)]
pub struct Item {
    #[serde(skip)]
    pub kind: ItemKind,
    pub id: i64,
    pub association_id: i64,
    pub category: String,
    pub quantity: i64,
    pub borrowing_count: i64,
    pub sticker_printed: bool,
    pub location: Location,
    pub images: Vec<String>,
    #[serde(flatten)]
    pub fields: ItemFields,
}

#[derive(Debug, Clone, Serialize)]
#[serde(untagged)]
pub enum ItemFields {
    Miniature { r#type: String, game: Game, scale: String },
    Terrain { r#type: String, game: Game, scale: String, theater: Option<String> },
    Tablecloth { r#type: String, material: Option<String>, game: Game, size: String, remarks: Option<String> },
    Rulebook { name: String, game: Game, supplement: bool },
    BoardGame { name: String, universe: Option<String> },
    Book { name: String, universe: Option<String>, period: Option<String> },
    Equipment { r#type: String },
    Consumable { r#type: String, unit: Option<String> },
}

impl Item {
    /// The upload folder name: `category.lower().replace(' ', '_')`, so it follows the
    /// item's *category*, not its type.
    pub fn category_snake(&self) -> String {
        self.category.to_lowercase().replace(' ', "_")
    }

    pub fn game(&self) -> Option<&Game> {
        match &self.fields {
            ItemFields::Miniature { game, .. }
            | ItemFields::Terrain { game, .. }
            | ItemFields::Tablecloth { game, .. }
            | ItemFields::Rulebook { game, .. } => Some(game),
            _ => None,
        }
    }
}

/// The type's own columns, in table order (`game_id` stands for the joined game).
fn own_columns(kind: ItemKind) -> &'static [&'static str] {
    match kind {
        ItemKind::Miniature => &["type", "game_id", "scale"],
        ItemKind::Terrain => &["type", "game_id", "scale", "theater"],
        ItemKind::Tablecloth => &["type", "material", "game_id", "size", "remarks"],
        ItemKind::Rulebook => &["name", "game_id", "supplement"],
        ItemKind::BoardGame => &["name", "universe"],
        ItemKind::Book => &["name", "universe", "period"],
        ItemKind::Equipment => &["type"],
        ItemKind::Consumable => &["type", "unit"],
    }
}

pub fn has_game(kind: ItemKind) -> bool {
    own_columns(kind).contains(&"game_id")
}

fn select_sql(kind: ItemKind, filter: &str) -> String {
    let own: String = own_columns(kind).iter().map(|column| format!(", i.{column}")).collect();
    let (game_column, game_join) =
        if has_game(kind) { (", g.name AS game_name", " JOIN games g ON g.id = i.game_id") } else { ("", "") };
    format!(
        "SELECT i.id, i.association_id, i.category, i.quantity, i.borrowing_count, i.sticker_printed, i.images, \
         l.id AS location_id, l.association_id AS location_association_id, l.room AS location_room, \
         l.spot AS location_spot{own}{game_column} \
         FROM {table} i JOIN locations l ON l.id = i.location_id{game_join} \
         WHERE {filter} ORDER BY i.id",
        table = kind.table()
    )
}

fn from_row(kind: ItemKind, row: &SqliteRow) -> Result<Item, sqlx::Error> {
    let game =
        || -> Result<Game, sqlx::Error> { Ok(Game { id: row.try_get("game_id")?, name: row.try_get("game_name")? }) };
    let text = |column: &str| row.try_get::<String, _>(column);
    let opt = |column: &str| row.try_get::<Option<String>, _>(column);
    let fields = match kind {
        ItemKind::Miniature => ItemFields::Miniature { r#type: text("type")?, game: game()?, scale: text("scale")? },
        ItemKind::Terrain => ItemFields::Terrain {
            r#type: text("type")?,
            game: game()?,
            scale: text("scale")?,
            theater: opt("theater")?,
        },
        ItemKind::Tablecloth => ItemFields::Tablecloth {
            r#type: text("type")?,
            material: opt("material")?,
            game: game()?,
            size: text("size")?,
            remarks: opt("remarks")?,
        },
        ItemKind::Rulebook => {
            ItemFields::Rulebook { name: text("name")?, game: game()?, supplement: row.try_get("supplement")? }
        }
        ItemKind::BoardGame => ItemFields::BoardGame { name: text("name")?, universe: opt("universe")? },
        ItemKind::Book => ItemFields::Book { name: text("name")?, universe: opt("universe")?, period: opt("period")? },
        ItemKind::Equipment => ItemFields::Equipment { r#type: text("type")? },
        ItemKind::Consumable => ItemFields::Consumable { r#type: text("type")?, unit: opt("unit")? },
    };
    let images: String = row.try_get("images")?;
    Ok(Item {
        kind,
        id: row.try_get("id")?,
        association_id: row.try_get("association_id")?,
        category: row.try_get("category")?,
        quantity: row.try_get("quantity")?,
        borrowing_count: row.try_get("borrowing_count")?,
        sticker_printed: row.try_get("sticker_printed")?,
        location: Location {
            id: row.try_get("location_id")?,
            association_id: row.try_get("location_association_id")?,
            room: row.try_get("location_room")?,
            spot: row.try_get("location_spot")?,
        },
        images: images_from_json(&images).map_err(|err| sqlx::Error::Decode(Box::new(err)))?,
        fields,
    })
}

/// Every item of a type in one association, by id.
pub async fn list(pool: &SqlitePool, kind: ItemKind, association_id: i64) -> Result<Vec<Item>, sqlx::Error> {
    sqlx::query(AssertSqlSafe(select_sql(kind, "i.association_id = ?")))
        .bind(association_id)
        .fetch_all(pool)
        .await?
        .iter()
        .map(|row| from_row(kind, row))
        .collect()
}

/// An item by id, whatever its association: callers scope it (`get_or_404`).
pub async fn get(pool: &SqlitePool, kind: ItemKind, id: i64) -> Result<Option<Item>, sqlx::Error> {
    sqlx::query(AssertSqlSafe(select_sql(kind, "i.id = ?")))
        .bind(id)
        .fetch_optional(pool)
        .await?
        .map(|row| from_row(kind, &row))
        .transpose()
}

/// A value for one of the type's own columns.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Text(String),
    OptText(Option<String>),
    Int(i64),
    Bool(bool),
}

/// What a create or edit form sets.
#[derive(Debug, Clone)]
pub struct Values {
    pub category: String,
    pub quantity: i64,
    pub location_id: i64,
    /// `(column, value)` for the type's own columns.
    pub own: Vec<(&'static str, Value)>,
    /// Only an edit sets it; a new item starts unprinted.
    pub sticker_printed: Option<bool>,
}

fn bind_value<'q>(
    query: sqlx::query::Query<'q, sqlx::Sqlite, sqlx::sqlite::SqliteArguments>,
    value: &Value,
) -> sqlx::query::Query<'q, sqlx::Sqlite, sqlx::sqlite::SqliteArguments> {
    match value {
        Value::Text(text) => query.bind(text.clone()),
        Value::OptText(text) => query.bind(text.clone()),
        Value::Int(int) => query.bind(*int),
        Value::Bool(flag) => query.bind(*flag),
    }
}

/// Inserts with the model defaults SQLAlchemy applied: nothing borrowed, no sticker
/// printed, no photos.
pub async fn insert(
    pool: &SqlitePool,
    kind: ItemKind,
    association_id: i64,
    values: &Values,
) -> Result<i64, sqlx::Error> {
    let own: Vec<&str> = values.own.iter().map(|(column, _)| *column).collect();
    let sql = format!(
        "INSERT INTO {table} (association_id, category, {own_columns}{sep}quantity, borrowing_count, sticker_printed, \
         location_id, images) VALUES (?, ?, {own_marks}{sep}?, 0, 0, ?, ?) RETURNING id",
        table = kind.table(),
        own_columns = own.join(", "),
        own_marks = vec!["?"; own.len()].join(", "),
        sep = if own.is_empty() { "" } else { ", " },
    );
    let mut query = sqlx::query(AssertSqlSafe(sql)).bind(association_id).bind(values.category.clone());
    for (_, value) in &values.own {
        query = bind_value(query, value);
    }
    let row = query.bind(values.quantity).bind(values.location_id).bind(images_to_json(&[])).fetch_one(pool).await?;
    row.try_get("id")
}

pub async fn update(pool: &SqlitePool, kind: ItemKind, id: i64, values: &Values) -> Result<(), sqlx::Error> {
    let mut sets = vec!["category = ?".to_owned()];
    sets.extend(values.own.iter().map(|(column, _)| format!("{column} = ?")));
    sets.push("quantity = ?".to_owned());
    sets.push("location_id = ?".to_owned());
    if values.sticker_printed.is_some() {
        sets.push("sticker_printed = ?".to_owned());
    }
    let sql = format!("UPDATE {} SET {} WHERE id = ?", kind.table(), sets.join(", "));
    let mut query = sqlx::query(AssertSqlSafe(sql)).bind(values.category.clone());
    for (_, value) in &values.own {
        query = bind_value(query, value);
    }
    query = query.bind(values.quantity).bind(values.location_id);
    if let Some(printed) = values.sticker_printed {
        query = query.bind(printed);
    }
    query.bind(id).execute(pool).await?;
    Ok(())
}

pub async fn delete(pool: &SqlitePool, kind: ItemKind, id: i64) -> Result<(), sqlx::Error> {
    sqlx::query(AssertSqlSafe(format!("DELETE FROM {} WHERE id = ?", kind.table()))).bind(id).execute(pool).await?;
    Ok(())
}

pub async fn set_images(pool: &SqlitePool, kind: ItemKind, id: i64, images: &[String]) -> Result<(), sqlx::Error> {
    sqlx::query(AssertSqlSafe(format!("UPDATE {} SET images = ? WHERE id = ?", kind.table())))
        .bind(images_to_json(images))
        .bind(id)
        .execute(pool)
        .await?;
    Ok(())
}

/// Keeps the denormalized `borrowing_count` in step with a borrow (+1) or a return (-1,
/// never below zero). Done in SQL rather than read-modify-write, so two concurrent
/// requests cannot lose an update.
pub async fn adjust_borrowing_count<'e>(
    executor: impl SqliteExecutor<'e>,
    kind: ItemKind,
    id: i64,
    borrowed: bool,
) -> Result<(), sqlx::Error> {
    let new_count = if borrowed { "borrowing_count + 1" } else { "MAX(0, borrowing_count - 1)" };
    let sql = format!("UPDATE {} SET borrowing_count = {new_count} WHERE id = ?", kind.table());
    sqlx::query(AssertSqlSafe(sql)).bind(id).execute(executor).await?;
    Ok(())
}

/// Flags the items whose stickers were just generated.
pub async fn mark_printed<'e>(
    executor: impl SqliteExecutor<'e>,
    kind: ItemKind,
    ids: &[i64],
) -> Result<(), sqlx::Error> {
    if ids.is_empty() {
        return Ok(());
    }
    let marks = vec!["?"; ids.len()].join(", ");
    let mut query =
        sqlx::query(AssertSqlSafe(format!("UPDATE {} SET sticker_printed = 1 WHERE id IN ({marks})", kind.table())));
    for id in ids {
        query = query.bind(*id);
    }
    query.execute(executor).await?;
    Ok(())
}
