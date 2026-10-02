//! Flask's session, cookie-compatible: a cookie signed by one app is read by the other,
//! so nobody is logged out when the server switches, and a rollback is seamless.
//!
//! The format is itsdangerous' `URLSafeTimedSerializer` as Flask configures it
//! (`SecureCookieSessionInterface`):
//!
//! ```text
//! [.]base64url(json | zlib(json)) . base64url(timestamp) . base64url(hmac-sha1)
//! ```
//!
//! - The leading `.` marks a zlib-compressed payload, used when it saves more than a byte.
//! - The JSON is Flask's *tagged* JSON (a tuple is `{" t": [...]}`, which is how flashes
//!   are stored), compact, with sorted keys and non-ASCII escaped.
//! - The signing key is `HMAC-SHA1(secret_key, "cookie-session")`.
//! - A cookie older than 31 days (`PERMANENT_SESSION_LIFETIME`, which Flask applies to
//!   every session) or dated in the future is ignored, as is a bad signature.
//!
//! The cookie is `SameSite=Lax` (MIGRATION_PLAN.md §5.9), which Flask's was not: browsers
//! then leave it out of cross-site form posts, so another site cannot borrow, edit or
//! delete as a logged-in member.
//!
//! Values are kept in their tagged form, so whatever Flask stored (authlib's OAuth state
//! included) survives a round trip unchanged.

use std::sync::{Arc, Mutex, MutexGuard};

use axum::extract::{FromRequestParts, Request, State};
use axum::http::request::Parts;
use axum::http::{HeaderMap, HeaderValue, header};
use axum::middleware::Next;
use axum::response::Response;
use base64::Engine as _;
use base64::engine::general_purpose::{URL_SAFE_NO_PAD, URL_SAFE_NO_PAD_INDIFFERENT};
use flate2::Compression;
use flate2::read::ZlibDecoder;
use flate2::write::ZlibEncoder;
use hmac::{Hmac, KeyInit as _, Mac as _};
use serde_json::{Map, Value, json};
use sha1::Sha1;
use std::io::{Read as _, Write as _};

use crate::AppState;
use crate::error::AppError;

type HmacSha1 = Hmac<Sha1>;

const SALT: &[u8] = b"cookie-session";
/// Flask's default `PERMANENT_SESSION_LIFETIME`: 31 days.
pub const MAX_AGE_SECS: u64 = 31 * 24 * 3600;
const DEFAULT_LANG: &str = "fr";
const FLASHES: &str = "_flashes";

/// Signs and verifies session cookies with one secret key.
#[derive(Clone)]
pub struct CookieCodec {
    mac: HmacSha1,
}

impl CookieCodec {
    /// Fails only if HMAC refused the key, which it never does (it takes any length); the
    /// error is still surfaced at startup rather than turned into a panic.
    pub fn new(secret_key: &str) -> Result<Self, hmac::digest::InvalidLength> {
        // itsdangerous' "hmac" key derivation: the signing key is HMAC(secret_key, salt).
        let derived = HmacSha1::new_from_slice(secret_key.as_bytes())?.chain_update(SALT).finalize().into_bytes();
        Ok(Self { mac: HmacSha1::new_from_slice(&derived)? })
    }

    fn mac(&self) -> HmacSha1 {
        self.mac.clone()
    }

    pub fn encode(&self, data: &Map<String, Value>, now: u64) -> String {
        let json = to_python_json(data);
        let mut payload = URL_SAFE_NO_PAD.encode(json.as_bytes());
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        if encoder.write_all(json.as_bytes()).is_ok()
            && let Ok(compressed) = encoder.finish()
            && compressed.len() < json.len().saturating_sub(1)
        {
            payload = format!(".{}", URL_SAFE_NO_PAD.encode(compressed));
        }
        let value = format!("{payload}.{}", URL_SAFE_NO_PAD.encode(int_to_bytes(now)));
        let signature = self.mac().chain_update(value.as_bytes()).finalize().into_bytes();
        format!("{value}.{}", URL_SAFE_NO_PAD.encode(signature))
    }

    /// The session in `cookie`, or `None` when it is invalid, tampered with or expired.
    pub fn decode(&self, cookie: &str, now: u64) -> Option<Map<String, Value>> {
        let (value, signature) = cookie.rsplit_once('.')?;
        let signature = URL_SAFE_NO_PAD_INDIFFERENT.decode(signature).ok()?;
        self.mac().chain_update(value.as_bytes()).verify_slice(&signature).ok()?;

        let (payload, timestamp) = value.rsplit_once('.')?;
        let timestamp = bytes_to_int(&URL_SAFE_NO_PAD_INDIFFERENT.decode(timestamp).ok()?)?;
        let age = now.checked_sub(timestamp)?; // a timestamp in the future is refused
        if age > MAX_AGE_SECS {
            return None;
        }

        let (compressed, payload) = match payload.strip_prefix('.') {
            Some(rest) => (true, rest),
            None => (false, payload),
        };
        let mut json = URL_SAFE_NO_PAD_INDIFFERENT.decode(payload).ok()?;
        if compressed {
            let mut inflated = Vec::new();
            ZlibDecoder::new(json.as_slice()).read_to_end(&mut inflated).ok()?;
            json = inflated;
        }
        match serde_json::from_slice(&json).ok()? {
            Value::Object(map) => Some(map),
            _ => None,
        }
    }
}

fn int_to_bytes(value: u64) -> Vec<u8> {
    let bytes = value.to_be_bytes();
    let first = bytes.iter().position(|&b| b != 0).unwrap_or(bytes.len());
    bytes[first..].to_vec()
}

fn bytes_to_int(bytes: &[u8]) -> Option<u64> {
    if bytes.len() > 8 {
        return None;
    }
    Some(bytes.iter().fold(0u64, |acc, &b| (acc << 8) | u64::from(b)))
}

/// `json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True)`.
/// serde_json's map is sorted already (no `preserve_order`), byte order being code point
/// order; what remains is escaping everything outside ASCII as `\uXXXX`.
pub fn to_python_json(data: &Map<String, Value>) -> String {
    let json = serde_json::to_string(data).unwrap_or_else(|_| "{}".to_owned());
    let mut out = String::with_capacity(json.len());
    for c in json.chars() {
        if c.is_ascii() {
            out.push(c);
        } else {
            let mut units = [0u16; 2];
            for unit in c.encode_utf16(&mut units) {
                out.push_str(&format!("\\u{unit:04x}"));
            }
        }
    }
    out
}

/// How the cookie is named and scoped. Under a URL prefix each instance (production,
/// staging) names its cookie after the prefix and scopes its path to it, otherwise each
/// would overwrite the other's and log the user out (see `create_app`).
#[derive(Clone)]
pub struct SessionConfig {
    pub codec: CookieCodec,
    pub cookie_name: String,
    pub cookie_path: String,
}

impl SessionConfig {
    pub fn new(secret_key: &str, url_prefix: &str) -> Result<Self, hmac::digest::InvalidLength> {
        let (cookie_name, cookie_path) = if url_prefix.is_empty() {
            ("session".to_owned(), "/".to_owned())
        } else {
            let safe: String =
                url_prefix.chars().map(|c| if c.is_alphanumeric() || c == '_' { c } else { '_' }).collect();
            (format!("session_{safe}"), format!("/{url_prefix}"))
        };
        Ok(Self { codec: CookieCodec::new(secret_key)?, cookie_name, cookie_path })
    }

    fn cookie_value<'a>(&self, headers: &'a HeaderMap) -> Option<&'a str> {
        // The first cookie of that name wins, as in werkzeug.
        headers
            .get_all(header::COOKIE)
            .iter()
            .filter_map(|value| value.to_str().ok())
            .flat_map(|value| value.split(';'))
            .filter_map(|pair| pair.trim().split_once('='))
            .find(|(name, _)| *name == self.cookie_name)
            .map(|(_, value)| value.trim_matches('"'))
    }
}

#[derive(Debug, Default)]
struct SessionState {
    data: Map<String, Value>,
    modified: bool,
}

/// The current request's session. Cheap to clone; every clone sees the same data.
#[derive(Clone, Debug, Default)]
pub struct Session(Arc<Mutex<SessionState>>);

impl Session {
    pub fn from_data(data: Map<String, Value>) -> Self {
        Self(Arc::new(Mutex::new(SessionState { data, modified: false })))
    }

    fn state(&self) -> MutexGuard<'_, SessionState> {
        // A panic while holding the lock cannot leave the map half-updated; carry on.
        self.0.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn get(&self, key: &str) -> Option<Value> {
        self.state().data.get(key).cloned()
    }

    pub fn insert(&self, key: &str, value: Value) {
        let mut state = self.state();
        state.data.insert(key.to_owned(), value);
        state.modified = true;
    }

    /// Like `session.pop(key, None)`: only marks the session modified if the key was there.
    pub fn remove(&self, key: &str) -> Option<Value> {
        let mut state = self.state();
        let removed = state.data.remove(key);
        if removed.is_some() {
            state.modified = true;
        }
        removed
    }

    pub fn is_modified(&self) -> bool {
        self.state().modified
    }

    pub fn data(&self) -> Map<String, Value> {
        self.state().data.clone()
    }

    /// `session['user_id']`, when it is an integer. (A Mongo-era string id is dropped by
    /// the middleware before any handler runs.)
    pub fn user_id(&self) -> Option<i64> {
        self.get("user_id").and_then(|v| v.as_i64())
    }

    pub fn set_user_id(&self, id: i64) {
        self.insert("user_id", json!(id));
    }

    /// `session.get('lang', 'fr')`.
    pub fn lang(&self) -> String {
        match self.get("lang") {
            Some(Value::String(lang)) => lang,
            _ => DEFAULT_LANG.to_owned(),
        }
    }

    /// `flask.flash(message, category)`: stored as a tagged `(category, message)` tuple.
    pub fn flash(&self, category: &str, message: &str) {
        let mut state = self.state();
        let entry = json!({" t": [category, message]});
        match state.data.get_mut(FLASHES) {
            Some(Value::Array(flashes)) => flashes.push(entry),
            _ => {
                state.data.insert(FLASHES.to_owned(), Value::Array(vec![entry]));
            }
        }
        state.modified = true;
    }

    /// `get_flashed_messages(with_categories=True)`: pops them from the session.
    pub fn take_flashes(&self) -> Vec<(String, String)> {
        let Some(Value::Array(flashes)) = self.remove(FLASHES) else {
            return Vec::new();
        };
        flashes
            .into_iter()
            .filter_map(|entry| {
                let pair = match entry {
                    Value::Object(mut tagged) => tagged.remove(" t")?,
                    other => other,
                };
                match pair {
                    Value::Array(items) => match items.as_slice() {
                        [Value::String(category), Value::String(message)] => Some((category.clone(), message.clone())),
                        _ => None,
                    },
                    _ => None,
                }
            })
            .collect()
    }
}

impl<S: Send + Sync> FromRequestParts<S> for Session {
    type Rejection = AppError;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        parts
            .extensions
            .get::<Session>()
            .cloned()
            .ok_or_else(|| AppError::Internal("session middleware is not installed".to_owned()))
    }
}

fn unix_now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs())
}

/// Opens the session before the handler and saves it after, like Flask's
/// `open_session`/`save_session`, plus the app's `load_current_user` clean-up of
/// pre-SQLite sessions (whose `user_id` was a MongoDB ObjectId string).
pub async fn middleware(State(state): State<AppState>, mut request: Request, next: Next) -> Response {
    let config = &state.session;
    let now = unix_now();
    let data = config.cookie_value(request.headers()).and_then(|cookie| config.codec.decode(cookie, now));
    let session = Session::from_data(data.unwrap_or_default());

    if let Some(user_id) = session.get("user_id")
        && user_id.as_i64().is_none()
    {
        session.remove("user_id");
    }

    request.extensions_mut().insert(session.clone());
    let mut response = next.run(request).await;
    let unread = response.extensions().get::<crate::error::SessionUnread>().is_some();
    save(config, &session, response.headers_mut(), now, unread);
    response
}

fn save(config: &SessionConfig, session: &Session, headers: &mut HeaderMap, now: u64, unread: bool) {
    // Every request reads the session (to load the current user), so Flask always adds it —
    // except when it answered before getting that far (`SessionUnread`): then the session
    // was neither read nor cleaned up, and nothing is written back.
    if unread {
        return;
    }
    headers.append(header::VARY, HeaderValue::from_static("Cookie"));
    if !session.is_modified() {
        return;
    }
    let data = session.data();
    let cookie = if data.is_empty() {
        format!(
            "{}=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; HttpOnly; Path={}; SameSite=Lax",
            config.cookie_name, config.cookie_path
        )
    } else {
        format!(
            "{}={}; HttpOnly; Path={}; SameSite=Lax",
            config.cookie_name,
            config.codec.encode(&data, now),
            config.cookie_path
        )
    };
    match HeaderValue::from_str(&cookie) {
        Ok(value) => {
            headers.append(header::SET_COOKIE, value);
        }
        Err(err) => tracing::error!("cannot set the session cookie: {err}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Signed by Flask 3.1 with secret `test-secret`: `{'user_id': 1, 'lang': 'en',
    /// '_flashes': [('success', 'Miniature créée.')]}`.
    const FLASK_COOKIE: &str = "eyJfZmxhc2hlcyI6W3siIHQiOlsic3VjY2VzcyIsIk1pbmlhdHVyZSBjclx1MDBlOVx1MDBlOWUuIl19XSwibGFuZyI6ImVuIiwidXNlcl9pZCI6MX0.ar5zZA.yv-Qs6Q9ZwDbocOEMGjBr1mGdEk";
    /// The same flash plus twenty `('success', 'Miniature created.')`: Flask compressed it.
    const FLASK_COMPRESSED: &str = ".eJztyjEKgCAYhuGrxDdL2Jh36AQlIfZVQjj46xTdvaC9C-TyvstzYl4PJzsFZjzR5GeQ4j1FoDCEGFwuiY1PU9Ga_Vu2sJf69nSZS3XV_dVZhcPFDQaMjynCNIcFprtukxYomw.ar5zZA.wb1oyUBnCU9HSuxOToCx98JQ2_8";
    /// The timestamp both carry (`ar5zZA`).
    const SIGNED_AT: u64 = 0x6abe_7364;

    fn codec() -> CookieCodec {
        CookieCodec::new("test-secret").unwrap()
    }

    #[test]
    fn reads_a_flask_cookie() {
        let session = Session::from_data(codec().decode(FLASK_COOKIE, SIGNED_AT + 60).unwrap());
        assert_eq!(session.user_id(), Some(1));
        assert_eq!(session.lang(), "en");
        assert_eq!(session.take_flashes(), vec![("success".to_owned(), "Miniature créée.".to_owned())]);
        assert!(session.is_modified(), "popping the flashes modifies the session");
    }

    #[test]
    fn reads_a_compressed_flask_cookie() {
        let session = Session::from_data(codec().decode(FLASK_COMPRESSED, SIGNED_AT).unwrap());
        let flashes = session.take_flashes();
        assert_eq!(flashes.len(), 21);
        assert_eq!(flashes[0], ("success".to_owned(), "Miniature créée.".to_owned()));
        assert_eq!(flashes[20], ("success".to_owned(), "Miniature created.".to_owned()));
    }

    #[test]
    fn writes_what_flask_writes() {
        // Same data, same timestamp: the uncompressed cookie is byte-identical to Flask's.
        let data = codec().decode(FLASK_COOKIE, SIGNED_AT).unwrap();
        assert_eq!(codec().encode(&data, SIGNED_AT), FLASK_COOKIE);
    }

    #[test]
    fn compressed_round_trip() {
        let data = codec().decode(FLASK_COMPRESSED, SIGNED_AT).unwrap();
        let cookie = codec().encode(&data, SIGNED_AT);
        assert!(cookie.starts_with('.'));
        assert_eq!(codec().decode(&cookie, SIGNED_AT).unwrap(), data);
    }

    #[test]
    fn python_json_formatting() {
        let mut data = Map::new();
        data.insert("lang".into(), json!("fr"));
        data.insert("_flashes".into(), json!([{" t": ["success", "Créé 🎲"]}]));
        data.insert("user_id".into(), json!(7));
        assert_eq!(
            to_python_json(&data),
            "{\"_flashes\":[{\" t\":[\"success\",\"Cr\\u00e9\\u00e9 \\ud83c\\udfb2\"]}],\"lang\":\"fr\",\"user_id\":7}"
        );
    }

    #[test]
    fn rejects_bad_signatures_and_age() {
        let codec = codec();
        assert!(codec.decode(FLASK_COOKIE, SIGNED_AT + MAX_AGE_SECS).is_some());
        assert!(codec.decode(FLASK_COOKIE, SIGNED_AT + MAX_AGE_SECS + 1).is_none(), "expired");
        assert!(codec.decode(FLASK_COOKIE, SIGNED_AT - 1).is_none(), "from the future");
        assert!(CookieCodec::new("other-secret").unwrap().decode(FLASK_COOKIE, SIGNED_AT).is_none());
        let tampered = FLASK_COOKIE.replacen("eyJf", "eyJg", 1);
        assert!(codec.decode(&tampered, SIGNED_AT).is_none());
        assert!(codec.decode("garbage", SIGNED_AT).is_none());
        assert!(codec.decode("", SIGNED_AT).is_none());
    }

    #[test]
    fn remove_only_modifies_when_present() {
        let session = Session::default();
        assert_eq!(session.remove("user_id"), None);
        assert!(!session.is_modified());
        session.set_user_id(3);
        assert!(session.is_modified());
    }

    #[test]
    fn cookie_name_and_path_follow_the_prefix() {
        let root = SessionConfig::new("k", "").unwrap();
        assert_eq!((root.cookie_name.as_str(), root.cookie_path.as_str()), ("session", "/"));
        let staging = SessionConfig::new("k", "inventory-staging").unwrap();
        assert_eq!(staging.cookie_name, "session_inventory_staging");
        assert_eq!(staging.cookie_path, "/inventory-staging");
    }
}
