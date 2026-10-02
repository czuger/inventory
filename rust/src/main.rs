use std::net::{Ipv4Addr, SocketAddr};
use std::process::ExitCode;
use std::time::Duration;

use anyhow::Context as _;
use clap::{Parser, Subcommand};
use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};
use tracing_subscriber::EnvFilter;

use inventory::config::{Config, Secrets};
use inventory::db::users;
use inventory::{AppState, build_app, db, migrate, password};

#[derive(Parser)]
#[command(about = "The club inventory web app")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Serve the app on BIND_ADDR (the default command)
    Serve,
    /// Back up the database, then apply the pending migrations
    Migrate,
    /// Exit 0 if the server on BIND_ADDR answers /health (the container's HEALTHCHECK)
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
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info,sqlx=warn")))
        .init();

    let result = match Cli::parse().command.unwrap_or(Command::Serve) {
        Command::Serve => serve().await,
        Command::Migrate => run_migrations().await,
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

    let listener = tokio::net::TcpListener::bind(&config.bind_addr)
        .await
        .with_context(|| format!("cannot listen on {}", config.bind_addr))?;
    tracing::info!("listening on {}", config.bind_addr);
    let state = AppState::new(config, &secrets.secret_key, pool.clone())?.with_discord(secrets.discord);
    let app = build_app(state);
    axum::serve(listener, app).with_graceful_shutdown(shutdown_signal()).await?;
    pool.close().await;
    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(_) => std::future::pending::<()>().await,
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
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

/// A bare HTTP/1.0 GET: the runtime image has no curl, and this needs no extra crate.
async fn healthcheck() -> anyhow::Result<()> {
    let bind = std::env::var("BIND_ADDR").unwrap_or_else(|_| "0.0.0.0:8000".to_owned());
    let mut addr: SocketAddr = bind.parse().with_context(|| format!("BIND_ADDR {bind:?} is not an ip:port"))?;
    if addr.ip().is_unspecified() {
        addr.set_ip(Ipv4Addr::LOCALHOST.into());
    }
    let probe = async {
        let mut stream = tokio::net::TcpStream::connect(addr).await?;
        stream.write_all(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n").await?;
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await?;
        Ok::<_, std::io::Error>(response)
    };
    let response = tokio::time::timeout(Duration::from_secs(3), probe)
        .await
        .context("timed out")?
        .with_context(|| format!("cannot reach {addr}"))?;
    let status_line = String::from_utf8_lossy(&response).lines().next().unwrap_or_default().to_owned();
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

    let no_terminal = "typing the password needs a terminal (in the container: `docker exec -it`)";
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
