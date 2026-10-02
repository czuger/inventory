//! The session middleware: when the cookie is (re)set, deleted or left alone.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::http::header;
use serde_json::json;

use common::{Client, SECRET_KEY, TestDb, get};
use inventory::{AppState, build_app};

#[tokio::test]
async fn test_mongo_era_session_is_logged_out() {
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    client.set_session(json!({"user_id": "65f0c0ffee0123456789abcd"}));
    let response = client.get("/health").await;
    assert_eq!(
        response.headers[header::SET_COOKIE],
        "session=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; HttpOnly; Path=/; SameSite=Lax"
    );
    assert!(!client.session().contains_key("user_id"));
}

#[tokio::test]
async fn mongo_era_logout_keeps_the_rest_of_the_session() {
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    client.set_session(json!({"user_id": "65f0c0ffee0123456789abcd", "lang": "en"}));
    let response = client.get("/health").await;
    let set_cookie = response.headers[header::SET_COOKIE].to_str().unwrap();
    assert!(
        set_cookie.starts_with("session=") && set_cookie.ends_with("; HttpOnly; Path=/; SameSite=Lax"),
        "{set_cookie}"
    );
    assert_eq!(client.session(), json!({"lang": "en"}).as_object().unwrap().clone());
}

#[tokio::test]
async fn unmodified_session_sets_no_cookie() {
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    client.set_session(json!({"user_id": 1, "lang": "en"}));
    let response = client.get("/health").await;
    assert!(response.headers.get(header::SET_COOKIE).is_none());
    assert_eq!(client.session()["user_id"], 1);
}

#[tokio::test]
async fn tampered_cookie_is_an_empty_session() {
    let db = TestDb::new().await;
    let mut client = Client::new(db.app());
    client.cookie = Some("eyJ1c2VyX2lkIjoxfQ.ar5zZA.not-the-signature".to_owned());
    let response = client.get("/health").await;
    // Nothing was modified, so nothing is written back (Flask leaves the bad cookie too).
    assert!(response.headers.get(header::SET_COOKIE).is_none());
}

#[tokio::test]
async fn every_response_varies_on_cookie() {
    let db = TestDb::new().await;
    assert_eq!(get(db.app(), "/health").await.headers[header::VARY], "Cookie");
    assert_eq!(get(db.app(), "/no/such/page").await.headers[header::VARY], "Cookie");
}

#[tokio::test]
async fn prefixed_instance_scopes_its_cookie() {
    let db = TestDb::new().await;
    let mut config = db.config();
    config.url_prefix = "inventory_staging".to_owned();
    let app = build_app(AppState::new(config, SECRET_KEY, db.pool.clone()).unwrap());
    let mut client = Client::new(app);
    client.set_session(json!({"user_id": "65f0c0ffee0123456789abcd"}));
    // The test client sends `session=`, which this instance does not read: untouched.
    assert!(client.get("/health").await.headers.get(header::SET_COOKIE).is_none());

    let cookie = format!("session_inventory_staging={}", client.cookie.clone().unwrap());
    let request = axum::http::Request::get("/health").header(header::COOKIE, cookie).body(axum::body::Body::empty());
    let response = common::send(client.app.clone(), request.unwrap()).await;
    assert_eq!(
        response.headers[header::SET_COOKIE],
        "session_inventory_staging=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; HttpOnly; Path=/inventory_staging; SameSite=Lax"
    );
}
