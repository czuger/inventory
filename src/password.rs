//! Username/password accounts (MIGRATION_PLAN.md §5.9): argon2id hashes, the sign-up
//! rules, and a per-client limit on login and sign-up attempts.

use std::collections::{HashMap, VecDeque};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use argon2::Argon2;
use argon2::password_hash::phc::PasswordHash;
use argon2::password_hash::{PasswordHasher, PasswordVerifier};

use crate::error::AppError;

pub const LOGIN_MIN: usize = 3;
pub const LOGIN_MAX: usize = 32;
pub const PASSWORD_MIN: usize = 8;
pub const PASSWORD_MAX: usize = 128;

/// argon2id with the crate's defaults, as a PHC string (`$argon2id$v=19$...`). CPU-heavy
/// on purpose, so it runs off the async threads.
pub async fn hash(password: &str) -> Result<String, AppError> {
    let password = password.to_owned();
    tokio::task::spawn_blocking(move || {
        Argon2::default().hash_password(password.as_bytes()).map(|hash| hash.to_string())
    })
    .await
    .map_err(|err| AppError::Internal(format!("hashing task: {err}")))?
    .map_err(|err| AppError::Internal(format!("hashing: {err}")))
}

/// A hash nobody's password matches, checked when the login name is unknown so that the
/// answer takes as long as for a wrong password.
static DUMMY_HASH: LazyLock<Option<String>> =
    LazyLock::new(|| Argon2::default().hash_password(b"no account has this password").ok().map(|h| h.to_string()));

/// Whether `password` matches `stored` (`None`: an unknown login or an account without a
/// password, which never matches but costs the same time).
pub async fn verify(password: &str, stored: Option<&str>) -> bool {
    let password = password.to_owned();
    let stored = stored.map(str::to_owned);
    let result = tokio::task::spawn_blocking(move || {
        let known = stored.is_some();
        let Some(hash) = stored.or_else(|| DUMMY_HASH.clone()) else { return false };
        let matches = PasswordHash::new(&hash)
            .is_ok_and(|parsed| Argon2::default().verify_password(password.as_bytes(), &parsed).is_ok());
        known && matches
    })
    .await;
    result.unwrap_or(false)
}

/// Why a sign-up was refused: each is a key of the translations.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refusal {
    UsernameInvalid,
    UsernameTaken,
    PasswordTooShort,
    PasswordsMismatch,
}

impl Refusal {
    pub fn message_key(self) -> &'static str {
        match self {
            Self::UsernameInvalid => "username_invalid",
            Self::UsernameTaken => "username_taken",
            Self::PasswordTooShort => "password_too_short",
            Self::PasswordsMismatch => "passwords_mismatch",
        }
    }
}

/// The login name, trimmed: 3 to 32 letters, digits, `_`, `.` or `-`.
pub fn check_login(login: &str) -> Result<String, Refusal> {
    let login = login.trim();
    let length = login.chars().count();
    let allowed = login.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-'));
    if (LOGIN_MIN..=LOGIN_MAX).contains(&length) && allowed {
        Ok(login.to_owned())
    } else {
        Err(Refusal::UsernameInvalid)
    }
}

/// 8 to 128 characters, typed the same twice.
pub fn check_password(password: &str, confirm: &str) -> Result<(), Refusal> {
    let length = password.chars().count();
    if !(PASSWORD_MIN..=PASSWORD_MAX).contains(&length) {
        return Err(Refusal::PasswordTooShort);
    }
    if password != confirm {
        return Err(Refusal::PasswordsMismatch);
    }
    Ok(())
}

/// At most `limit` attempts per client within `window` (a sliding window, in memory: the
/// app runs as one process).
pub struct RateLimiter {
    limit: usize,
    window: Duration,
    attempts: Mutex<HashMap<String, VecDeque<Instant>>>,
}

impl RateLimiter {
    pub fn new(limit: usize, window: Duration) -> Self {
        Self { limit, window, attempts: Mutex::new(HashMap::new()) }
    }

    /// Records an attempt by `client`; `false` if it is over the limit.
    pub fn allow(&self, client: &str) -> bool {
        let now = Instant::now();
        let mut attempts = self.attempts.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        // Forget clients that have been quiet for a whole window, so the map stays small.
        attempts.retain(|_, times| times.back().is_some_and(|last| now.duration_since(*last) < self.window));
        let times = attempts.entry(client.to_owned()).or_default();
        while times.front().is_some_and(|first| now.duration_since(*first) >= self.window) {
            times.pop_front();
        }
        if times.len() >= self.limit {
            return false;
        }
        times.push_back(now);
        true
    }
}

impl Default for RateLimiter {
    /// 10 attempts a minute across login and sign-up.
    fn default() -> Self {
        Self::new(10, Duration::from_secs(60))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn hashes_verify() {
        let hashed = hash("correct horse").await.unwrap();
        assert!(hashed.starts_with("$argon2id$v=19$"));
        assert!(verify("correct horse", Some(&hashed)).await);
        assert!(!verify("wrong horse", Some(&hashed)).await);
        assert!(!verify("correct horse", None).await);
        assert!(!verify("correct horse", Some("not a hash")).await);
        assert_ne!(hashed, hash("correct horse").await.unwrap(), "salted");
    }

    #[test]
    fn sign_up_rules() {
        assert_eq!(check_login("  jean.dupont-2 "), Ok("jean.dupont-2".to_owned()));
        for bad in ["ab", "", "jean dupont", "élodie", "a".repeat(33).as_str(), "x/y"] {
            assert_eq!(check_login(bad), Err(Refusal::UsernameInvalid), "{bad:?}");
        }
        assert_eq!(check_password("short", "short"), Err(Refusal::PasswordTooShort));
        assert_eq!(check_password(&"x".repeat(129), &"x".repeat(129)), Err(Refusal::PasswordTooShort));
        assert_eq!(check_password("long enough", "long enougH"), Err(Refusal::PasswordsMismatch));
        assert_eq!(check_password("éléphant", "éléphant"), Ok(()));
    }

    #[test]
    fn limits_per_client() {
        let limiter = RateLimiter::new(3, Duration::from_secs(60));
        assert!((0..3).all(|_| limiter.allow("a")));
        assert!(!limiter.allow("a"));
        assert!(limiter.allow("b"), "per client");
        let quick = RateLimiter::new(1, Duration::from_millis(1));
        assert!(quick.allow("a"));
        std::thread::sleep(Duration::from_millis(5));
        assert!(quick.allow("a"), "the window slides");
    }
}
