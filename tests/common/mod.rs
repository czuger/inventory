//! Shared test helpers: a migrated database in a temp directory, and an app to call.
#![allow(dead_code, clippy::unwrap_used, clippy::expect_used)]

use std::path::{Path, PathBuf};

use axum::Router;
use axum::body::Body;
use axum::http::{HeaderMap, Request, StatusCode, header};
use http_body_util::BodyExt as _;
use sqlx::SqlitePool;
use tempfile::TempDir;
use tower::ServiceExt as _;

use inventory::config::Config;
use inventory::session::CookieCodec;
use inventory::{AppState, build_app, db, migrate};
use serde_json::{Map, Value};

pub const SECRET_KEY: &str = "test-secret";

/// A database file migrated to the latest schema. Each test gets its own: a temp file
/// rather than `:memory:`, because WAL mode and several pooled connections need a file.
pub struct TestDb {
    pub dir: TempDir,
    pub path: PathBuf,
    pub pool: SqlitePool,
}

impl TestDb {
    pub async fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("inventory.sqlite3");
        migrate::run(&path).await.unwrap();
        let pool = db::connect(&path).await.unwrap();
        Self { dir, path, pool }
    }

    pub fn config(&self) -> Config {
        test_config(self.dir.path(), &self.path)
    }

    pub fn app(&self) -> Router {
        build_app(AppState::new(self.config(), SECRET_KEY, self.pool.clone()).unwrap())
    }
}

pub fn test_config(root: &Path, database_path: &Path) -> Config {
    Config {
        root: root.to_path_buf(),
        database_path: database_path.to_path_buf(),
        url_prefix: String::new(),
        bind_addr: "127.0.0.1:0".to_owned(),
        socket_path: None,
        uploads_dir: root.join("uploads"),
        discord_api_base: "http://discord.invalid/api".to_owned(),
    }
}

pub struct TestResponse {
    pub status: StatusCode,
    pub headers: HeaderMap,
    pub body: String,
    /// The body as sent (`body` is its lossy UTF-8 reading).
    pub bytes: Vec<u8>,
}

pub async fn send(app: Router, request: Request<Body>) -> TestResponse {
    let response = app.oneshot(request).await.unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    TestResponse { status, headers, body: String::from_utf8_lossy(&bytes).into_owned(), bytes: bytes.to_vec() }
}

pub async fn get(app: Router, uri: &str) -> TestResponse {
    send(app, Request::get(uri).body(Body::empty()).unwrap()).await
}

fn unix_now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs()
}

/// Like Flask's test client: keeps the session cookie between requests, and lets a test
/// read or write the session directly (`session_transaction`).
pub struct Client {
    pub app: Router,
    pub cookie: Option<String>,
    /// `session`, or `session_<prefix>` for an app under a URL prefix.
    pub cookie_name: String,
}

impl Client {
    pub fn new(app: Router) -> Self {
        Self { app, cookie: None, cookie_name: "session".to_owned() }
    }

    pub fn with_cookie_name(mut self, name: &str) -> Self {
        self.cookie_name = name.to_owned();
        self
    }

    fn codec() -> CookieCodec {
        CookieCodec::new(SECRET_KEY).unwrap()
    }

    pub async fn send(&mut self, mut request: Request<Body>) -> TestResponse {
        if let Some(cookie) = &self.cookie {
            let header_value = format!("{}={cookie}", self.cookie_name);
            request.headers_mut().insert(header::COOKIE, header_value.parse().unwrap());
        }
        let response = send(self.app.clone(), request).await;
        for set_cookie in response.headers.get_all(header::SET_COOKIE) {
            let set_cookie = set_cookie.to_str().unwrap();
            if let Some(value) = set_cookie.strip_prefix(&format!("{}=", self.cookie_name)) {
                let value = value.split(';').next().unwrap();
                self.cookie = (!value.is_empty()).then(|| value.to_owned());
            }
        }
        response
    }

    pub async fn get(&mut self, uri: &str) -> TestResponse {
        self.send(Request::get(uri).body(Body::empty()).unwrap()).await
    }

    /// The session as the server last left it.
    pub fn session(&self) -> Map<String, Value> {
        self.cookie.as_deref().and_then(|cookie| Self::codec().decode(cookie, unix_now())).unwrap_or_default()
    }

    pub fn set_session(&mut self, data: Value) {
        let Value::Object(map) = data else { panic!("session data must be an object") };
        self.cookie = Some(Self::codec().encode(&map, unix_now()));
    }

    /// `login(client, user)` from conftest.py.
    pub fn login(&mut self, user_id: i64) {
        let mut data = self.session();
        data.insert("user_id".into(), Value::from(user_id));
        self.set_session(Value::Object(data));
    }
}

impl Client {
    pub async fn post_form(&mut self, uri: &str, form: &[(&str, &str)]) -> TestResponse {
        let body: String = form_urlencoded::Serializer::new(String::new()).extend_pairs(form).finish();
        let request = Request::post(uri)
            .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
            .body(Body::from(body))
            .unwrap();
        self.send(request).await
    }

    pub async fn post(&mut self, uri: &str) -> TestResponse {
        self.send(Request::post(uri).body(Body::empty()).unwrap()).await
    }

    /// `follow_redirects=True`: GETs the `Location` of a redirect (all of ours are paths).
    pub async fn follow(&mut self, response: TestResponse) -> TestResponse {
        if !response.status.is_redirection() {
            return response;
        }
        let location = response.headers[header::LOCATION].to_str().unwrap().to_owned();
        Box::pin(self.get(&location)).await
    }
}

/// The rows `conftest.py`'s `_seed` fixture creates.
#[derive(Debug, Clone, Copy)]
pub struct Seed {
    pub assoc: i64,
    pub game: i64,
    pub loc: i64,
    pub admin: i64,
    pub user: i64,
}

impl TestDb {
    pub async fn seed(&self) -> Seed {
        let id = |sql: &'static str| {
            let pool = self.pool.clone();
            async move { sqlx::query_scalar::<_, i64>(sql).fetch_one(&pool).await.unwrap() }
        };
        Seed {
            assoc: id("INSERT INTO associations (name, slug) VALUES ('Test Asso', 'test') RETURNING id").await,
            game: id("INSERT INTO games (name) VALUES ('Test Game') RETURNING id").await,
            loc: id("INSERT INTO locations (association_id, room, spot) VALUES (1, 'Room 1', '') RETURNING id").await,
            admin: id(
                "INSERT INTO users (discord_id, username, is_admin) VALUES ('100', 'admin_user', 1) RETURNING id",
            )
            .await,
            user: id("INSERT INTO users (discord_id, username, is_admin) VALUES ('200', 'plain_user', 0) RETURNING id")
                .await,
        }
    }

    pub async fn count(&self, sql: &str) -> i64 {
        sqlx::query_scalar(sqlx::AssertSqlSafe(sql.to_owned())).fetch_one(&self.pool).await.unwrap()
    }
}
