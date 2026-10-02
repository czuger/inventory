//! Discord login against a mock Discord: ported from `tests/test_auth.py` (which mocked
//! authlib instead), plus the state handling and the failures Python answered with a 500.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::http::{StatusCode, header};
use serde_json::json;
use wiremock::matchers::{body_string_contains, header as has_header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

use common::{Client, SECRET_KEY, TestDb};
use inventory::config::DiscordConfig;
use inventory::{AppState, build_app};

/// A Discord that issues `tok` for code `good-code` (to this client only) and says the
/// user is `user`.
async fn discord(user: serde_json::Value) -> MockServer {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/oauth2/token"))
        // authlib's default client authentication: HTTP Basic, base64("CID:SECRET").
        .and(has_header("authorization", "Basic Q0lEOlNFQ1JFVA=="))
        .and(body_string_contains("grant_type=authorization_code"))
        .and(body_string_contains("code=good-code"))
        .and(body_string_contains("redirect_uri=http%3A%2F%2Flocalhost%2Fauth%2Fdiscord%2Fcallback"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"access_token": "tok", "token_type": "Bearer"})))
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .and(path("/api/users/@me"))
        .and(has_header("authorization", "Bearer tok"))
        .respond_with(ResponseTemplate::new(200).set_body_json(user))
        .mount(&server)
        .await;
    server
}

fn client(db: &TestDb, server: &MockServer) -> Client {
    let mut config = db.config();
    config.discord_api_base = format!("{}/api", server.uri());
    let discord = DiscordConfig { client_id: "CID".into(), client_secret: "SECRET".into() };
    Client::new(build_app(AppState::new(config, SECRET_KEY, db.pool.clone()).unwrap().with_discord(discord)))
}

/// `/auth/discord`, then Discord's redirect back with `code`. Returns the callback's response.
async fn log_in(client: &mut Client, code: &str) -> common::TestResponse {
    let response = client.get("/auth/discord").await;
    assert_eq!(response.status, StatusCode::FOUND);
    let location = response.headers[header::LOCATION].to_str().unwrap().to_owned();
    let state = location.split("state=").nth(1).unwrap().to_owned();
    client.get(&format!("/auth/discord/callback?code={code}&state={state}")).await
}

async fn user_row(db: &TestDb, discord_id: &str) -> Option<(i64, String, Option<String>, bool)> {
    sqlx::query_as("SELECT id, username, display_name, is_admin FROM users WHERE discord_id = ?")
        .bind(discord_id)
        .fetch_optional(&db.pool)
        .await
        .unwrap()
}

// --- ported from tests/test_auth.py -------------------------------------------------

#[tokio::test]
async fn test_logout_clears_session() {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let mut client = Client::new(db.app());
    client.login(seed.admin);
    assert!(client.session().contains_key("user_id"));
    let response = client.get("/auth/logout").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(response.headers[header::LOCATION], "/");
    assert!(!client.session().contains_key("user_id"));
}

#[tokio::test]
async fn test_logout_unauthenticated_is_harmless() {
    let db = TestDb::new().await;
    let response = Client::new(db.app()).get("/auth/logout").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert!(response.headers.get(header::SET_COOKIE).is_none(), "nothing to forget");
}

#[tokio::test]
async fn test_login_redirects_to_discord() {
    let db = TestDb::new().await;
    let server = discord(json!({})).await;
    let mut client = client(&db, &server);
    let response = client.get("/auth/discord").await;
    assert_eq!(response.status, StatusCode::FOUND);
    let location = response.headers[header::LOCATION].to_str().unwrap();
    // Exactly the URL authlib built (parameters in its order, values quote_plus'ed).
    let expected = format!(
        "{}/api/oauth2/authorize?response_type=code&client_id=CID&redirect_uri=\
         http%3A%2F%2Flocalhost%2Fauth%2Fdiscord%2Fcallback&scope=identify&state=",
        server.uri()
    );
    assert!(location.starts_with(&expected), "{location}");
    let state = &location[expected.len()..];
    assert_eq!(state.len(), 30);
    // ...and kept the state where authlib kept it.
    let saved = &client.session()[&format!("_state_discord_{state}")];
    assert_eq!(saved["data"]["redirect_uri"], "http://localhost/auth/discord/callback");
    assert_eq!(saved["data"]["url"], location);
    assert!(saved["exp"].as_f64().unwrap() > 0.0);
}

#[tokio::test]
async fn test_callback_creates_new_user() {
    let db = TestDb::new().await;
    let server = discord(json!({"id": "999", "username": "newplayer", "global_name": "New Player"})).await;
    let mut client = client(&db, &server);
    let response = log_in(&mut client, "good-code").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(response.headers[header::LOCATION], "/");
    let (id, username, display_name, is_admin) = user_row(&db, "999").await.unwrap();
    assert_eq!((username.as_str(), display_name.as_deref(), is_admin), ("newplayer", Some("New Player"), false));
    assert_eq!(client.session()["user_id"], id);
    // The state was used up.
    assert!(!client.session().keys().any(|key| key.starts_with("_state_discord_")));
}

#[tokio::test]
async fn test_callback_updates_existing_user() {
    let db = TestDb::new().await;
    sqlx::query("INSERT INTO users (discord_id, username, is_admin) VALUES ('888', 'old_name', 0)")
        .execute(&db.pool)
        .await
        .unwrap();
    let server = discord(json!({"id": "888", "username": "new_name", "global_name": null})).await;
    let mut client = client(&db, &server);
    log_in(&mut client, "good-code").await;
    let (_, username, display_name, _) = user_row(&db, "888").await.unwrap();
    assert_eq!(username, "new_name");
    assert_eq!(display_name, None);
}

#[tokio::test]
async fn test_callback_no_update_if_unchanged() {
    let db = TestDb::new().await;
    sqlx::query(
        "INSERT INTO users (discord_id, username, display_name, is_admin) VALUES ('777', 'stable', 'Stable', 1)",
    )
    .execute(&db.pool)
    .await
    .unwrap();
    let server = discord(json!({"id": "777", "username": "stable", "global_name": "Stable"})).await;
    let mut client = client(&db, &server);
    log_in(&mut client, "good-code").await;
    assert_eq!(db.count("SELECT count(*) FROM users WHERE discord_id = '777'").await, 1);
    // An admin stays one.
    assert!(user_row(&db, "777").await.unwrap().3);
}

// --- what Python answered with a 500 --------------------------------------------------

async fn assert_failed_login(db: &TestDb, client: &mut Client, response: common::TestResponse) {
    assert_eq!(response.status, StatusCode::FOUND, "{}", response.body);
    // Back to the login page (which offers both ways in), with a message.
    assert_eq!(response.headers[header::LOCATION], "/auth/login");
    assert!(!client.session().contains_key("user_id"));
    assert_eq!(db.count("SELECT count(*) FROM users").await, 0);
}

#[tokio::test]
async fn unknown_state_is_refused() {
    let db = TestDb::new().await;
    let server = discord(json!({"id": "1", "username": "x"})).await;
    let mut client = client(&db, &server);
    let response = client.get("/auth/discord/callback?code=good-code&state=forged").await;
    assert_failed_login(&db, &mut client, response).await;
    assert_eq!(client.session()["_flashes"][0][" t"][1], "Discord login failed.");
}

#[tokio::test]
async fn refused_consent_is_refused() {
    let db = TestDb::new().await;
    let server = discord(json!({"id": "1", "username": "x"})).await;
    let mut client = client(&db, &server);
    let response = client.get("/auth/discord").await;
    let state = response.headers[header::LOCATION].to_str().unwrap().split("state=").nth(1).unwrap().to_owned();
    let response = client.get(&format!("/auth/discord/callback?error=access_denied&state={state}")).await;
    assert_failed_login(&db, &mut client, response).await;
    // The state is dropped all the same.
    assert!(!client.session().keys().any(|key| key.starts_with("_state_discord_")));
}

#[tokio::test]
async fn rejected_code_is_refused() {
    let db = TestDb::new().await;
    let server = discord(json!({"id": "1", "username": "x"})).await;
    let mut client = client(&db, &server);
    let response = log_in(&mut client, "bad-code").await;
    assert_failed_login(&db, &mut client, response).await;
}

#[tokio::test]
async fn a_state_is_good_once() {
    let db = TestDb::new().await;
    let server = discord(json!({"id": "5", "username": "once"})).await;
    let mut client = client(&db, &server);
    let response = client.get("/auth/discord").await;
    let state = response.headers[header::LOCATION].to_str().unwrap().split("state=").nth(1).unwrap().to_owned();
    let callback = format!("/auth/discord/callback?code=good-code&state={state}");
    client.get(&callback).await;
    assert!(client.session().contains_key("user_id"));
    // The state left the session with its first use: replaying the callback fails.
    client.get(&callback).await;
    assert_eq!(client.session()["_flashes"][0][" t"][1], "Discord login failed.");
}

#[tokio::test]
async fn login_without_discord_configured_is_a_500() {
    let db = TestDb::new().await;
    assert_eq!(Client::new(db.app()).get("/auth/discord").await.status, StatusCode::INTERNAL_SERVER_ERROR);
}
