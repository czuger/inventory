use std::net::{Ipv4Addr, SocketAddr};
use std::process::ExitCode;
use std::time::Duration;

use anyhow::Context as _;
use clap::{Parser, Subcommand};
use tracing_subscriber::EnvFilter;

use inventory::config::{Config, Secrets};
use inventory::db::users;
use inventory::{AppState, build_app, db, listen, migrate, password, seed};

#[derive(Parser)]
#[command(about = "The club inventory web app")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Serve the app on SOCKET_PATH, or BIND_ADDR without one (the default command)
    Serve,
    /// Back up the database, then apply the pending migrations
    Migrate,
    /// Load the club inventory into a fresh, migrated database (never one that holds data)
    Seed {
        /// A seed file to load instead of the built-in misc/grognards_seed.json
        #[arg(long)]
        file: Option<std::path::PathBuf>,
    },
    /// Exit 0 if the server on SOCKET_PATH or BIND_ADDR answers /health (the deploy's health probe)
    Healthcheck,
    /// Grant (or revoke) admin rights; the user must have logged in at least once
    SetAdmin {
        /// The user's username, as shown in the navbar
        username: String,
        /// Revoke instead of granting
        #[arg(long)]
        revoke: bool,
    },
    /// Give a user a password (prompted twice), so they can log in without Discord
    SetPassword {
        /// The user's username, as shown in the navbar
        username: String,
        /// The name to log in with (default: the one they have, or their username)
        #[arg(long)]
        login: Option<String>,
    },
}

#[tokio::main]
async fn main() -> ExitCode {
    let _ = dotenvy::dotenv();
    tracing_subscriber::fmt()
        // Colours only on a terminal: `make logs` reads the unit's plain output from journald.
        .with_ansi(std::io::IsTerminal::is_terminal(&std::io::stdout()))
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info,sqlx=warn")))
        .init();

    let result = match Cli::parse().command.unwrap_or(Command::Serve) {
        Command::Serve => serve().await,
        Command::Migrate => run_migrations().await,
        Command::Seed { file } => run_seed(file.as_deref()).await,
        Command::Healthcheck => healthcheck().await,
        Command::SetAdmin { username, revoke } => set_admin(&username, !revoke).await,
        Command::SetPassword { username, login } => set_password(&username, login.as_deref()).await,
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("error: {err:#}");
            ExitCode::FAILURE
        }
    }
}

async fn serve() -> anyhow::Result<()> {
    let config = Config::from_env()?;
    // Read at startup, as the Flask app did, so a missing config.json fails the deploy's
    // health check instead of the first login.
    let secrets = Secrets::load(&config.root)?;
    let pool = db::connect(&config.database_path)
        .await
        .with_context(|| format!("cannot open {}", config.database_path.display()))?;

    let state = AppState::new(config.clone(), &secrets.secret_key, pool.clone())?.with_discord(secrets.discord);
    let app = build_app(state);
    listen::serve(app, &config).await.with_context(|| match &config.socket_path {
        Some(path) => format!("cannot serve on {}", path.display()),
        None => format!("cannot serve on {}", config.bind_addr),
    })?;
    pool.close().await;
    Ok(())
}

async fn run_migrations() -> anyhow::Result<()> {
    let config = Config::from_env()?;
    let report = migrate::run(&config.database_path)
        .await
        .with_context(|| format!("migrating {}", config.database_path.display()))?;
    if report.baselined {
        println!("recorded the Alembic-built schema as migration 0001");
    }
    if let Some(backup) = &report.backup {
        println!("backed up to {}", backup.display());
    }
    let previous = report.previous.map_or_else(|| "an empty database".to_owned(), |v| format!("{v:04}"));
    match report.applied.last() {
        Some(head) => println!("migrated {previous} -> {head:04}"),
        None => println!("database at {previous}, nothing to migrate"),
    }
    Ok(())
}

async fn run_seed(file: Option<&std::path::Path>) -> anyhow::Result<()> {
    let json = match file {
        Some(path) => std::fs::read_to_string(path).with_context(|| format!("cannot read {}", path.display()))?,
        None => seed::GROGNARDS.to_owned(),
    };
    let data = seed::parse(&json)?;
    let config = Config::from_env()?;
    let pool = db::connect(&config.database_path).await?;
    let summary =
        seed::seed(&pool, &data).await.with_context(|| format!("seeding {}", config.database_path.display()))?;
    pool.close().await;
    let items: Vec<String> = summary.items.iter().map(|(kind, n)| format!("{n} {}", kind.table())).collect();
    println!(
        "seeded '{}': {} locations, {} games, {}",
        summary.association,
        summary.locations,
        summary.games,
        items.join(", ")
    );
    Ok(())
}

/// Asks the server on SOCKET_PATH, or BIND_ADDR without one, for /health.
async fn healthcheck() -> anyhow::Result<()> {
    let probe = async {
        if let Some(path) = std::env::var_os("SOCKET_PATH").filter(|path| !path.is_empty()) {
            let stream = tokio::net::UnixStream::connect(&path)
                .await
                .with_context(|| format!("cannot reach unix:{}", path.display()))?;
            return Ok(listen::get_health(stream).await?);
        }
        let bind = std::env::var("BIND_ADDR").unwrap_or_else(|_| "0.0.0.0:8000".to_owned());
        let mut addr: SocketAddr = bind.parse().with_context(|| format!("BIND_ADDR {bind:?} is not an ip:port"))?;
        if addr.ip().is_unspecified() {
            addr.set_ip(Ipv4Addr::LOCALHOST.into());
        }
        let stream = tokio::net::TcpStream::connect(addr).await.with_context(|| format!("cannot reach {addr}"))?;
        anyhow::Ok(listen::get_health(stream).await?)
    };
    let status_line = tokio::time::timeout(Duration::from_secs(3), probe).await.context("timed out")??;
    anyhow::ensure!(status_line.split(' ').nth(1) == Some("200"), "unhealthy: {status_line}");
    Ok(())
}

/// The one user with this display name; an error when there is none, or several.
async fn user_named(pool: &sqlx::SqlitePool, username: &str) -> anyhow::Result<inventory::db::models::User> {
    let mut matches = users::find_by_username(pool, username).await?;
    match matches.len() {
        0 => anyhow::bail!(
            "No user found with username '{username}'.\n\
             Users must log in (or sign up) at least once before being granted anything."
        ),
        1 => Ok(matches.remove(0)),
        n => anyhow::bail!(
            "{n} users are named '{username}' (ids {}); refusing to guess.",
            matches.iter().map(|u| u.id.to_string()).collect::<Vec<_>>().join(", ")
        ),
    }
}

/// How a user is identified in messages.
fn describe(user: &inventory::db::models::User) -> String {
    match (&user.discord_id, &user.login) {
        (Some(discord_id), _) => format!("discord_id: {discord_id}"),
        (None, Some(login)) => format!("login: {login}"),
        (None, None) => format!("id: {}", user.id),
    }
}

/// `misc/set_admin.py`: the only way to get the first admin, since no page grants it.
async fn set_admin(username: &str, admin: bool) -> anyhow::Result<()> {
    let config = Config::from_env()?;
    let pool = db::connect(&config.database_path).await?;
    let user = user_named(&pool, username).await?;
    users::set_admin(&pool, user.id, admin).await?;
    let action = if admin { "granted" } else { "revoked" };
    println!("Admin {action} for '{username}' ({}).", describe(&user));
    pool.close().await;
    Ok(())
}

/// Gives a user (a Discord member included) a password, prompted twice and never echoed.
async fn set_password(username: &str, login: Option<&str>) -> anyhow::Result<()> {
    let config = Config::from_env()?;
    let pool = db::connect(&config.database_path).await?;
    let user = user_named(&pool, username).await?;

    let wanted = login.map(str::to_owned).or_else(|| user.login.clone()).unwrap_or_else(|| user.username.clone());
    let login = password::check_login(&wanted)
        .map_err(|_| anyhow::anyhow!("'{wanted}' cannot be a login: 3 to 32 letters, digits, '_', '.' or '-'"))?;
    if let Some(other) = users::find_by_login(&pool, &login).await?
        && other.id != user.id
    {
        anyhow::bail!("the login '{login}' is already used by user {}", other.id);
    }

    let no_terminal = "typing the password needs a terminal (over SSH: `ssh -t`)";
    let typed = rpassword::prompt_password(format!("New password for '{username}': ")).context(no_terminal)?;
    let again = rpassword::prompt_password("Again: ").context(no_terminal)?;
    password::check_password(&typed, &again).map_err(|refusal| match refusal {
        password::Refusal::PasswordsMismatch => anyhow::anyhow!("the two passwords differ"),
        _ => anyhow::anyhow!("a password is 8 to 128 characters"),
    })?;
    let hash = password::hash(&typed).await.map_err(|err| anyhow::anyhow!("{err}"))?;
    users::set_password(&pool, user.id, &login, &hash).await?;
    println!("Password set for '{username}' ({}); they log in as '{login}'.", describe(&user));
    pool.close().await;
    Ok(())
}
