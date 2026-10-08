//! `inventory seed`: fills a fresh database with the club inventory.
//!
//! The data is `misc/grognards_seed.json`, built once from the v2 extraction of the club
//! workbook (`misc/inventory_xlsx_extraction_report.md`) and embedded in the binary, so the
//! server needs nothing beside it. The file is checked as a whole before anything is
//! written, everything goes in one transaction, and a database that already holds an
//! association or a game is refused: seeding never deletes or merges.

use std::collections::{HashMap, HashSet};

use serde::Deserialize;
use sqlx::SqlitePool;

use crate::db::items::{self, Value, Values};
use crate::kinds::{ItemKind, SCALES, TABLECLOTH_MATERIALS, TABLECLOTH_SIZES};

/// The Grognards' inventory, as `inventory seed` loads it by default.
pub const GROGNARDS: &str = include_str!("../misc/grognards_seed.json");

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedFile {
    #[serde(rename = "_comment", default)]
    pub comment: Option<String>,
    #[serde(rename = "_rules", default)]
    pub rules: Vec<String>,
    pub association: SeedAssociation,
    pub locations: Vec<SeedLocation>,
    pub games: Vec<String>,
    pub items: Vec<SeedItem>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedAssociation {
    pub name: String,
    pub slug: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedLocation {
    pub room: String,
    pub spot: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedItem {
    /// The sheet lines it comes from (`F1:r47`): for people, not loaded.
    pub source: Vec<String>,
    /// `ItemKind::item_type` (`board_game`).
    #[serde(rename = "type")]
    pub kind: String,
    /// The item's `name` or `type` column, whichever its table has.
    pub name: String,
    pub quantity: i64,
    /// `[room, spot]`, one of `locations`.
    pub location: [String; 2],
    #[serde(default)]
    pub fields: SeedFields,
    /// What was interpreted: for people, not loaded.
    #[serde(default)]
    pub note: Option<String>,
}

/// The type's own columns. Each type takes only its own; any other one is an error.
#[derive(Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedFields {
    pub game: Option<String>,
    pub scale: Option<String>,
    pub theater: Option<String>,
    pub material: Option<String>,
    pub size: Option<String>,
    pub remarks: Option<String>,
    pub supplement: Option<bool>,
    pub universe: Option<String>,
    pub period: Option<String>,
    pub unit: Option<String>,
}

impl SeedFields {
    fn present(&self) -> Vec<&'static str> {
        let fields = [
            ("game", self.game.is_some()),
            ("scale", self.scale.is_some()),
            ("theater", self.theater.is_some()),
            ("material", self.material.is_some()),
            ("size", self.size.is_some()),
            ("remarks", self.remarks.is_some()),
            ("supplement", self.supplement.is_some()),
            ("universe", self.universe.is_some()),
            ("period", self.period.is_some()),
            ("unit", self.unit.is_some()),
        ];
        fields.into_iter().filter(|(_, set)| *set).map(|(name, _)| name).collect()
    }
}

/// The fields each type may set; `game` is required where it is listed.
fn allowed_fields(kind: ItemKind) -> &'static [&'static str] {
    match kind {
        ItemKind::Miniature => &["game", "scale"],
        ItemKind::Terrain => &["game", "scale", "theater"],
        ItemKind::Tablecloth => &["game", "material", "size", "remarks"],
        ItemKind::Rulebook => &["game", "supplement"],
        ItemKind::BoardGame => &["universe"],
        ItemKind::Book => &["universe", "period"],
        ItemKind::Equipment => &[],
        ItemKind::Consumable => &["unit"],
    }
}

#[derive(Debug, thiserror::Error)]
pub enum SeedError {
    #[error("the seed file is not valid JSON for a seed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("the seed file has {} problem(s), nothing was written:\n  {}", .0.len(), .0.join("\n  "))]
    Invalid(Vec<String>),
    #[error(
        "the database already holds {associations} association(s) and {games} game(s); seed only fills a fresh one"
    )]
    NotEmpty { associations: i64, games: i64 },
    #[error(transparent)]
    Database(#[from] sqlx::Error),
}

#[derive(Debug, PartialEq, Eq)]
pub struct Summary {
    pub association: String,
    pub locations: usize,
    pub games: usize,
    /// Items per type, in `ItemKind::ALL` order, types with none left out.
    pub items: Vec<(ItemKind, usize)>,
}

pub fn parse(json: &str) -> Result<SeedFile, SeedError> {
    Ok(serde_json::from_str(json)?)
}

/// Every problem in the file, so that one run lists them all.
pub fn check(file: &SeedFile) -> Result<(), SeedError> {
    let mut problems = Vec::new();
    let mut places = HashSet::new();
    for location in &file.locations {
        if !places.insert((location.room.as_str(), location.spot.as_str())) {
            problems.push(format!("location {} / {} is listed twice", location.room, location.spot));
        }
    }
    let mut games = HashSet::new();
    for game in &file.games {
        if !games.insert(game.as_str()) {
            problems.push(format!("game {game:?} is listed twice"));
        }
    }
    for (index, item) in file.items.iter().enumerate() {
        let at = format!("item {index} ({} {:?})", item.source.join(", "), item.name);
        let Some(kind) = ItemKind::from_item_type(&item.kind) else {
            problems.push(format!("{at}: unknown type {:?}", item.kind));
            continue;
        };
        if item.name.trim().is_empty() {
            problems.push(format!("{at}: empty name"));
        }
        if item.quantity < 0 {
            problems.push(format!("{at}: negative quantity"));
        }
        let [room, spot] = &item.location;
        if !places.contains(&(room.as_str(), spot.as_str())) {
            problems.push(format!("{at}: location {room} / {spot} is not in locations"));
        }
        let allowed = allowed_fields(kind);
        for field in item.fields.present() {
            if !allowed.contains(&field) {
                problems.push(format!("{at}: a {} has no {field}", item.kind));
            }
        }
        let fields = &item.fields;
        if items::has_game(kind) {
            match &fields.game {
                None => problems.push(format!("{at}: a {} needs a game", item.kind)),
                Some(game) if !games.contains(game.as_str()) => {
                    problems.push(format!("{at}: game {game:?} is not in games"));
                }
                Some(_) => {}
            }
        }
        if matches!(kind, ItemKind::Miniature | ItemKind::Terrain)
            && !fields.scale.as_deref().is_some_and(|scale| SCALES.contains(&scale))
        {
            problems.push(format!("{at}: scale {:?} is not one of {SCALES:?}", fields.scale));
        }
        if kind == ItemKind::Tablecloth {
            if !fields.size.as_deref().is_some_and(|size| TABLECLOTH_SIZES.iter().any(|(cm, _)| *cm == size)) {
                problems.push(format!("{at}: size {:?} is not a tablecloth size", fields.size));
            }
            if let Some(material) = &fields.material
                && !TABLECLOTH_MATERIALS.contains(&material.as_str())
            {
                problems.push(format!("{at}: material {material:?} is not one of {TABLECLOTH_MATERIALS:?}"));
            }
        }
    }
    if problems.is_empty() { Ok(()) } else { Err(SeedError::Invalid(problems)) }
}

/// The insert values of a checked item, in `own_columns` order.
fn values(kind: ItemKind, item: &SeedItem, location_id: i64, game_id: Option<i64>) -> Values {
    let fields = &item.fields;
    let name = Value::Text(item.name.clone());
    let text = |value: &Option<String>| Value::Text(value.clone().unwrap_or_default());
    let opt = |value: &Option<String>| Value::OptText(value.clone());
    let game = || ("game_id", Value::Int(game_id.unwrap_or_default()));
    let own = match kind {
        ItemKind::Miniature => vec![("type", name), game(), ("scale", text(&fields.scale))],
        ItemKind::Terrain => {
            vec![("type", name), game(), ("scale", text(&fields.scale)), ("theater", opt(&fields.theater))]
        }
        ItemKind::Tablecloth => vec![
            ("type", name),
            ("material", opt(&fields.material)),
            game(),
            ("size", text(&fields.size)),
            ("remarks", opt(&fields.remarks)),
        ],
        ItemKind::Rulebook => {
            vec![("name", name), game(), ("supplement", Value::Bool(fields.supplement == Some(true)))]
        }
        ItemKind::BoardGame => vec![("name", name), ("universe", opt(&fields.universe))],
        ItemKind::Book => vec![("name", name), ("universe", opt(&fields.universe)), ("period", opt(&fields.period))],
        ItemKind::Equipment => vec![("type", name)],
        ItemKind::Consumable => vec![("type", name), ("unit", opt(&fields.unit))],
    };
    Values { category: kind.category().to_owned(), quantity: item.quantity, location_id, own, sticker_printed: None }
}

/// Checks the file, then loads it into an empty database in one transaction.
pub async fn seed(pool: &SqlitePool, file: &SeedFile) -> Result<Summary, SeedError> {
    check(file)?;
    let mut tx = pool.begin().await?;

    let associations = sqlx::query_scalar!("SELECT COUNT(*) FROM associations").fetch_one(&mut *tx).await?;
    let games = sqlx::query_scalar!("SELECT COUNT(*) FROM games").fetch_one(&mut *tx).await?;
    if associations > 0 || games > 0 {
        return Err(SeedError::NotEmpty { associations, games });
    }

    let association_id = sqlx::query_scalar!(
        "INSERT INTO associations (name, slug) VALUES (?, ?) RETURNING id AS \"id!\"",
        file.association.name,
        file.association.slug
    )
    .fetch_one(&mut *tx)
    .await?;
    let mut location_ids = HashMap::new();
    for location in &file.locations {
        let id = sqlx::query_scalar!(
            "INSERT INTO locations (association_id, room, spot) VALUES (?, ?, ?) RETURNING id AS \"id!\"",
            association_id,
            location.room,
            location.spot
        )
        .fetch_one(&mut *tx)
        .await?;
        location_ids.insert((location.room.as_str(), location.spot.as_str()), id);
    }
    let mut game_ids = HashMap::new();
    for game in &file.games {
        let id = sqlx::query_scalar!("INSERT INTO games (name) VALUES (?) RETURNING id AS \"id!\"", game)
            .fetch_one(&mut *tx)
            .await?;
        game_ids.insert(game.as_str(), id);
    }

    let mut counts: HashMap<ItemKind, usize> = HashMap::new();
    for item in &file.items {
        // `check` vouched for the type, the location and the game.
        let Some(kind) = ItemKind::from_item_type(&item.kind) else { continue };
        let [room, spot] = &item.location;
        let location_id = location_ids.get(&(room.as_str(), spot.as_str())).copied().unwrap_or_default();
        let game_id = item.fields.game.as_deref().and_then(|game| game_ids.get(game).copied());
        items::insert(&mut *tx, kind, association_id, &values(kind, item, location_id, game_id)).await?;
        *counts.entry(kind).or_default() += 1;
    }
    tx.commit().await?;

    Ok(Summary {
        association: file.association.slug.clone(),
        locations: file.locations.len(),
        games: file.games.len(),
        items: ItemKind::ALL.into_iter().filter_map(|kind| counts.get(&kind).map(|n| (kind, *n))).collect(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_embedded_file_is_valid() {
        let file = parse(GROGNARDS);
        assert!(file.is_ok(), "{file:?}");
        if let Ok(file) = file {
            let checked = check(&file);
            assert!(checked.is_ok(), "{checked:?}");
        }
    }
}
