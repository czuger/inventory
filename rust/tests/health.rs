#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::body::Body;
use axum::http::{Request, StatusCode, header};

use common::{TestDb, get, send, test_config};
use inventory::{AppState, build_app, db};

#[tokio::test]
async fn health_is_plain_ok() {
    let db = TestDb::new().await;
    let response = get(db.app(), "/health").await;
    assert_eq!(response.status, StatusCode::OK);
    assert_eq!(response.headers[header::CONTENT_TYPE], "text/plain");
    assert_eq!(response.body, "ok");

    let head = send(db.app(), Request::head("/health").body(Body::empty()).unwrap()).await;
    assert_eq!(head.status, StatusCode::OK);
    assert_eq!(head.body, "");
}

#[tokio::test]
async fn health_never_touches_the_database() {
    // A pool whose database cannot even be opened: /health must not notice.
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("missing/dir/inventory.sqlite3");
    let pool = sqlx::SqlitePool::connect_lazy_with(db::connect_options(&path));
    let app = build_app(AppState::new(test_config(dir.path(), &path), common::SECRET_KEY, pool).unwrap());
    assert_eq!(get(app, "/health").await.status, StatusCode::OK);
}

#[tokio::test]
async fn unknown_url_is_werkzeug_404() {
    let db = TestDb::new().await;
    let response = get(db.app(), "/no/such/page").await;
    assert_eq!(response.status, StatusCode::NOT_FOUND);
    assert_eq!(response.headers[header::CONTENT_TYPE], "text/html; charset=utf-8");
    assert!(response.body.starts_with("<!doctype html>\n<html lang=en>\n<title>404 Not Found</title>"));
}
