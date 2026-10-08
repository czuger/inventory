//! Where the server listens, and the probe `inventory healthcheck` sends there.
//!
//! On the server the app listens on a Unix socket (`SOCKET_PATH`): nginx runs in a container
//! and reaches it through a host directory bind-mounted into it, so no port is opened at all.
//! Without `SOCKET_PATH` (`cargo run`), it listens on TCP at `BIND_ADDR`.

use std::fs::{self, Permissions};
use std::future::Future;
use std::io;
use std::os::unix::fs::{FileTypeExt as _, PermissionsExt as _};
use std::path::Path;

use axum::Router;
use tokio::io::{AsyncRead, AsyncReadExt as _, AsyncWrite, AsyncWriteExt as _};
use tokio::net::{TcpListener, UnixListener};

use crate::config::Config;

/// nginx's worker runs as another user (uid 101 in the container): it must be able to
/// connect. Who may reach the directory is the directory's business.
const SOCKET_MODE: u32 = 0o666;

/// Serves `app` on `config`'s socket if it has one, on its TCP address otherwise, until
/// SIGTERM or Ctrl-C.
///
/// # Errors
///
/// The listener cannot be set up, or the socket path is taken by something that is not a
/// socket.
pub async fn serve(app: Router, config: &Config) -> io::Result<()> {
    match &config.socket_path {
        Some(path) => serve_unix(app, path, shutdown_signal()).await,
        None => {
            let listener = TcpListener::bind(&config.bind_addr).await?;
            tracing::info!("listening on {}", config.bind_addr);
            axum::serve(listener, app).with_graceful_shutdown(shutdown_signal()).await
        }
    }
}

/// Serves on a Unix socket until `shutdown` resolves, then removes the socket.
pub async fn serve_unix(
    app: Router,
    path: &Path,
    shutdown: impl Future<Output = ()> + Send + 'static,
) -> io::Result<()> {
    remove_stale_socket(path)?;
    let listener = UnixListener::bind(path)?;
    fs::set_permissions(path, Permissions::from_mode(SOCKET_MODE))?;
    tracing::info!("listening on unix:{}", path.display());
    axum::serve(listener, app).with_graceful_shutdown(shutdown).await?;
    fs::remove_file(path)
}

/// A socket left by a previous run (crash, kill -9) would make `bind` fail; anything else at
/// that path is not ours to delete.
fn remove_stale_socket(path: &Path) -> io::Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_socket() => fs::remove_file(path),
        Ok(_) => {
            Err(io::Error::new(io::ErrorKind::AlreadyExists, format!("{} exists and is not a socket", path.display())))
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(_) => std::future::pending::<()>().await,
        }
    };
    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
}

/// A bare HTTP/1.0 `GET /health` over `stream`; returns the status line of the answer. The
/// server needs no curl, and this needs no extra crate.
///
/// # Errors
///
/// Reading or writing `stream` fails.
pub async fn get_health(mut stream: impl AsyncRead + AsyncWrite + Unpin) -> io::Result<String> {
    stream.write_all(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n").await?;
    let mut response = Vec::new();
    stream.read_to_end(&mut response).await?;
    Ok(String::from_utf8_lossy(&response).lines().next().unwrap_or_default().to_owned())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use axum::routing::get;
    use tokio::net::UnixStream;

    use super::*;

    #[test]
    fn stale_socket_is_removed() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("stale.sock");
        drop(std::os::unix::net::UnixListener::bind(&path).unwrap());
        remove_stale_socket(&path).unwrap();
        assert!(!path.exists());
    }

    #[test]
    fn regular_file_at_socket_path_is_kept() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("not_a_socket");
        fs::write(&path, "keep me").unwrap();
        assert_eq!(remove_stale_socket(&path).unwrap_err().kind(), io::ErrorKind::AlreadyExists);
        assert_eq!(fs::read_to_string(&path).unwrap(), "keep me");
    }

    #[tokio::test]
    async fn serves_health_on_a_socket_and_removes_it_on_shutdown() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("app.sock");
        let app = Router::new().route("/health", get(crate::handlers::app::health));
        let (stop, stopped) = tokio::sync::oneshot::channel::<()>();
        let server = tokio::spawn({
            let path = path.clone();
            async move {
                serve_unix(app, &path, async {
                    let _ = stopped.await;
                })
                .await
            }
        });

        let mut stream = None;
        for _ in 0..100 {
            if let Ok(connected) = UnixStream::connect(&path).await {
                stream = Some(connected);
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
        let status = get_health(stream.unwrap()).await.unwrap();
        assert_eq!(status.split(' ').nth(1), Some("200"), "{status}");
        assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, SOCKET_MODE);

        stop.send(()).unwrap();
        server.await.unwrap().unwrap();
        assert!(!path.exists());
    }
}
