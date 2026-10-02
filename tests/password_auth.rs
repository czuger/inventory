//! Username/password login and sign-up (MIGRATION_PLAN.md §5.9).
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::body::Body;
use axum::http::{Request, StatusCode, header};
use serde_json::json;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

use common::{Client, SECRET_KEY, TestDb, TestResponse};
use inventory::config::DiscordConfig;
use inventory::db::users;
use inventory::{AppState, build_app, password};

async fn setup() -> (TestDb, Client) {
    let db = TestDb::new().await;
    db.seed().await;
    let client = Client::new(db.app());
    (db, client)
}

async fn register(client: &mut Client, username: &str, password: &str, confirm: &str) -> TestResponse {
    client
        .post_form("/auth/register", &[("username", username), ("password", password), ("password_confirm", confirm)])
        .await
}

async fn log_in(client: &mut Client, username: &str, password: &str) -> TestResponse {
    client.post_form("/auth/login", &[("username", username), ("password", password)]).await
}

/// `(id, discord_id, username, is_admin, login, password_hash)` of the user logging in as `login`.
async fn account(db: &TestDb, login: &str) -> Option<(i64, Option<String>, String, bool, String, String)> {
    sqlx::query_as("SELECT id, discord_id, username, is_admin, login, password_hash FROM users WHERE login = ?")
        .bind(login)
        .fetch_optional(&db.pool)
        .await
        .unwrap()
}

// --- sign-up -------------------------------------------------------------------------

#[tokio::test]
async fn sign_up_creates_a_plain_member_and_logs_in() {
    let (db, mut client) = setup().await;
    let response = register(&mut client, "  jean.dupont ", "correct horse", "correct horse").await;
    assert_eq!(response.status, StatusCode::FOUND, "{}", response.body);
    assert_eq!(response.headers[header::LOCATION], "/");
    assert!(response.headers[header::SET_COOKIE].to_str().unwrap().ends_with("; SameSite=Lax"));

    let (id, discord_id, username, is_admin, login, hash) = account(&db, "jean.dupont").await.unwrap();
    assert_eq!((discord_id, username.as_str(), is_admin, login.as_str()), (None, "jean.dupont", false, "jean.dupont"));
    assert!(hash.starts_with("$argon2id$"), "{hash}");
    assert_eq!(client.session()["user_id"], id);

    // Logged in: the navbar shows the name, and borrowing works.
    let page = client.get("/test/miniatures/").await;
    assert!(page.body.contains("jean.dupont"));
    assert!(!page.body.contains("/auth/login\""));
}

#[tokio::test]
async fn sign_up_refusals() {
    let (db, mut client) = setup().await;
    register(&mut client, "Bob", "password1", "password1").await;
    let mut other = Client::new(db.app());
    for (username, password, confirm, message) in [
        ("BOB", "password1", "password1", "This username is already taken"),
        ("ab", "password1", "password1", "doit faire 3 à 32 caractères"),
        ("jean dupont", "password1", "password1", "doit faire 3 à 32 caractères"),
        ("alice", "short", "short", "entre 8 et 128 caractères"),
        ("alice", "password1", "password2", "ne correspondent pas"),
    ] {
        // English for the first, French (the default) for the others.
        other.set_session(if username == "BOB" { json!({"lang": "en"}) } else { json!({}) });
        let response = register(&mut other, username, password, confirm).await;
        assert_eq!(response.status, StatusCode::BAD_REQUEST, "{username}");
        assert!(response.body.contains(message), "{username}: {}", response.body);
        // The name typed is kept in the form.
        assert!(response.body.contains(&format!("value=\"{}\"", username.trim())), "{username}");
    }
    assert_eq!(db.count("SELECT count(*) FROM users WHERE login IS NOT NULL").await, 1);
    assert!(!other.session().contains_key("user_id"));
}

// --- login ---------------------------------------------------------------------------

#[tokio::test]
async fn login_with_a_password() {
    let (db, mut client) = setup().await;
    register(&mut client, "Bob", "password1", "password1").await;
    let (id, ..) = account(&db, "Bob").await.unwrap();

    let mut fresh = Client::new(db.app());
    // The login name is case-insensitive, the password is not.
    let response = log_in(&mut fresh, "bob", "password1").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(fresh.session()["user_id"], id);

    let response = fresh.get("/auth/logout").await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert!(!fresh.session().contains_key("user_id"));
}

#[tokio::test]
async fn failed_logins_all_look_the_same() {
    let (db, mut client) = setup().await;
    register(&mut client, "Bob", "password1", "password1").await;
    // admin_user (from the seed) is a Discord-only account: no password at all.
    for (username, password) in [("Bob", "Password1"), ("nobody", "password1"), ("admin_user", ""), ("", "x")] {
        let mut visitor = Client::new(db.app());
        visitor.set_session(json!({"lang": "en"}));
        let response = log_in(&mut visitor, username, password).await;
        assert_eq!(response.status, StatusCode::BAD_REQUEST, "{username}");
        assert!(response.body.contains("Wrong username or password."), "{username}");
        assert!(!visitor.session().contains_key("user_id"));
    }
}

#[tokio::test]
async fn login_page_offers_both_ways_in() {
    let (_, mut client) = setup().await;
    let page = client.get("/auth/login").await;
    assert_eq!(page.status, StatusCode::OK);
    assert!(page.body.contains("action=\"/auth/login\""));
    assert!(page.body.contains("href=\"/auth/discord\""));
    assert!(page.body.contains("href=\"/auth/register\""));
    // The navbar still links into the (first) association.
    assert!(page.body.contains("href=\"/test/miniatures/\""));
    assert_eq!(client.get("/auth/register").await.status, StatusCode::OK);
    // And every page's navbar leads here.
    assert!(client.get("/test/books/").await.body.contains("href=\"/auth/login\""));
}

#[tokio::test]
async fn attempts_are_rate_limited_per_client() {
    let (db, _) = setup().await;
    let app = db.app();
    let attempt = |ip: &'static str| {
        let app = app.clone();
        async move {
            let request = Request::post("/auth/login")
                .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
                .header("x-real-ip", ip)
                .body(Body::from("username=x&password=y"))
                .unwrap();
            common::send(app, request).await.status
        }
    };
    for _ in 0..10 {
        assert_eq!(attempt("10.0.0.1").await, StatusCode::BAD_REQUEST);
    }
    assert_eq!(attempt("10.0.0.1").await, StatusCode::TOO_MANY_REQUESTS);
    // Sign-ups count against the same budget.
    let request = Request::post("/auth/register")
        .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
        .header("x-real-ip", "10.0.0.1")
        .body(Body::from("username=newbie&password=password1&password_confirm=password1"))
        .unwrap();
    assert_eq!(common::send(app.clone(), request).await.status, StatusCode::TOO_MANY_REQUESTS);
    // Another client is unaffected.
    assert_eq!(attempt("10.0.0.2").await, StatusCode::BAD_REQUEST);
}

// --- Discord members with a password --------------------------------------------------

#[tokio::test]
async fn a_discord_member_given_a_password_keeps_everything() {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    sqlx::query(
        "INSERT INTO borrowings (association_id, borrower_id, item_id, item_type, action, date)
         VALUES (1, ?, 1, 'miniature', 'borrow', '2026-01-01 10:00:00.000000')",
    )
    .bind(seed.user)
    .execute(&db.pool)
    .await
    .unwrap();

    // What `inventory set-password plain_user` does once the password is typed.
    let hash = password::hash("discord-and-pw").await.unwrap();
    users::set_password(&db.pool, seed.user, "plain_user", &hash).await.unwrap();

    // Password login reaches the same account...
    let mut client = Client::new(db.app());
    log_in(&mut client, "plain_user", "discord-and-pw").await;
    assert_eq!(client.session()["user_id"], seed.user);
    let history = db.count(&format!("SELECT count(*) FROM borrowings WHERE borrower_id = {}", seed.user)).await;
    assert_eq!(history, 1);

    // ...and so does Discord, which leaves the login and password alone even when it
    // renames the user.
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/oauth2/token"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"access_token": "tok"})))
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .and(path("/api/users/@me"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"id": "200", "username": "renamed"})))
        .mount(&server)
        .await;
    let mut config = db.config();
    config.discord_api_base = format!("{}/api", server.uri());
    let discord = DiscordConfig { client_id: "c".into(), client_secret: "s".into() };
    let mut discord_client =
        Client::new(build_app(AppState::new(config, SECRET_KEY, db.pool.clone()).unwrap().with_discord(discord)));
    let start = discord_client.get("/auth/discord").await;
    let state = start.headers[header::LOCATION].to_str().unwrap().split("state=").nth(1).unwrap().to_owned();
    discord_client.get(&format!("/auth/discord/callback?code=x&state={state}")).await;
    assert_eq!(discord_client.session()["user_id"], seed.user);

    let (id, discord_id, username, _, login, stored_hash) = account(&db, "plain_user").await.unwrap();
    assert_eq!((id, discord_id.as_deref(), username.as_str()), (seed.user, Some("200"), "renamed"));
    assert_eq!((login.as_str(), stored_hash.as_str()), ("plain_user", hash.as_str()));
}
