//! How an item is named in a sticker, a printed list and a duplicate link
//! (`inventory/api/item_labels.py`).

use crate::db::items::{Item, ItemFields};

/// `x` unless empty: Python's `[x] if x else []` on an optional text.
fn present(value: &Option<String>) -> Option<&str> {
    value.as_deref().filter(|v| !v.is_empty())
}

/// The lines printed on the item's sticker, the first one in bold.
pub fn sticker_lines(item: &Item) -> Vec<String> {
    let loc = item.location.label();
    let qty = format!("Qté : {}", item.quantity);
    let mut lines: Vec<String> = Vec::new();
    match &item.fields {
        ItemFields::Miniature { r#type, game, scale } => {
            lines.extend([r#type.clone(), game.name.clone(), scale.clone()]);
        }
        ItemFields::Terrain { r#type, game, scale, theater } => {
            lines.extend([r#type.clone(), game.name.clone()]);
            lines.extend(present(theater).map(str::to_owned));
            lines.push(scale.clone());
        }
        ItemFields::Tablecloth { r#type, game, size, material, .. } => {
            lines.extend([r#type.clone(), game.name.clone(), size.clone()]);
            lines.extend(present(material).map(str::to_owned));
        }
        ItemFields::Rulebook { name, game, supplement } => {
            lines.extend([name.clone(), game.name.clone()]);
            if *supplement {
                lines.push("Supplément".to_owned());
            }
        }
        ItemFields::BoardGame { name, universe } => {
            lines.push(name.clone());
            lines.extend(present(universe).map(str::to_owned));
        }
        ItemFields::Book { name, universe, period } => {
            lines.push(name.clone());
            lines.extend(present(universe).map(str::to_owned));
            lines.extend(present(period).map(str::to_owned));
        }
        ItemFields::Equipment { r#type } => lines.push(r#type.clone()),
        ItemFields::Consumable { r#type, unit } => {
            lines.push(r#type.clone());
            lines.extend(present(unit).map(str::to_owned));
        }
    }
    lines.push(qty);
    lines.push(loc);
    lines
}

/// One row of the printed list: `(name, details, quantity, location)`.
pub fn list_row(item: &Item) -> (String, String, i64, String) {
    let (name, details) = match &item.fields {
        ItemFields::Miniature { r#type, game, scale } => (r#type.clone(), format!("{} · {scale}", game.name)),
        ItemFields::Terrain { r#type, game, scale, theater } => {
            let mut details = game.name.clone();
            if let Some(theater) = present(theater) {
                details.push_str(&format!(" · {theater}"));
            }
            details.push_str(&format!(" · {scale}"));
            (r#type.clone(), details)
        }
        ItemFields::Tablecloth { r#type, size, material, .. } => {
            let mut details = size.clone();
            if let Some(material) = present(material) {
                details.push_str(&format!(" · {material}"));
            }
            (r#type.clone(), details)
        }
        ItemFields::Rulebook { name, game, supplement } => {
            let mut details = game.name.clone();
            if *supplement {
                details.push_str(" · Supplément");
            }
            (name.clone(), details)
        }
        ItemFields::BoardGame { name, universe } => (name.clone(), universe.clone().unwrap_or_default()),
        ItemFields::Book { name, universe, period } => {
            let parts: Vec<&str> = [present(universe), present(period)].into_iter().flatten().collect();
            (name.clone(), parts.join(" · "))
        }
        ItemFields::Equipment { r#type } => (r#type.clone(), String::new()),
        ItemFields::Consumable { r#type, unit } => (r#type.clone(), unit.clone().unwrap_or_default()),
    };
    (name, details, item.quantity, item.location.label())
}

/// How a duplicate link names the other item: `Name – details`, or just the name.
pub fn display_label(item: &Item) -> String {
    let (name, details, _, _) = list_row(item);
    if details.is_empty() { name } else { format!("{name} – {details}") }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::models::{Game, Location};
    use crate::kinds::ItemKind;

    fn item(kind: ItemKind, fields: ItemFields, spot: &str) -> Item {
        Item {
            kind,
            id: 7,
            association_id: 1,
            category: kind.category().to_owned(),
            quantity: 3,
            borrowing_count: 0,
            sticker_printed: false,
            location: Location { id: 1, association_id: 1, room: "Cave".into(), spot: spot.into() },
            images: vec![],
            fields,
        }
    }

    fn game() -> Game {
        Game { id: 1, name: "Bolt Action".into() }
    }

    #[test]
    fn like_item_labels_py() {
        let terrain = item(
            ItemKind::Terrain,
            ItemFields::Terrain {
                r#type: "Forest".into(),
                game: game(),
                scale: "28mm".into(),
                theater: Some(String::new()),
            },
            "Shelf 2",
        );
        assert_eq!(sticker_lines(&terrain), ["Forest", "Bolt Action", "28mm", "Qté : 3", "Cave – Shelf 2"]);
        assert_eq!(list_row(&terrain), ("Forest".into(), "Bolt Action · 28mm".into(), 3, "Cave – Shelf 2".into()));

        let book = item(
            ItemKind::Book,
            ItemFields::Book { name: "Osprey".into(), universe: None, period: Some("WW2".into()) },
            "",
        );
        assert_eq!(list_row(&book).1, "WW2");
        assert_eq!(display_label(&book), "Osprey – WW2");
        assert_eq!(sticker_lines(&book), ["Osprey", "WW2", "Qté : 3", "Cave"]);

        let rulebook =
            item(ItemKind::Rulebook, ItemFields::Rulebook { name: "Core".into(), game: game(), supplement: true }, "");
        assert_eq!(list_row(&rulebook).1, "Bolt Action · Supplément");

        let equipment = item(ItemKind::Equipment, ItemFields::Equipment { r#type: "Dice".into() }, "");
        assert_eq!(display_label(&equipment), "Dice");
    }
}
