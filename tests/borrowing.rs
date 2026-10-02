//! Ported from `tests/test_borrowing.py`, plus the redirect and the show page.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::body::Body;
use axum::http::{Request, StatusCode, header};

use common::{Client, Seed, TestDb};
use inventory::db::items::{self, Value, Values};
use inventory::kinds::ItemKind;

async fn make_mini(db: &TestDb, seed: &Seed, borrowing_count: i64) -> i64 {
    let values = Values {
        category: "Miniature".into(),
        quantity: 3,
        location_id: seed.loc,
        own: vec![
            ("type", Value::Text("Infantry".into())),
            ("game_id", Value::Int(seed.game)),
            ("scale", Value::Text("28mm".into())),
        ],
        sticker_printed: None,
    };
    let id = items::insert(&db.pool, ItemKind::Miniature, seed.assoc, &values).await.unwrap();
    sqlx::query("UPDATE miniatures SET borrowing_count = ? WHERE id = ?")
        .bind(borrowing_count)
        .bind(id)
        .execute(&db.pool)
        .await
        .unwrap();
    id
}

async fn borrowing_count(db: &TestDb, id: i64) -> i64 {
    db.count(&format!("SELECT borrowing_count FROM miniatures WHERE id = {id}")).await
}

async fn setup(borrowing_count: i64) -> (TestDb, Seed, i64, Client) {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let item = make_mini(&db, &seed, borrowing_count).await;
    let mut client = Client::new(db.app());
    client.login(seed.user);
    (db, seed, item, client)
}

#[tokio::test]
async fn test_borrow_increments_count() {
    let (db, _, item, mut client) = setup(0).await;
    client.post(&format!("/test/miniatures/{item}/borrow")).await;
    client.post(&format!("/test/miniatures/{item}/borrow")).await;
    assert_eq!(borrowing_count(&db, item).await, 2);
}

#[tokio::test]
async fn test_return_decrements_count() {
    let (db, _, item, mut client) = setup(2).await;
    client.post(&format!("/test/miniatures/{item}/return")).await;
    assert_eq!(borrowing_count(&db, item).await, 1);
}

#[tokio::test]
async fn test_return_floor_at_zero() {
    let (db, _, item, mut client) = setup(0).await;
    client.post(&format!("/test/miniatures/{item}/return")).await;
    assert_eq!(borrowing_count(&db, item).await, 0);
}

#[tokio::test]
async fn test_borrowing_records_user() {
    let (db, seed, item, mut client) = setup(0).await;
    client.post(&format!("/test/miniatures/{item}/borrow")).await;
    let (borrower, action): (i64, String) =
        sqlx::query_as("SELECT borrower_id, action FROM borrowings WHERE item_id = ? ORDER BY id LIMIT 1")
            .bind(item)
            .fetch_one(&db.pool)
            .await
            .unwrap();
    assert_eq!(borrower, seed.user);
    assert_eq!(action, "borrow");
}

#[tokio::test]
async fn test_borrow_history_order() {
    let (db, _, item, mut client) = setup(0).await;
    client.post(&format!("/test/miniatures/{item}/borrow")).await;
    client.post(&format!("/test/miniatures/{item}/return")).await;
    let actions: Vec<String> =
        sqlx::query_scalar("SELECT action FROM borrowings WHERE item_id = ? ORDER BY date DESC, id DESC")
            .bind(item)
            .fetch_all(&db.pool)
            .await
            .unwrap();
    assert_eq!(actions, ["return", "borrow"]);
}

#[tokio::test]
async fn test_borrow_creates_association_record() {
    let (db, seed, item, mut client) = setup(0).await;
    client.post(&format!("/test/miniatures/{item}/borrow")).await;
    let assoc: i64 = sqlx::query_scalar("SELECT association_id FROM borrowings WHERE item_id = ?")
        .bind(item)
        .fetch_one(&db.pool)
        .await
        .unwrap();
    assert_eq!(assoc, seed.assoc);
}

// --- beyond the Python suite -------------------------------------------------------

#[tokio::test]
async fn dates_are_stored_like_sqlalchemy() {
    let (db, _, item, mut client) = setup(0).await;
    client.post(&format!("/test/miniatures/{item}/borrow")).await;
    let date: String = sqlx::query_scalar("SELECT date FROM borrowings").fetch_one(&db.pool).await.unwrap();
    // YYYY-MM-DD HH:MM:SS.ffffff
    assert_eq!(date.len(), 26, "{date}");
    assert_eq!(&date[10..11], " ");
    assert_eq!(&date[19..20], ".");
}

#[tokio::test]
async fn redirects_to_the_referrer_or_the_item() {
    let (_, _, item, mut client) = setup(0).await;
    let request = Request::post(format!("/test/miniatures/{item}/borrow"))
        .header(header::REFERER, "http://localhost/test/miniatures/")
        .body(Body::empty())
        .unwrap();
    let response = client.send(request).await;
    assert_eq!(response.headers[header::LOCATION], "http://localhost/test/miniatures/");
    // Python crashed without a Referer (`redirect(None)`): the item page now.
    let response = client.post(&format!("/test/miniatures/{item}/return")).await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(response.headers[header::LOCATION], format!("/test/miniatures/{item}"));
}

#[tokio::test]
async fn show_page_offers_the_right_button() {
    let (db, seed, item, mut user) = setup(0).await;
    let page = user.get(&format!("/test/miniatures/{item}")).await;
    assert!(page.body.contains(&format!("/test/miniatures/{item}/borrow")));
    user.post(&format!("/test/miniatures/{item}/borrow")).await;
    let page = user.get(&format!("/test/miniatures/{item}")).await;
    // The borrower is offered the return; anyone else may borrow another one.
    assert!(page.body.contains(&format!("/test/miniatures/{item}/return")));
    assert!(page.body.contains("plain_user"));
    let mut admin = Client::new(db.app());
    admin.login(seed.admin);
    let page = admin.get(&format!("/test/miniatures/{item}")).await;
    assert!(page.body.contains(&format!("/test/miniatures/{item}/borrow")));
    assert!(!page.body.contains(&format!("/test/miniatures/{item}/return")));
    // Anonymous visitors see the history but no button.
    let page = Client::new(db.app()).get(&format!("/test/miniatures/{item}")).await;
    assert!(page.body.contains("plain_user"));
    assert!(!page.body.contains(&format!("/test/miniatures/{item}/borrow\"")));
}
