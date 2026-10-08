//! `inventory seed`: the club inventory loads into a fresh database, and nowhere else.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::http::StatusCode;

use common::{TestDb, get};
use inventory::db::items;
use inventory::kinds::ItemKind;
use inventory::seed::{self, GROGNARDS, SeedError};

async fn count(db: &TestDb, table: &str) -> i64 {
    sqlx::query_scalar(sqlx::AssertSqlSafe(format!("SELECT COUNT(*) FROM {table}"))).fetch_one(&db.pool).await.unwrap()
}

#[tokio::test]
async fn seeds_the_whole_file_into_a_fresh_database() {
    let db = TestDb::new().await;
    let file = seed::parse(GROGNARDS).unwrap();
    let summary = seed::seed(&db.pool, &file).await.unwrap();

    assert_eq!(summary.association, "grognards");
    assert_eq!(count(&db, "associations").await, 1);
    assert_eq!(count(&db, "locations").await, file.locations.len() as i64);
    assert_eq!(count(&db, "games").await, file.games.len() as i64);
    let mut total = 0;
    for kind in ItemKind::ALL {
        let expected = file.items.iter().filter(|item| item.kind == kind.item_type()).count();
        assert_eq!(count(&db, kind.table()).await, expected as i64, "{}", kind.table());
        total += expected;
    }
    assert_eq!(total, file.items.len());
    assert_eq!(summary.items.iter().map(|(_, n)| n).sum::<usize>(), total);
}

#[tokio::test]
async fn every_seeded_item_has_a_page() {
    let db = TestDb::new().await;
    seed::seed(&db.pool, &seed::parse(GROGNARDS).unwrap()).await.unwrap();
    let assoc: i64 = sqlx::query_scalar("SELECT id FROM associations").fetch_one(&db.pool).await.unwrap();
    for kind in ItemKind::ALL {
        for item in items::list(&db.pool, kind, assoc).await.unwrap() {
            let response = get(db.app(), &format!("/grognards/{}/{}", kind.segment(), item.id)).await;
            assert_eq!(response.status, StatusCode::OK, "{} {}", kind.segment(), item.id);
        }
        let response = get(db.app(), &format!("/grognards/{}/", kind.segment())).await;
        assert_eq!(response.status, StatusCode::OK, "{} index", kind.segment());
    }
}

#[tokio::test]
async fn refuses_a_database_that_holds_data() {
    let db = TestDb::new().await;
    let file = seed::parse(GROGNARDS).unwrap();
    seed::seed(&db.pool, &file).await.unwrap();
    let before = count(&db, "terrains").await;

    let again = seed::seed(&db.pool, &file).await;
    assert!(matches!(again, Err(SeedError::NotEmpty { associations: 1, .. })), "{again:?}");
    assert_eq!(count(&db, "associations").await, 1);
    assert_eq!(count(&db, "terrains").await, before);
}

#[tokio::test]
async fn an_invalid_file_writes_nothing_and_lists_every_problem() {
    let db = TestDb::new().await;
    let json = r#"{
        "association": {"name": "Club", "slug": "club"},
        "locations": [{"room": "Salle", "spot": "Armoire"}],
        "games": ["Generic"],
        "items": [
            {"source": [], "type": "miniature", "name": "Orcs", "quantity": 1, "location": ["Salle", "Armoire"],
             "fields": {"game": "Generic", "scale": "54mm"}},
            {"source": [], "type": "terrain", "name": "Ruins", "quantity": 1, "location": ["Salle", "Placard"],
             "fields": {"game": "Unknown", "scale": "28mm"}},
            {"source": [], "type": "equipment", "name": "Dice", "quantity": -1, "location": ["Salle", "Armoire"],
             "fields": {"scale": "28mm"}},
            {"source": [], "type": "spaceship", "name": "X", "quantity": 1, "location": ["Salle", "Armoire"]}
        ]
    }"#;
    let file = seed::parse(json).unwrap();
    let Err(SeedError::Invalid(problems)) = seed::seed(&db.pool, &file).await else { panic!("not refused") };
    assert_eq!(problems.len(), 6, "{problems:#?}");
    for expected in
        ["scale Some(\"54mm\")", "Salle / Placard", "game \"Unknown\"", "negative", "has no scale", "spaceship"]
    {
        assert!(problems.iter().any(|p| p.contains(expected)), "{expected}: {problems:#?}");
    }
    assert_eq!(count(&db, "associations").await, 0);
    assert_eq!(count(&db, "locations").await, 0);
}

#[tokio::test]
async fn unknown_keys_are_refused() {
    let json = r#"{"association": {"name": "C", "slug": "c"}, "locations": [], "games": [], "items": [],
                   "extra": 1}"#;
    assert!(matches!(seed::parse(json), Err(SeedError::Json(_))));
}
