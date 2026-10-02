//! App-level routes and werkzeug's routing behaviour.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::body::Body;
use axum::http::{Request, StatusCode, header};
use serde_json::json;

use common::{Client, SECRET_KEY, TestDb, get, send};
use inventory::{AppState, build_app};

async fn add_association(db: &TestDb, name: &str, slug: &str) {
    sqlx::query("INSERT INTO associations (name, slug) VALUES (?, ?)")
        .bind(name)
        .bind(slug)
        .execute(&db.pool)
        .await
        .unwrap();
}

// --- ported from tests/test_auth.py -------------------------------------------------

#[tokio::test]
async fn test_language_switch_to_en() {
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    let response = client.get("/set-language/en").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(client.session()["lang"], "en");
}

#[tokio::test]
async fn test_language_switch_to_fr() {
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    let response = client.get("/set-language/fr").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(client.session()["lang"], "fr");
}

#[tokio::test]
async fn test_language_invalid_ignored() {
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    client.set_session(json!({"lang": "fr"}));
    let response = client.get("/set-language/de").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert!(response.headers.get(header::SET_COOKIE).is_none(), "nothing changed");
    assert_eq!(client.session()["lang"], "fr");
}

// --- the rest of the app-level routes --------------------------------------------

#[tokio::test]
async fn set_language_goes_back_to_the_referrer() {
    let db = TestDb::new().await;
    let request = Request::get("/set-language/en")
        .header(header::REFERER, "http://localhost/test/miniatures/3")
        .body(Body::empty())
        .unwrap();
    let response = send(db.app(), request).await;
    assert_eq!(response.headers[header::LOCATION], "http://localhost/test/miniatures/3");

    let response = get(db.app(), "/set-language/en").await;
    assert_eq!(response.headers[header::LOCATION], "/");
    assert!(response.body.contains(r#"<a href="/">/</a>"#));
}

#[tokio::test]
async fn index_without_association() {
    let db = TestDb::new().await;
    let response = get(db.app(), "/").await;
    assert_eq!(response.status, StatusCode::NOT_FOUND);
    assert_eq!(response.headers[header::CONTENT_TYPE], "text/html; charset=utf-8");
    assert_eq!(response.body, "No association found.");
}

#[tokio::test]
async fn index_redirects_to_the_first_association() {
    let db = TestDb::new().await;
    add_association(&db, "Test Asso", "test").await;
    add_association(&db, "Other Asso", "other").await;
    let response = get(db.app(), "/").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(response.headers[header::LOCATION], "/test/miniatures/");

    // Under a URL prefix, every generated link carries it.
    let mut config = db.config();
    config.url_prefix = "inventory".to_owned();
    let app = build_app(AppState::new(config, SECRET_KEY, db.pool.clone()).unwrap());
    assert_eq!(get(app, "/").await.headers[header::LOCATION], "/inventory/test/miniatures/");
}

#[tokio::test]
async fn missing_trailing_slash_is_a_308() {
    let db = TestDb::new().await;
    let response = get(db.app(), "/test/miniatures?a=1&b=2").await;
    assert_eq!(response.status, StatusCode::PERMANENT_REDIRECT);
    assert_eq!(response.headers[header::LOCATION], "http://localhost/test/miniatures/?a=1&b=2");

    let request = Request::get("/test/board-games")
        .header(header::HOST, "apps.example.com")
        .header("x-forwarded-proto", "https")
        .body(Body::empty())
        .unwrap();
    let response = send(db.app(), request).await;
    assert_eq!(response.headers[header::LOCATION], "https://apps.example.com/test/board-games/");
    assert_eq!(get(db.app(), "/test/print").await.status, StatusCode::PERMANENT_REDIRECT);

    // Only for the methods the rule takes; werkzeug answers anything else with a 404.
    let post = send(db.app(), Request::post("/test/miniatures").body(Body::empty()).unwrap()).await;
    assert_eq!(post.status, StatusCode::NOT_FOUND);
    // And never the other way round.
    assert_eq!(get(db.app(), "/health/").await.status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn wrong_method_is_a_werkzeug_405() {
    let db = TestDb::new().await;
    let response = send(db.app(), Request::post("/health").body(Body::empty()).unwrap()).await;
    assert_eq!(response.status, StatusCode::METHOD_NOT_ALLOWED);
    assert!(response.body.contains("<title>405 Method Not Allowed</title>"));
    let allow: std::collections::BTreeSet<&str> =
        response.headers[header::ALLOW].to_str().unwrap().split(", ").collect();
    assert_eq!(allow, ["GET", "HEAD", "OPTIONS"].into_iter().collect());
    assert_eq!(response.headers[header::VARY], "Cookie");
}

#[tokio::test]
async fn options_lists_the_methods() {
    let db = TestDb::new().await;
    let response = send(db.app(), Request::options("/health").body(Body::empty()).unwrap()).await;
    assert_eq!(response.status, StatusCode::OK);
    assert_eq!(response.body, "");
    assert_eq!(response.headers[header::CONTENT_TYPE], "text/html; charset=utf-8");
    assert!(response.headers[header::ALLOW].to_str().unwrap().contains("OPTIONS"));
}

#[tokio::test]
async fn static_files() {
    let db = TestDb::new().await;
    let response = get(db.app(), "/static/favicon.png").await;
    assert_eq!(response.status, StatusCode::OK);
    assert_eq!(response.headers[header::CONTENT_TYPE], "image/png");
    assert_eq!(get(db.app(), "/static/nope.png").await.status, StatusCode::NOT_FOUND);

    let photo_dir = db.config().uploads_dir.join("board_game/3");
    std::fs::create_dir_all(&photo_dir).unwrap();
    std::fs::write(photo_dir.join("abc_photo.jpg"), b"jpeg bytes").unwrap();
    let response = get(db.app(), "/static/uploads/board_game/3/abc_photo.jpg").await;
    assert_eq!(response.status, StatusCode::OK);
    assert_eq!(response.headers[header::CONTENT_TYPE], "image/jpeg");
    assert_eq!(response.body, "jpeg bytes");

    let missing = get(db.app(), "/static/uploads/board_game/3/missing.jpg").await;
    assert_eq!(missing.status, StatusCode::NOT_FOUND);
    assert!(missing.body.contains("<title>404 Not Found</title>"));
    let traversal = get(db.app(), "/static/uploads/../../secret_key.txt").await;
    assert_eq!(traversal.status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn unknown_association_answers_before_reading_the_session() {
    // Flask's url_value_preprocessor aborts before load_current_user: no Vary, and a
    // Mongo-era session is not cleaned up on that request.
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    client.set_session(json!({"user_id": "65f0c0ffee0123456789abcd"}));
    let response = client.get("/nope/miniatures/").await;
    assert_eq!(response.status, StatusCode::NOT_FOUND);
    assert!(response.headers.get(header::VARY).is_none());
    assert!(response.headers.get(header::SET_COOKIE).is_none());
}

#[tokio::test]
async fn static_files_are_inline_attachments() {
    let db = TestDb::new().await;
    let favicon = get(db.app(), "/static/favicon.png").await;
    assert_eq!(favicon.headers[header::CONTENT_DISPOSITION], "inline; filename=favicon.png");
    let dir = db.config().uploads_dir.join("book/1");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("x_cover.jpg"), b"jpg").unwrap();
    let photo = get(db.app(), "/static/uploads/book/1/x_cover.jpg").await;
    assert_eq!(photo.headers[header::CONTENT_DISPOSITION], "inline; filename=x_cover.jpg");
    let missing = get(db.app(), "/static/uploads/book/1/nope.jpg").await;
    assert!(missing.headers.get(header::CONTENT_DISPOSITION).is_none());
}
