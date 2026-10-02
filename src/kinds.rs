//! The eight item types and every name each goes by. In the Flask app this knowledge was
//! spread over a dozen hand-maintained registries (CLAUDE.md lists them); here it is one
//! table.

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ItemKind {
    Miniature,
    Terrain,
    Tablecloth,
    Rulebook,
    BoardGame,
    Book,
    Equipment,
    Consumable,
}

impl ItemKind {
    /// In the order the print page walks them (`print_page.ITEM_TYPES`).
    pub const ALL: [ItemKind; 8] = [
        Self::Miniature,
        Self::Terrain,
        Self::Tablecloth,
        Self::Rulebook,
        Self::BoardGame,
        Self::Book,
        Self::Equipment,
        Self::Consumable,
    ];

    /// What `Borrowing.item_type`, `DuplicateLink.item*_type` and `legacy_object_ids` store.
    pub fn item_type(self) -> &'static str {
        match self {
            Self::Miniature => "miniature",
            Self::Terrain => "terrain",
            Self::Tablecloth => "tablecloth",
            Self::Rulebook => "rulebook",
            Self::BoardGame => "board_game",
            Self::Book => "book",
            Self::Equipment => "equipment",
            Self::Consumable => "consumable",
        }
    }

    /// The Flask blueprint name, which prefixes its endpoints (`board_games.show`).
    pub fn blueprint(self) -> &'static str {
        match self {
            Self::Miniature => "miniatures",
            Self::Terrain => "terrains",
            Self::Tablecloth => "tablecloths",
            Self::Rulebook => "rulebooks",
            Self::BoardGame => "board_games",
            Self::Book => "books",
            Self::Equipment => "equipment",
            Self::Consumable => "consumables",
        }
    }

    /// The URL segment after the association slug (`/<slug>/board-games/`).
    pub fn segment(self) -> &'static str {
        match self {
            Self::BoardGame => "board-games",
            other => other.blueprint(),
        }
    }

    /// The table, which is also the blueprint name.
    pub fn table(self) -> &'static str {
        self.blueprint()
    }

    /// The category display name (`CATEGORIES`), the default `category` of a new item.
    pub fn category(self) -> &'static str {
        match self {
            Self::Miniature => "Miniature",
            Self::Terrain => "Terrain",
            Self::Tablecloth => "Tablecloth",
            Self::Rulebook => "Rulebook",
            Self::BoardGame => "Board Game",
            Self::Book => "Book",
            Self::Equipment => "Equipment",
            Self::Consumable => "Consumable",
        }
    }

    /// How flash messages name it (`"Board game created."`).
    pub fn noun(self) -> &'static str {
        match self {
            Self::BoardGame => "Board game",
            other => other.category(),
        }
    }

    /// The template directory (`board_game/list.html`).
    pub fn template_dir(self) -> &'static str {
        self.item_type()
    }

    /// A consumable starts at 0; everything else at 1.
    pub fn default_quantity(self) -> i64 {
        match self {
            Self::Consumable => 0,
            _ => 1,
        }
    }

    pub fn from_item_type(item_type: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|kind| kind.item_type() == item_type)
    }

    /// `_SLUG_TO_TYPE`: the URL segment to the type.
    pub fn from_segment(segment: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|kind| kind.segment() == segment)
    }

    pub fn from_blueprint(blueprint: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|kind| kind.blueprint() == blueprint)
    }

    pub fn from_category(category: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|kind| kind.category() == category)
    }
}

/// `CATEGORIES` from `inventory/db/constants.py`, in its (form) order.
pub const CATEGORIES: [&str; 8] =
    ["Tablecloth", "Miniature", "Terrain", "Rulebook", "Board Game", "Book", "Equipment", "Consumable"];

/// `(cm, inches)`, in form order.
pub const TABLECLOTH_SIZES: [(&str, &str); 6] = [
    ("120x180", "48\"x72\""),
    ("120x90", "48\"x36\""),
    ("90x90", "36\"x36\""),
    ("120x120", "48\"x48\""),
    ("120x80", "48\"x32\""),
    ("?x?", "?x?"),
];

pub const SCALES: [&str; 4] = ["70mm", "28mm", "15mm", "Mixte"];

/// The values the `tablecloths.material` CHECK constraint allows.
pub const TABLECLOTH_MATERIALS: [&str; 4] = ["mousepad (neoprene)", "vinyl", "cloth", "textured"];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_round_trip() {
        for kind in ItemKind::ALL {
            assert_eq!(ItemKind::from_item_type(kind.item_type()), Some(kind));
            assert_eq!(ItemKind::from_segment(kind.segment()), Some(kind));
            assert_eq!(ItemKind::from_blueprint(kind.blueprint()), Some(kind));
            assert_eq!(ItemKind::from_category(kind.category()), Some(kind));
            assert!(CATEGORIES.contains(&kind.category()));
        }
        assert_eq!(ItemKind::BoardGame.segment(), "board-games");
        assert_eq!(ItemKind::BoardGame.blueprint(), "board_games");
        assert_eq!(ItemKind::Equipment.segment(), "equipment");
        assert_eq!(ItemKind::from_segment("board_games"), None);
    }
}
