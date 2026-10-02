//! Discord login (`routes/auth.py`, which used authlib): the OAuth2 authorization-code
//! flow with the `identify` scope, then the user is found or created by Discord id.
//!
//! The state is kept in the session the way authlib kept it
//! (`_state_discord_<state>` → `{"data": {"redirect_uri", "url"}, "exp"}`), so a login
//! started on one app can finish on the other while both run.
//!
//! Username/password login and sign-up (MIGRATION_PLAN.md §5.9) live here too: the login
//! page offers both ways in.

use axum::Router;
use axum::extract::{RawQuery, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde::Deserialize;
use serde_json::{Value, json};

use crate::AppState;
use crate::db::{refs, users};
use crate::error::AppError;
use crate::extract::FormData;
use crate::password::{self, Refusal};
use crate::session::Session;
use crate::templates::Page;
use crate::urls::UrlContext;
use crate::web::redirect;

const STATE_PREFIX: &str = "_state_discord_";
/// authlib's state lifetime.
const STATE_TTL_SECS: f64 = 3600.0;

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/auth/discord", get(login))
        .route("/auth/discord/callback", get(callback))
        .route("/auth/logout", get(logout))
        .route("/auth/login", get(signin_form).post(signin))
        .route("/auth/register", get(register_form).post(register))
}

fn now() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0.0, |d| d.as_secs_f64())
}

/// authlib's `generate_token(30)`: letters and digits.
fn state_token() -> Result<String, AppError> {
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let mut bytes = [0u8; 30];
    getrandom::fill(&mut bytes).map_err(|err| AppError::Internal(format!("no randomness: {err}")))?;
    Ok(bytes.iter().map(|b| char::from(ALPHABET[usize::from(*b) % ALPHABET.len()])).collect())
}

/// `urlencode`'s `quote_plus` with nothing kept as safe: only letters, digits and `_.-~`
/// pass through (so `:` and `/` are escaped too), and a space is `+`.
fn quote_plus(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for &byte in value.as_bytes() {
        match byte {
            b' ' => out.push('+'),
            b if b.is_ascii_alphanumeric() || b"_.-~".contains(&b) => out.push(char::from(b)),
            b => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// `/auth/discord`: off to Discord, which comes back to the callback.
async fn login(State(state): State<AppState>, headers: HeaderMap, session: Session) -> Result<Response, AppError> {
    let discord = state.discord.as_ref().ok_or_else(|| AppError::Internal("Discord is not configured".into()))?;
    let redirect_uri =
        UrlContext::from_request(&headers, &state.config.url_prefix).external_url_for("auth.callback", &[])?;
    tracing::info!("OAuth callback URL: {redirect_uri}");
    let token = state_token()?;
    let url = format!(
        "{}/oauth2/authorize?response_type=code&client_id={}&redirect_uri={}&scope=identify&state={token}",
        state.config.discord_api_base,
        quote_plus(&discord.client_id),
        quote_plus(&redirect_uri),
    );
    session.insert(
        &format!("{STATE_PREFIX}{token}"),
        json!({"data": {"redirect_uri": redirect_uri, "url": url}, "exp": now() + STATE_TTL_SECS}),
    );
    Ok(redirect(&url))
}

#[derive(Deserialize)]
struct TokenResponse {
    access_token: String,
}

#[derive(Deserialize)]
struct DiscordUser {
    id: Value,
    username: String,
    global_name: Option<String>,
}

/// The state's `redirect_uri` if the state is ours and still valid. Like authlib, drops
/// it from the session either way, along with any expired ones.
fn take_state(session: &Session, token: Option<&str>) -> Option<String> {
    let data = token.and_then(|token| session.remove(&format!("{STATE_PREFIX}{token}")));
    let now = now();
    let expired: Vec<String> = session
        .data()
        .iter()
        .filter(|(key, value)| key.starts_with(STATE_PREFIX) && value["exp"].as_f64().is_none_or(|exp| exp < now))
        .map(|(key, _)| key.clone())
        .collect();
    for key in expired {
        session.remove(&key);
    }
    let data = data?;
    if data["exp"].as_f64().is_none_or(|exp| exp < now) {
        return None;
    }
    data["data"]["redirect_uri"].as_str().map(str::to_owned)
}

/// Exchanges the code and asks Discord who the user is.
async fn fetch_discord_user(state: &AppState, code: &str, redirect_uri: &str) -> Result<DiscordUser, String> {
    let discord = state.discord.as_ref().ok_or("Discord is not configured")?;
    let base = &state.config.discord_api_base;
    let token: TokenResponse = state
        .http
        .post(format!("{base}/oauth2/token"))
        .basic_auth(&discord.client_id, Some(&discord.client_secret))
        .form(&[("grant_type", "authorization_code"), ("code", code), ("redirect_uri", redirect_uri)])
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|err| format!("token exchange: {err}"))?
        .json()
        .await
        .map_err(|err| format!("token response: {err}"))?;
    state
        .http
        .get(format!("{base}/users/@me"))
        .bearer_auth(&token.access_token)
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|err| format!("users/@me: {err}"))?
        .json()
        .await
        .map_err(|err| format!("users/@me response: {err}"))
}

/// `/auth/discord/callback`. Python answered every failure here with a 500 (a refused
/// consent, a stale state, Discord down); this goes back home with a message instead.
async fn callback(
    State(state): State<AppState>,
    headers: HeaderMap,
    session: Session,
    RawQuery(query): RawQuery,
) -> Result<Response, AppError> {
    let urls = UrlContext::from_request(&headers, &state.config.url_prefix);
    let home = urls.url_for("index", &[])?;
    let login_page = urls.url_for("auth.signin", &[])?;
    let args = FormData::parse(query.unwrap_or_default().as_bytes());
    let failed = |reason: &str| {
        tracing::warn!("Discord login failed: {reason}");
        session.flash("danger", "Discord login failed.");
        Ok(redirect(&login_page))
    };

    let redirect_uri = take_state(&session, args.get("state"));
    if let Some(error) = args.get("error") {
        return failed(&format!("Discord answered {error}"));
    }
    let Some(redirect_uri) = redirect_uri else { return failed("unknown or expired state") };
    let Some(code) = args.get("code") else { return failed("no code") };
    let info = match fetch_discord_user(&state, code, &redirect_uri).await {
        Ok(info) => info,
        Err(reason) => return failed(&reason),
    };

    let discord_id = match &info.id {
        Value::String(id) => id.clone(),
        other => other.to_string(),
    };
    let display_name = info.global_name.as_deref().filter(|name| !name.is_empty());
    let id = match users::find_by_discord_id(&state.pool, &discord_id).await? {
        None => users::insert_discord_user(&state.pool, &discord_id, &info.username, display_name).await?,
        Some(user) => {
            if user.username != info.username || user.display_name.as_deref() != display_name {
                users::update_names(&state.pool, user.id, &info.username, display_name).await?;
            }
            user.id
        }
    };
    session.set_user_id(id);
    Ok(redirect(&home))
}

/// `/auth/logout`.
async fn logout(State(state): State<AppState>, headers: HeaderMap, session: Session) -> Result<Response, AppError> {
    session.remove("user_id");
    Ok(redirect(&UrlContext::from_request(&headers, &state.config.url_prefix).url_for("index", &[])?))
}

/// The client a login attempt counts against: `X-Real-IP`, which nginx sets from the
/// connection and a client cannot forge (unlike the first `X-Forwarded-For` entry).
fn client_key(headers: &HeaderMap) -> String {
    headers.get("x-real-ip").and_then(|v| v.to_str().ok()).unwrap_or("local").to_owned()
}

/// The login and sign-up pages are not under an association, but the navbar links to one:
/// the first, as `/` does.
async fn page_for_auth(state: &AppState, page: Page) -> Result<Page, AppError> {
    let slug = refs::first_association_slug(&state.pool).await?.unwrap_or_default();
    Ok(page.with_slug(&slug))
}

/// A login or sign-up page, with a refusal (400) or without (200).
async fn auth_page(
    state: &AppState,
    page: Page,
    template: &str,
    username: &str,
    refusal: Option<&str>,
) -> Result<Response, AppError> {
    let page = page_for_auth(state, page).await?;
    let html = page.render(template, Some("auth"), minijinja::context! { username => username, error => refusal })?;
    let status = if refusal.is_some() { StatusCode::BAD_REQUEST } else { StatusCode::OK };
    Ok((status, html).into_response())
}

async fn signin_form(State(state): State<AppState>, page: Page) -> Result<Response, AppError> {
    auth_page(&state, page, "auth/login.html", "", None).await
}

/// `POST /auth/login`. One message for every failure, so it does not tell which names exist.
async fn signin(
    State(state): State<AppState>,
    headers: HeaderMap,
    page: Page,
    form: crate::extract::FormData,
) -> Result<Response, AppError> {
    let username = form.get("username").unwrap_or_default().trim().to_owned();
    if !state.login_limiter.allow(&client_key(&headers)) {
        return auth_page(&state, page, "auth/login.html", &username, Some("too_many_attempts"))
            .await
            .map(|response| (StatusCode::TOO_MANY_REQUESTS, response).into_response());
    }
    let user = if username.is_empty() { None } else { users::find_by_login(&state.pool, &username).await? };
    let password = form.get("password").unwrap_or_default();
    if !password::verify(password, user.as_ref().and_then(|u| u.password_hash.as_deref())).await {
        return auth_page(&state, page, "auth/login.html", &username, Some("invalid_credentials")).await;
    }
    let Some(user) = user else { return Err(AppError::Internal("verified without a user".into())) };
    page.session().set_user_id(user.id);
    Ok(redirect(&UrlContext::from_request(&headers, &state.config.url_prefix).url_for("index", &[])?))
}

async fn register_form(State(state): State<AppState>, page: Page) -> Result<Response, AppError> {
    auth_page(&state, page, "auth/register.html", "", None).await
}

/// `POST /auth/register`: a new, non-admin account, logged in straight away.
async fn register(
    State(state): State<AppState>,
    headers: HeaderMap,
    page: Page,
    form: crate::extract::FormData,
) -> Result<Response, AppError> {
    let typed = form.get("username").unwrap_or_default().trim().to_owned();
    if !state.login_limiter.allow(&client_key(&headers)) {
        return auth_page(&state, page, "auth/register.html", &typed, Some("too_many_attempts"))
            .await
            .map(|response| (StatusCode::TOO_MANY_REQUESTS, response).into_response());
    }
    let refuse = |refusal: Refusal| refusal.message_key();
    let login = match password::check_login(&typed) {
        Ok(login) => login,
        Err(refusal) => return auth_page(&state, page, "auth/register.html", &typed, Some(refuse(refusal))).await,
    };
    let (password, confirm) =
        (form.get("password").unwrap_or_default(), form.get("password_confirm").unwrap_or_default());
    if let Err(refusal) = password::check_password(password, confirm) {
        return auth_page(&state, page, "auth/register.html", &login, Some(refuse(refusal))).await;
    }
    if users::find_by_login(&state.pool, &login).await?.is_some() {
        return auth_page(&state, page, "auth/register.html", &login, Some(refuse(Refusal::UsernameTaken))).await;
    }
    let hash = password::hash(password).await?;
    let id = match users::insert_password_user(&state.pool, &login, &hash).await {
        Ok(id) => id,
        // Taken between the check and the insert.
        Err(sqlx::Error::Database(err)) if err.is_unique_violation() => {
            return auth_page(&state, page, "auth/register.html", &login, Some(refuse(Refusal::UsernameTaken))).await;
        }
        Err(err) => return Err(err.into()),
    };
    page.session().set_user_id(id);
    Ok(redirect(&UrlContext::from_request(&headers, &state.config.url_prefix).url_for("index", &[])?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quoting_like_urlencode() {
        // urlencode({'redirect_uri': ...}) as authlib built it.
        assert_eq!(
            quote_plus("https://apps.ieroe.com/inventory/auth/discord/callback"),
            "https%3A%2F%2Fapps.ieroe.com%2Finventory%2Fauth%2Fdiscord%2Fcallback"
        );
        assert_eq!(quote_plus("a b!*'(),;"), "a+b%21%2A%27%28%29%2C%3B");
    }

    #[test]
    fn state_tokens() {
        let token = state_token().unwrap();
        assert_eq!(token.len(), 30);
        assert!(token.chars().all(|c| c.is_ascii_alphanumeric()));
    }
}
