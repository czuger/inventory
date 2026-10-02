//! Ported from `tests/test_duplicates.py` and the legacy-id tests of
//! `tests/test_database.py`.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::http::{StatusCode, header};

use common::{Client, SECRET_KEY, Seed, TestDb};
use inventory::db::items::{self, Value, Values};
use inventory::kinds::ItemKind;
use inventory::{AppState, build_app};

const OBJECT_ID: &str = "65f0c0ffee0123456789abcd";

async fn make_mini(db: &TestDb, seed: &Seed) -> i64 {
    let values = Values {
        category: "Miniature".into(),
        quantity: 1,
        location_id: seed.loc,
        own: vec![
            ("type", Value::Text("Infantry".into())),
            ("game_id", Value::Int(seed.game)),
            ("scale", Value::Text("28mm".into())),
        ],
        sticker_printed: None,
    };
    items::insert(&db.pool, ItemKind::Miniature, seed.assoc, &values).await.unwrap()
}

async fn make_board_game(db: &TestDb, seed: &Seed) -> i64 {
    let values = Values {
        category: "Board Game".into(),
        quantity: 1,
        location_id: seed.loc,
        own: vec![("name", Value::Text("Catan".into())), ("universe", Value::OptText(None))],
        sticker_printed: None,
    };
    items::insert(&db.pool, ItemKind::BoardGame, seed.assoc, &values).await.unwrap()
}

fn mini_url(id: i64) -> String {
    format!("http://localhost/test/miniatures/{id}")
}

async fn setup() -> (TestDb, Seed, Client) {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let mut client = Client::new(db.app());
    client.login(seed.admin);
    (db, seed, client)
}

async fn links(db: &TestDb) -> Vec<(i64, String, i64, String)> {
    sqlx::query_as("SELECT item1_id, item1_type, item2_id, item2_type FROM duplicate_links ORDER BY id")
        .fetch_all(&db.pool)
        .await
        .unwrap()
}

async fn add(client: &mut Client, from: i64, url: &str) -> common::TestResponse {
    let response = client.post_form(&format!("/test/miniatures/{from}/duplicates"), &[("duplicate_url", url)]).await;
    client.follow(response).await
}

async fn add_legacy(db: &TestDb, item: i64) {
    sqlx::query("INSERT INTO legacy_object_ids (object_id, item_type, item_id) VALUES (?, 'miniature', ?)")
        .bind(OBJECT_ID)
        .bind(item)
        .execute(&db.pool)
        .await
        .unwrap();
}

#[tokio::test]
async fn test_add_duplicate_link() {
    let (db, seed, mut client) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    let response = add(&mut client, a, &mini_url(b)).await;
    assert_eq!(response.status, StatusCode::OK);
    assert!(response.body.contains("Suspected duplicate link added."));
    assert_eq!(links(&db).await, vec![(a, "miniature".into(), b, "miniature".into())]);
}

#[tokio::test]
async fn test_add_duplicate_requires_admin() {
    let (db, seed, _) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    let mut user = Client::new(db.app());
    user.login(seed.user);
    let response =
        user.post_form(&format!("/test/miniatures/{a}/duplicates"), &[("duplicate_url", &mini_url(b))]).await;
    assert_eq!(response.status, StatusCode::FORBIDDEN);
    assert!(links(&db).await.is_empty());
}

#[tokio::test]
async fn test_add_duplicate_rejects_self_link() {
    let (db, seed, mut client) = setup().await;
    let a = make_mini(&db, &seed).await;
    assert!(add(&mut client, a, &mini_url(a)).await.body.contains("Cannot link an item to itself."));
    assert!(links(&db).await.is_empty());
}

#[tokio::test]
async fn test_add_duplicate_rejects_double_link() {
    let (db, seed, mut client) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    add(&mut client, a, &mini_url(b)).await;
    assert!(add(&mut client, a, &mini_url(b)).await.body.contains("This link already exists."));
    assert_eq!(links(&db).await.len(), 1);
}

#[tokio::test]
async fn test_add_duplicate_rejects_reverse_double_link() {
    let (db, seed, mut client) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    add(&mut client, a, &mini_url(b)).await;
    add(&mut client, b, &mini_url(a)).await;
    assert_eq!(links(&db).await.len(), 1);
}

#[tokio::test]
async fn test_add_duplicate_invalid_url() {
    let (db, seed, mut client) = setup().await;
    let a = make_mini(&db, &seed).await;
    assert!(add(&mut client, a, "not-a-url").await.body.contains("Invalid item URL."));
    for url in ["http://localhost/test/dragons/1", "http://localhost/test/miniatures/abc", "/test/miniatures/0"] {
        add(&mut client, a, url).await;
    }
    assert!(links(&db).await.is_empty());
}

#[tokio::test]
async fn test_add_duplicate_nonexistent_item() {
    let (db, seed, mut client) = setup().await;
    let a = make_mini(&db, &seed).await;
    assert!(add(&mut client, a, &mini_url(999_999)).await.body.contains("Linked item not found."));
    assert!(links(&db).await.is_empty());
}

#[tokio::test]
async fn test_delete_duplicate_link() {
    let (db, seed, mut client) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    add(&mut client, a, &mini_url(b)).await;
    let link: i64 = sqlx::query_scalar("SELECT id FROM duplicate_links").fetch_one(&db.pool).await.unwrap();
    let response = client.post(&format!("/test/miniatures/{a}/duplicates/{link}/delete")).await;
    let response = client.follow(response).await;
    assert_eq!(response.status, StatusCode::OK);
    assert!(response.body.contains("Duplicate link removed."));
    assert!(links(&db).await.is_empty());
}

#[tokio::test]
async fn test_delete_duplicate_requires_admin() {
    let (db, seed, mut admin) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    add(&mut admin, a, &mini_url(b)).await;
    let link: i64 = sqlx::query_scalar("SELECT id FROM duplicate_links").fetch_one(&db.pool).await.unwrap();
    let mut user = Client::new(db.app());
    user.login(seed.user);
    let response = user.post(&format!("/test/miniatures/{a}/duplicates/{link}/delete")).await;
    assert_eq!(response.status, StatusCode::FORBIDDEN);
    assert_eq!(links(&db).await.len(), 1);
}

#[tokio::test]
async fn test_duplicate_link_is_bidirectional() {
    let (db, seed, mut client) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    add(&mut client, a, &mini_url(b)).await;
    // Created from a's side; b's page shows it, linking back to a.
    let page = client.get(&format!("/test/miniatures/{b}")).await;
    assert_eq!(page.status, StatusCode::OK);
    assert!(
        page.body.contains(&format!("href=\"/test/miniatures/{a}\">Infantry – Test Game · 28mm</a>")),
        "{}",
        page.body
    );
}

#[tokio::test]
async fn test_cross_type_duplicate() {
    let (db, seed, mut client) = setup().await;
    let mini = make_mini(&db, &seed).await;
    let board_game = make_board_game(&db, &seed).await;
    let response = add(&mut client, mini, &format!("http://localhost/test/board-games/{board_game}")).await;
    assert_eq!(response.status, StatusCode::OK);
    assert_eq!(links(&db).await, vec![(mini, "miniature".into(), board_game, "board_game".into())]);
    assert!(response.body.contains(&format!("href=\"/test/board-games/{board_game}\">Catan</a>")));
}

#[tokio::test]
async fn test_show_page_renders_duplicates_section() {
    let (db, seed, mut client) = setup().await;
    let item = make_mini(&db, &seed).await;
    let page = client.get(&format!("/test/miniatures/{item}")).await;
    assert!(page.body.to_lowercase().contains("doublon"));
}

#[tokio::test]
async fn test_edit_page_shows_duplicate_form_for_admin() {
    let (db, seed, mut client) = setup().await;
    let item = make_mini(&db, &seed).await;
    assert!(client.get(&format!("/test/miniatures/{item}/edit")).await.body.contains("duplicate_url"));
}

#[tokio::test]
async fn test_edit_page_no_duplicate_form_for_non_admin() {
    let (db, seed, _) = setup().await;
    let item = make_mini(&db, &seed).await;
    let mut user = Client::new(db.app());
    user.login(seed.user);
    let page = user.get(&format!("/test/miniatures/{item}/edit")).await;
    assert_eq!(page.status, StatusCode::FORBIDDEN);
    assert!(!page.body.contains("duplicate_url"));
}

// --- from tests/test_database.py ---------------------------------------------------

#[tokio::test]
async fn test_legacy_object_id_url_redirects() {
    let (db, seed, mut client) = setup().await;
    let item = make_mini(&db, &seed).await;
    add_legacy(&db, item).await;
    let response = client.get(&format!("/test/miniatures/{OBJECT_ID}")).await;
    assert_eq!(response.status, StatusCode::MOVED_PERMANENTLY);
    assert_eq!(response.headers[header::LOCATION], format!("/test/miniatures/{item}"));
}

#[tokio::test]
async fn test_unknown_legacy_object_id_is_404() {
    let (_, _, mut client) = setup().await;
    assert_eq!(client.get(&format!("/test/miniatures/{OBJECT_ID}")).await.status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn test_legacy_object_id_of_another_type_is_404() {
    let (db, seed, mut client) = setup().await;
    let item = make_mini(&db, &seed).await;
    add_legacy(&db, item).await;
    assert_eq!(client.get(&format!("/test/terrains/{OBJECT_ID}")).await.status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn test_duplicate_link_accepts_legacy_url() {
    let (db, seed, mut client) = setup().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    add_legacy(&db, b).await;
    add(&mut client, a, &format!("http://localhost/test/miniatures/{OBJECT_ID}")).await;
    assert_eq!(links(&db).await, vec![(a, "miniature".into(), b, "miniature".into())]);
}

// --- beyond the Python suite -------------------------------------------------------

#[tokio::test]
async fn legacy_redirect_keeps_the_url_slug_and_prefix() {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let item = make_mini(&db, &seed).await;
    add_legacy(&db, item).await;
    let mut config = db.config();
    config.url_prefix = "inventory".into();
    let app = build_app(AppState::new(config, SECRET_KEY, db.pool.clone()).unwrap());
    // The slug is not checked here (as in Flask): the item page will.
    let response = Client::new(app).get(&format!("/whatever/miniatures/{OBJECT_ID}")).await;
    assert_eq!(response.headers[header::LOCATION], format!("/inventory/whatever/miniatures/{item}"));
}

#[tokio::test]
async fn pasted_production_url_is_understood() {
    // Python missed the type in `/inventory/<slug>/<items>/<id>`; the prefix is stripped now.
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let (a, b) = (make_mini(&db, &seed).await, make_mini(&db, &seed).await);
    let mut config = db.config();
    config.url_prefix = "inventory".into();
    let app = build_app(AppState::new(config, SECRET_KEY, db.pool.clone()).unwrap());
    let mut client = Client::new(app).with_cookie_name("session_inventory");
    client.login(seed.admin);
    let url = format!("https://apps.ieroe.com/inventory/test/miniatures/{b}");
    client.post_form(&format!("/test/miniatures/{a}/duplicates"), &[("duplicate_url", &url)]).await;
    assert_eq!(links(&db).await.len(), 1);
}

#[tokio::test]
async fn link_to_another_association_is_refused() {
    let (db, seed, mut client) = setup().await;
    let a = make_mini(&db, &seed).await;
    sqlx::raw_sql(
        "INSERT INTO associations (name, slug) VALUES ('Other', 'other');
         INSERT INTO locations (association_id, room, spot) VALUES (2, 'X', '');
         INSERT INTO miniatures (association_id, category, type, game_id, scale, quantity, borrowing_count,
             sticker_printed, location_id, images) VALUES (2, 'Miniature', 'Theirs', 1, '28mm', 1, 0, 0, 2, '[]');",
    )
    .execute(&db.pool)
    .await
    .unwrap();
    let theirs: i64 = sqlx::query_scalar("SELECT max(id) FROM miniatures").fetch_one(&db.pool).await.unwrap();
    assert!(add(&mut client, a, &mini_url(theirs)).await.body.contains("Linked item not found."));
    assert!(links(&db).await.is_empty());
}
