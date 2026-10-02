//! The club inventory web app ("Les Grognards d'Alsace"), ported from Flask.
//! `MIGRATION_PLAN.md` at the repository root tracks the port.

pub mod config;
pub mod db;
pub mod error;
pub mod extract;
pub mod handlers;
pub mod kinds;
pub mod labels;
pub mod migrate;
pub mod password;
pub mod pdf;
pub mod session;
pub mod templates;
pub mod upload;
pub mod urls;
pub mod web;

use std::sync::Arc;

use axum::Router;
use axum::routing::{any, get, get_service};
use sqlx::SqlitePool;
use tower::ServiceBuilder;
use tower_http::services::ServeDir;
use tower_http::trace::TraceLayer;

use crate::config::{Config, DiscordConfig};
use crate::kinds::ItemKind;
use crate::session::SessionConfig;
use crate::templates::{Templates, TemplatesError};

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub pool: SqlitePool,
    pub session: Arc<SessionConfig>,
    pub templates: Arc<Templates>,
    /// The Discord application; without it, login answers a 500.
    pub discord: Option<Arc<DiscordConfig>>,
    pub http: reqwest::Client,
    /// Login and sign-up attempts per client.
    pub login_limiter: Arc<password::RateLimiter>,
}

#[derive(Debug, thiserror::Error)]
pub enum InitError {
    #[error("the secret key cannot be used to sign sessions")]
    SecretKey,
    #[error(transparent)]
    Templates(#[from] TemplatesError),
}

impl AppState {
    pub fn new(config: Config, secret_key: &str, pool: SqlitePool) -> Result<Self, InitError> {
        let session = SessionConfig::new(secret_key, &config.url_prefix).map_err(|_| InitError::SecretKey)?;
        Ok(Self {
            config: Arc::new(config),
            pool,
            session: Arc::new(session),
            templates: Arc::new(Templates::new()?),
            discord: None,
            http: reqwest::Client::new(),
            login_limiter: Arc::new(password::RateLimiter::default()),
        })
    }

    pub fn with_discord(mut self, discord: DiscordConfig) -> Self {
        self.discord = Some(Arc::new(discord));
        self
    }
}

/// The whole application; `main` serves it and the integration tests call it directly.
pub fn build_app(state: AppState) -> Router {
    let uploads =
        ServeDir::new(&state.config.uploads_dir).not_found_service(get(handlers::app::not_found).with_state(()));

    let mut router = Router::new()
        .route("/", get(handlers::app::index))
        .route("/health", get(handlers::app::health))
        .route("/set-language/{lang}", get(handlers::app::set_language))
        .merge(handlers::auth::routes())
        .nest_service(
            "/static/uploads",
            get_service(uploads).layer(axum::middleware::from_fn(handlers::app::upload_disposition)),
        )
        .route("/static/{*path}", get(handlers::app::static_file))
        .route("/{slug}/print", any(web::add_trailing_slash));
    for kind in ItemKind::ALL {
        router = router
            .route(&format!("/{{slug}}/{}", kind.segment()), any(web::add_trailing_slash))
            .merge(handlers::items::routes(kind))
            .merge(handlers::borrow::routes(kind))
            .merge(handlers::images::routes(kind))
            .merge(handlers::duplicates::routes(kind))
            .merge(handlers::print::sticker_routes(kind));
    }
    router = router.merge(handlers::print::print_routes());

    let routes = router.fallback(handlers::app::not_found).with_state(state.clone());

    // Wrapped around the router as a whole, not added with `Router::layer` (which wraps each
    // route): axum completes some responses after a route's own layers ran (the `Allow`
    // header of a 405), and these layers must see the final response.
    let app = ServiceBuilder::new()
        .layer(TraceLayer::new_for_http())
        .layer(axum::middleware::from_fn_with_state(state, session::middleware))
        .layer(axum::middleware::from_fn(web::werkzeug_compat))
        .service(routes);
    Router::new().fallback_service(app)
}
