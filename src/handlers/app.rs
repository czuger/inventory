//! Routes registered at the application root (`app.py`'s `create_app`).

use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};

use crate::AppState;
use crate::error::AppError;
use crate::session::Session;
use crate::urls::UrlContext;
use crate::web::{redirect, referrer};

/// What the deploy gates on: `inventory healthcheck` probes it from inside the container
/// after every start, and the image's HEALTHCHECK runs the same probe.
///
/// Deliberately does NOT touch the database. It answers the only question the deploy can
/// act on — did the server come up with this image — and a probe that also failed when
/// the database blinked would roll back a perfectly good release.
pub async fn health() -> impl IntoResponse {
    ([(header::CONTENT_TYPE, "text/plain")], "ok")
}

pub async fn not_found() -> AppError {
    AppError::NotFound
}

/// `/`: the first association's miniatures.
pub async fn index(State(state): State<AppState>, headers: HeaderMap) -> Result<Response, AppError> {
    let slug = crate::db::refs::first_association_slug(&state.pool).await?;
    let Some(slug) = slug else {
        return Ok((
            StatusCode::NOT_FOUND,
            [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
            "No association found.",
        )
            .into_response());
    };
    let url = UrlContext::from_request(&headers, &state.config.url_prefix);
    Ok(redirect(&url.url_for("miniatures.index", &[("slug", slug)])?))
}

/// `/set-language/<lang>`: anything but `en`/`fr` is ignored. Back to where the user was.
pub async fn set_language(
    State(state): State<AppState>,
    Path(lang): Path<String>,
    session: Session,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    if lang == "en" || lang == "fr" {
        session.insert("lang", lang.into());
    }
    let target = match referrer(&headers) {
        Some(referrer) => referrer,
        None => UrlContext::from_request(&headers, &state.config.url_prefix).url_for("index", &[])?,
    };
    Ok(redirect(&target))
}

/// The files of `inventory/api/static/`, built into the binary. Uploaded photos are
/// served from `UPLOADS_DIR` by a separate route.
pub async fn static_file(Path(path): Path<String>) -> Response {
    let (body, content_type): (&'static [u8], &str) = match path.as_str() {
        "favicon.png" => (include_bytes!("../../static/favicon.png"), "image/png"),
        "favicon.svg" => (include_bytes!("../../static/favicon.svg"), "image/svg+xml"),
        "icons8-knight-96.png" => (include_bytes!("../../static/icons8-knight-96.png"), "image/png"),
        _ => return AppError::NotFound.into_response(),
    };
    let disposition = inline_disposition(&path);
    (
        [(header::CONTENT_TYPE, content_type), (header::CACHE_CONTROL, "no-cache")],
        [(header::CONTENT_DISPOSITION, disposition)],
        body,
    )
        .into_response()
}

/// What Flask's `send_from_directory` sends: `inline; filename=<name>` (quoted when the
/// name has characters outside a header token, as werkzeug does).
pub fn inline_disposition(path: &str) -> String {
    let name = path.rsplit('/').next().unwrap_or(path);
    let token = !name.is_empty() && name.bytes().all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b));
    if token {
        format!("inline; filename={name}")
    } else {
        format!("inline; filename=\"{}\"", name.replace('"', "\\\""))
    }
}

/// Adds Flask's `Content-Disposition` to a photo served from `UPLOADS_DIR`.
pub async fn upload_disposition(request: axum::extract::Request, next: axum::middleware::Next) -> Response {
    let disposition = inline_disposition(request.uri().path());
    let mut response = next.run(request).await;
    if response.status().is_success()
        && let Ok(value) = axum::http::HeaderValue::from_str(&disposition)
    {
        response.headers_mut().insert(header::CONTENT_DISPOSITION, value);
    }
    response
}
