//! Ported from `tests/test_print.py`, plus checks on what the PDFs contain.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use std::io::Read as _;

use axum::http::{StatusCode, header};

use common::{Client, Seed, TestDb, TestResponse};
use inventory::db::items::{self, Value, Values};
use inventory::kinds::ItemKind;

type OwnValues = Vec<(&'static str, Value)>;

/// `_make_one_of_each`: one item per type, in `ItemKind::ALL` order.
async fn make_one_of_each(db: &TestDb, seed: &Seed) -> Vec<(ItemKind, i64)> {
    let text = |v: &str| Value::Text(v.to_owned());
    let game = Value::Int(seed.game);
    let specs: Vec<(ItemKind, i64, OwnValues)> = vec![
        (ItemKind::Miniature, 1, vec![("type", text("Infantry")), ("game_id", game.clone()), ("scale", text("28mm"))]),
        (
            ItemKind::Terrain,
            1,
            vec![
                ("type", text("Forest")),
                ("game_id", game.clone()),
                ("scale", text("28mm")),
                ("theater", Value::OptText(None)),
            ],
        ),
        (
            ItemKind::Tablecloth,
            1,
            vec![
                ("type", text("Green")),
                ("material", Value::OptText(None)),
                ("game_id", game.clone()),
                ("size", text("120x180")),
                ("remarks", Value::OptText(None)),
            ],
        ),
        (
            ItemKind::Rulebook,
            1,
            vec![("name", text("Rules")), ("game_id", game.clone()), ("supplement", Value::Bool(false))],
        ),
        (ItemKind::BoardGame, 1, vec![("name", text("Chess")), ("universe", Value::OptText(None))]),
        (
            ItemKind::Book,
            1,
            vec![("name", text("History")), ("universe", Value::OptText(None)), ("period", Value::OptText(None))],
        ),
        (ItemKind::Equipment, 1, vec![("type", text("Brush"))]),
        (ItemKind::Consumable, 2, vec![("type", text("Paint")), ("unit", Value::OptText(None))]),
    ];
    let mut made = Vec::new();
    for (kind, quantity, own) in specs {
        let values = Values {
            category: kind.category().to_owned(),
            quantity,
            location_id: seed.loc,
            own,
            sticker_printed: None,
        };
        made.push((kind, items::insert(&db.pool, kind, seed.assoc, &values).await.unwrap()));
    }
    made
}

async fn printed(db: &TestDb, kind: ItemKind, id: i64) -> bool {
    db.count(&format!("SELECT sticker_printed FROM {} WHERE id = {id}", kind.table())).await == 1
}

async fn set_printed(db: &TestDb, kind: ItemKind, id: i64, value: bool) {
    let sql = format!("UPDATE {} SET sticker_printed = {} WHERE id = {id}", kind.table(), i64::from(value));
    sqlx::query(sqlx::AssertSqlSafe(sql)).execute(&db.pool).await.unwrap();
}

/// The drawing operators of every page, inflated, so tests can look for drawn strings.
fn pdf_text(pdf: &[u8]) -> String {
    let bytes = pdf;
    let mut out = String::new();
    let mut rest = bytes;
    while let Some(start) = find(rest, b"stream\n") {
        let after = &rest[start + 7..];
        let Some(end) = find(after, b"\nendstream") else { break };
        let mut inflated = String::new();
        if flate2::read::ZlibDecoder::new(&after[..end]).read_to_string(&mut inflated).is_ok() {
            out.push_str(&inflated);
        }
        rest = &after[end..];
    }
    out
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|window| window == needle)
}

fn page_count(pdf: &str) -> usize {
    pdf.split("/Count ").nth(1).and_then(|rest| rest.split_whitespace().next()?.parse().ok()).unwrap_or(0)
}

async fn setup() -> (TestDb, Seed, Client) {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let mut client = Client::new(db.app());
    client.login(seed.admin);
    (db, seed, client)
}

fn assert_pdf(response: &TestResponse, filename: &str) {
    assert_eq!(response.status, StatusCode::OK, "{}", response.body);
    assert_eq!(response.headers[header::CONTENT_TYPE], "application/pdf");
    assert_eq!(response.headers[header::CONTENT_DISPOSITION], format!("inline; filename={filename}"));
    assert!(response.body.starts_with("%PDF-"));
}

#[tokio::test]
async fn test_index() {
    let (_, _, mut client) = setup().await;
    let response = client.get("/test/print/").await;
    assert_eq!(response.status, StatusCode::OK);
    assert!(response.body.to_lowercase().contains("miniature"));
    // `?category=` preselects one.
    let response = client.get("/test/print/?category=Board+Game").await;
    assert!(response.body.contains("<option value=\"Board Game\" selected>"), "{}", response.body);
}

#[tokio::test]
async fn test_index_requires_admin() {
    let (db, seed, _) = setup().await;
    let mut user = Client::new(db.app());
    user.login(seed.user);
    assert_eq!(user.get("/test/print/").await.status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn test_index_unauthenticated() {
    let (db, _, _) = setup().await;
    assert_eq!(Client::new(db.app()).get("/test/print/").await.status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn test_stickers_full_returns_pdf() {
    let (db, seed, mut client) = setup().await;
    make_one_of_each(&db, &seed).await;
    let response = client.post_form("/test/print/stickers", &[("mode", "full")]).await;
    assert_pdf(&response, "stickers.pdf");
    let text = pdf_text(&response.bytes);
    for line in ["(Infantry) Tj", "(Chess) Tj", "(Qt\\351 : 2) Tj", "(Room 1) Tj"] {
        assert!(text.contains(line), "missing {line}");
    }
}

#[tokio::test]
async fn test_stickers_full_marks_all_printed() {
    let (db, seed, mut client) = setup().await;
    let made = make_one_of_each(&db, &seed).await;
    client.post_form("/test/print/stickers", &[("mode", "full")]).await;
    for (kind, id) in made {
        assert!(printed(&db, kind, id).await, "{kind:?}");
    }
}

#[tokio::test]
async fn test_stickers_new_only_skips_printed() {
    let (db, seed, mut client) = setup().await;
    let made = make_one_of_each(&db, &seed).await;
    set_printed(&db, made[0].0, made[0].1, true).await;
    let response = client.post_form("/test/print/stickers", &[("mode", "new")]).await;
    assert!(printed(&db, made[0].0, made[0].1).await);
    assert!(printed(&db, made[1].0, made[1].1).await);
    // The already printed miniature is not on the sheet.
    let text = pdf_text(&response.bytes);
    assert!(!text.contains("(Infantry) Tj"));
    assert!(text.contains("(Forest) Tj"));
}

#[tokio::test]
async fn test_stickers_new_only_marks_unprinted() {
    let (db, seed, mut client) = setup().await;
    let made = make_one_of_each(&db, &seed).await;
    client.post_form("/test/print/stickers", &[("mode", "full")]).await;
    set_printed(&db, made[0].0, made[0].1, false).await;
    client.post_form("/test/print/stickers", &[("mode", "new")]).await;
    assert!(printed(&db, made[0].0, made[0].1).await);
}

#[tokio::test]
async fn test_stickers_category_filters() {
    let (db, seed, mut client) = setup().await;
    let made = make_one_of_each(&db, &seed).await;
    let response = client.post_form("/test/print/stickers", &[("mode", "category"), ("category", "Miniature")]).await;
    assert_pdf(&response, "stickers.pdf");
    assert!(printed(&db, made[0].0, made[0].1).await);
    assert!(!printed(&db, made[1].0, made[1].1).await);
}

#[tokio::test]
async fn test_print_list_full_returns_pdf() {
    let (db, seed, mut client) = setup().await;
    let made = make_one_of_each(&db, &seed).await;
    let response = client.post_form("/test/print/list", &[("mode", "full")]).await;
    assert_pdf(&response, "list.pdf");
    let text = pdf_text(&response.bytes);
    for drawn in ["(Inventaire) Tj", "(Nom / Type) Tj", "(Infantry) Tj", "(Test Game \\267 28mm) Tj", "(Paint) Tj"] {
        assert!(text.contains(drawn), "missing {drawn}");
    }
    // The list does not mark anything printed.
    assert!(!printed(&db, made[0].0, made[0].1).await);
}

#[tokio::test]
async fn test_print_list_new_only() {
    let (db, seed, mut client) = setup().await;
    let made = make_one_of_each(&db, &seed).await;
    set_printed(&db, made[0].0, made[0].1, true).await;
    let response = client.post_form("/test/print/list", &[("mode", "new")]).await;
    assert_pdf(&response, "list.pdf");
    assert!(!pdf_text(&response.bytes).contains("(Infantry) Tj"));
}

#[tokio::test]
async fn test_print_list_category() {
    let (db, seed, mut client) = setup().await;
    make_one_of_each(&db, &seed).await;
    let response = client.post_form("/test/print/list", &[("mode", "category"), ("category", "Terrain")]).await;
    assert_pdf(&response, "list.pdf");
    let text = pdf_text(&response.bytes);
    assert!(text.contains("(Terrain) Tj"), "the category is the title");
    assert!(text.contains("(Forest) Tj"));
    assert!(!text.contains("(Infantry) Tj"));
}

#[tokio::test]
async fn test_stickers_requires_admin() {
    let (db, seed, _) = setup().await;
    let mut user = Client::new(db.app());
    user.login(seed.user);
    assert_eq!(user.post_form("/test/print/stickers", &[("mode", "full")]).await.status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn test_print_list_requires_admin() {
    let (db, seed, _) = setup().await;
    let mut user = Client::new(db.app());
    user.login(seed.user);
    assert_eq!(user.post_form("/test/print/list", &[("mode", "full")]).await.status, StatusCode::FORBIDDEN);
}

// --- beyond the Python suite -------------------------------------------------------

#[tokio::test]
async fn sticker_sheets_paginate_and_link_absolutely() {
    let (db, seed, mut client) = setup().await;
    for _ in 0..2 {
        make_one_of_each(&db, &seed).await;
    }
    // 16 items: two pages of ten.
    let response = client.post_form("/test/print/stickers", &[("mode", "full")]).await;
    assert_eq!(page_count(&response.body), 2);
    // An unknown category prints nothing, but still a (blank) PDF.
    let response = client.post_form("/test/print/stickers", &[("mode", "category"), ("category", "Dragons")]).await;
    assert_pdf(&response, "stickers.pdf");
    assert_eq!(page_count(&response.body), 1);
    assert!(!pdf_text(&response.bytes).contains("Tj"));
}

#[tokio::test]
async fn unknown_slug_before_admin_gate() {
    let (db, _, _) = setup().await;
    assert_eq!(Client::new(db.app()).get("/nope/print/").await.status, StatusCode::NOT_FOUND);
}
