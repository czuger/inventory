//! Where everything lives: the project root, the database, the uploads, and the two
//! files the server mounts read-only (`config.json`, `secret_key.txt`).
//!
//! The root is the first directory, walking up from the working directory, that holds
//! `Cargo.toml`, `.git` or `README.md` (`/app` in the container, which has a README.md for
//! that purpose), unless `INVENTORY_ROOT` says otherwise.

use std::fmt::Write as _;
use std::path::{Path, PathBuf};

use serde::Deserialize;

const ROOT_MARKERS: [&str; 3] = ["Cargo.toml", ".git", "README.md"];
const DEFAULT_BIND_ADDR: &str = "0.0.0.0:8000";
const DEFAULT_DISCORD_API: &str = "https://discord.com/api";

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("project root not found (no Cargo.toml, .git or README.md above {0})")]
    RootNotFound(PathBuf),
    #[error("cannot read {path}: {source}")]
    Read { path: PathBuf, source: std::io::Error },
    #[error("cannot parse {path}: {source}")]
    Parse { path: PathBuf, source: serde_json::Error },
    #[error("cannot create {path}: {source}")]
    CreateDir { path: PathBuf, source: std::io::Error },
    #[error("cannot generate a random secret key: {0}")]
    Random(getrandom::Error),
}

/// Settings that come from the environment and the project layout. Enough to run
/// `migrate`; serving also needs [`Secrets`].
#[derive(Debug, Clone)]
pub struct Config {
    pub root: PathBuf,
    pub database_path: PathBuf,
    /// The sub-path nginx serves the app under, without slashes (`inventory`), or empty.
    pub url_prefix: String,
    pub bind_addr: String,
    pub uploads_dir: PathBuf,
    /// Where Discord's OAuth and API endpoints live (`DISCORD_API_BASE`, for tests).
    pub discord_api_base: String,
}

impl Config {
    /// Reads the process environment (after `.env`, which `main` loads).
    pub fn from_env() -> Result<Self, ConfigError> {
        let cwd = std::env::current_dir().map_err(|source| ConfigError::Read { path: ".".into(), source })?;
        Self::from_vars(|name| std::env::var(name).ok(), &cwd)
    }

    /// `from_env` with the environment and the starting directory passed in, for tests.
    pub fn from_vars(var: impl Fn(&str) -> Option<String>, cwd: &Path) -> Result<Self, ConfigError> {
        let non_empty = |name: &str| var(name).filter(|value| !value.trim().is_empty());

        let root = match non_empty("INVENTORY_ROOT") {
            Some(root) => PathBuf::from(root),
            None => find_root_from(cwd)?,
        };

        let database_path = match non_empty("DATABASE_URL") {
            Some(url) => parse_database_url(&url),
            None => {
                // Like database_url() in Python: the directory is created on demand.
                let data_dir = root.join("data");
                std::fs::create_dir_all(&data_dir)
                    .map_err(|source| ConfigError::CreateDir { path: data_dir.clone(), source })?;
                data_dir.join("inventory.sqlite3")
            }
        };

        Ok(Self {
            database_path,
            url_prefix: normalize_prefix(&var("URL_PREFIX").unwrap_or_default()),
            bind_addr: non_empty("BIND_ADDR").unwrap_or_else(|| DEFAULT_BIND_ADDR.to_owned()),
            uploads_dir: non_empty("UPLOADS_DIR")
                .map_or_else(|| root.join("data/uploads"), PathBuf::from),
            discord_api_base: non_empty("DISCORD_API_BASE")
                .map_or_else(|| DEFAULT_DISCORD_API.to_owned(), |base| base.trim_end_matches('/').to_owned()),
            root,
        })
    }
}

/// The first directory at or above `start` holding a root marker.
pub fn find_root_from(start: &Path) -> Result<PathBuf, ConfigError> {
    start
        .ancestors()
        .find(|dir| ROOT_MARKERS.iter().any(|marker| dir.join(marker).exists()))
        .map(Path::to_path_buf)
        .ok_or_else(|| ConfigError::RootNotFound(start.to_path_buf()))
}

/// Accepts the SQLAlchemy form the Python app used (`sqlite:///relative` or
/// `sqlite:////absolute`), the sqlx form (`sqlite://path`, `sqlite:path`) and a plain path.
pub fn parse_database_url(url: &str) -> PathBuf {
    let url = url.trim();
    let path = url
        .strip_prefix("sqlite:///")
        .or_else(|| url.strip_prefix("sqlite://"))
        .or_else(|| url.strip_prefix("sqlite:"))
        .unwrap_or(url);
    // sqlx-style URLs may carry options (`?mode=rwc`); the connect options set those here.
    PathBuf::from(path.split('?').next().unwrap_or(path))
}

/// `" /inventory/ "` -> `"inventory"`, as `create_app` does with `URL_PREFIX`.
pub fn normalize_prefix(prefix: &str) -> String {
    prefix.trim().trim_matches('/').to_owned()
}

#[derive(Debug, Clone, Deserialize)]
pub struct DiscordConfig {
    pub client_id: String,
    pub client_secret: String,
}

#[derive(Debug, Deserialize)]
struct ConfigFile {
    discord: DiscordConfig,
}

/// The two server-owned files: `config.json` (Discord credentials) and `secret_key.txt`
/// (the session signing key). Only `serve` needs them.
#[derive(Clone)]
pub struct Secrets {
    pub discord: DiscordConfig,
    pub secret_key: String,
}

impl std::fmt::Debug for Secrets {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Secrets").field("discord.client_id", &self.discord.client_id).finish_non_exhaustive()
    }
}

impl Secrets {
    pub fn load(root: &Path) -> Result<Self, ConfigError> {
        let path = root.join("config.json");
        let text = std::fs::read_to_string(&path).map_err(|source| ConfigError::Read { path: path.clone(), source })?;
        let file: ConfigFile = serde_json::from_str(&text).map_err(|source| ConfigError::Parse { path, source })?;
        Ok(Self { discord: file.discord, secret_key: load_secret_key(root)? })
    }
}

/// `secret_key.txt`, or a random key when it is missing — which logs every user out at
/// each restart, hence the error log (as in Python).
fn load_secret_key(root: &Path) -> Result<String, ConfigError> {
    let path = root.join("secret_key.txt");
    match std::fs::read_to_string(&path) {
        Ok(key) => {
            tracing::info!("Secret key found");
            Ok(key.trim().to_owned())
        }
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            tracing::error!("secret_key.txt not found at {}, using random secret key", path.display());
            random_hex(32)
        }
        Err(source) => Err(ConfigError::Read { path, source }),
    }
}

fn random_hex(bytes: usize) -> Result<String, ConfigError> {
    let mut buf = vec![0u8; bytes];
    getrandom::fill(&mut buf).map_err(ConfigError::Random)?;
    Ok(buf.iter().fold(String::with_capacity(bytes * 2), |mut hex, byte| {
        let _ = write!(hex, "{byte:02x}");
        hex
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn database_url_forms() {
        assert_eq!(parse_database_url("sqlite:////abs/db.sqlite3"), PathBuf::from("/abs/db.sqlite3"));
        assert_eq!(parse_database_url("sqlite:///rel/db.sqlite3"), PathBuf::from("rel/db.sqlite3"));
        assert_eq!(parse_database_url("sqlite://rel/db.sqlite3?mode=rwc"), PathBuf::from("rel/db.sqlite3"));
        assert_eq!(parse_database_url("sqlite:db.sqlite3"), PathBuf::from("db.sqlite3"));
        assert_eq!(parse_database_url("/plain/db.sqlite3"), PathBuf::from("/plain/db.sqlite3"));
    }

    #[test]
    fn prefix_is_normalized() {
        assert_eq!(normalize_prefix(" /inventory_staging/ "), "inventory_staging");
        assert_eq!(normalize_prefix(""), "");
        assert_eq!(normalize_prefix("/"), "");
    }

    #[test]
    fn root_is_found_by_marker() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("README.md"), "").unwrap();
        let nested = dir.path().join("a/b");
        std::fs::create_dir_all(&nested).unwrap();
        assert_eq!(find_root_from(&nested).unwrap(), dir.path());
    }

    #[test]
    fn defaults_and_overrides() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().to_str().unwrap().to_owned();
        let env = |name: &str| match name {
            "INVENTORY_ROOT" => Some(root.clone()),
            "URL_PREFIX" => Some("/inventory/".to_owned()),
            _ => None,
        };
        let config = Config::from_vars(env, Path::new("/")).unwrap();
        assert_eq!(config.database_path, dir.path().join("data/inventory.sqlite3"));
        assert!(dir.path().join("data").is_dir());
        assert_eq!(config.url_prefix, "inventory");
        assert_eq!(config.bind_addr, "0.0.0.0:8000");
        assert_eq!(config.uploads_dir, dir.path().join("data/uploads"));
        assert_eq!(config.discord_api_base, "https://discord.com/api");
    }

    #[test]
    fn secrets_from_files() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join("config.json"),
            r#"{"discord": {"client_id": "1", "client_secret": "s"}, "mongo": {}}"#,
        )
        .unwrap();
        std::fs::write(dir.path().join("secret_key.txt"), "abc\n").unwrap();
        let secrets = Secrets::load(dir.path()).unwrap();
        assert_eq!(secrets.discord.client_id, "1");
        assert_eq!(secrets.secret_key, "abc");
    }

    #[test]
    fn missing_secret_key_is_random() {
        let dir = tempfile::tempdir().unwrap();
        let key = load_secret_key(dir.path()).unwrap();
        assert_eq!(key.len(), 64);
        assert_ne!(key, load_secret_key(dir.path()).unwrap());
    }
}
