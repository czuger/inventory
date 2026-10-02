//! Request extractors standing in for Flask's `g`: who is logged in, and (later) which
//! association the URL names.

use std::sync::Arc;

use axum::extract::FromRequestParts;
use axum::http::request::Parts;

use crate::AppState;
use crate::db::{models::User, users};
use crate::error::AppError;
use crate::session::Session;

/// `g.current_user`: the user whose id is in the session, if it still exists. Loaded at
/// most once per request, and only by handlers that ask for it.
#[derive(Debug, Clone)]
pub struct CurrentUser(pub Option<Arc<User>>);

impl CurrentUser {
    pub fn user(&self) -> Option<&User> {
        self.0.as_deref()
    }

    pub fn is_admin(&self) -> bool {
        self.user().is_some_and(|user| user.is_admin)
    }
}

impl FromRequestParts<AppState> for CurrentUser {
    type Rejection = AppError;

    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, Self::Rejection> {
        if let Some(cached) = parts.extensions.get::<CurrentUser>() {
            return Ok(cached.clone());
        }
        let session = Session::from_request_parts(parts, state).await?;
        let user = match session.user_id() {
            Some(id) => users::find(&state.pool, id).await?.map(Arc::new),
            None => None,
        };
        let current = CurrentUser(user);
        parts.extensions.insert(current.clone());
        Ok(current)
    }
}

/// `request.form`: the urlencoded body as `(name, value)` pairs in order. Like werkzeug,
/// a body that is not a form is an empty form (so a missing field is a 400, not a 415),
/// and `form[name]` is the first value.
#[derive(Debug, Clone, Default)]
pub struct FormData(pub Vec<(String, String)>);

impl FormData {
    pub fn parse(body: &[u8]) -> Self {
        Self(form_urlencoded::parse(body).map(|(k, v)| (k.into_owned(), v.into_owned())).collect())
    }

    /// `request.form.get(name)`.
    pub fn get(&self, name: &str) -> Option<&str> {
        self.0.iter().find(|(key, _)| key == name).map(|(_, value)| value.as_str())
    }

    /// `request.form[name]`: a missing field is werkzeug's 400.
    pub fn require(&self, name: &str) -> Result<&str, AppError> {
        self.get(name).ok_or(AppError::BadRequest)
    }

    /// `name in request.form` (a ticked checkbox).
    pub fn contains(&self, name: &str) -> bool {
        self.get(name).is_some()
    }
}

impl<S: Send + Sync> axum::extract::FromRequest<S> for FormData {
    type Rejection = AppError;

    async fn from_request(request: axum::extract::Request, state: &S) -> Result<Self, Self::Rejection> {
        let is_form = request
            .headers()
            .get(axum::http::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .is_some_and(|value| value.starts_with("application/x-www-form-urlencoded"));
        let body = axum::body::Bytes::from_request(request, state).await.map_err(|_| AppError::BadRequest)?;
        Ok(if is_form { Self::parse(&body) } else { Self::default() })
    }
}

/// Python's `int(text)`: surrounding whitespace, a sign and `_` between digits allowed.
pub fn py_int(text: &str) -> Option<i64> {
    let text = text.trim();
    let (negative, digits) = match text.as_bytes().first() {
        Some(b'-') => (true, &text[1..]),
        Some(b'+') => (false, &text[1..]),
        _ => (false, text),
    };
    let well_formed = !digits.is_empty()
        && !digits.starts_with('_')
        && !digits.ends_with('_')
        && !digits.contains("__")
        && digits.chars().all(|c| c.is_ascii_digit() || c == '_');
    if !well_formed {
        return None;
    }
    let value: i64 = digits.replace('_', "").parse().ok()?;
    Some(if negative { -value } else { value })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_int() {
        assert_eq!(py_int("3"), Some(3));
        assert_eq!(py_int(" 007 "), Some(7));
        assert_eq!(py_int("-2"), Some(-2));
        assert_eq!(py_int("+1_000"), Some(1000));
        for bad in ["", " ", "1.5", "abc", "_1", "1_", "1__0", "--1", "0x10"] {
            assert_eq!(py_int(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn form_first_value_wins() {
        let form = FormData::parse(b"type=Infantry&type=Cavalry&note=a+b%C3%A9&flag=");
        assert_eq!(form.get("type"), Some("Infantry"));
        assert_eq!(form.get("note"), Some("a bé"));
        assert!(form.contains("flag"));
        assert!(matches!(form.require("missing"), Err(AppError::BadRequest)));
    }
}
