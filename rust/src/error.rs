//! The one error type handlers return. Each variant answers with the page werkzeug
//! renders for its status, byte for byte, so clients see what the Flask app sent.

use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("bad request")]
    BadRequest,
    #[error("unauthorized")]
    Unauthorized,
    #[error("forbidden")]
    Forbidden,
    #[error("not found")]
    NotFound,
    /// The URL names no association: a 404 answered before the session was ever read
    /// (Flask's `url_value_preprocessor` aborts ahead of `load_current_user`), so the
    /// response carries no `Vary: Cookie`.
    #[error("unknown association")]
    UnknownAssociation,
    #[error("too many requests")]
    TooManyRequests,
    #[error("database error: {0}")]
    Database(#[from] sqlx::Error),
    #[error(transparent)]
    Url(#[from] crate::urls::UrlError),
    #[error("{0}")]
    Internal(String),
}

impl AppError {
    pub fn status(&self) -> StatusCode {
        match self {
            Self::BadRequest => StatusCode::BAD_REQUEST,
            Self::Unauthorized => StatusCode::UNAUTHORIZED,
            Self::Forbidden => StatusCode::FORBIDDEN,
            Self::NotFound | Self::UnknownAssociation => StatusCode::NOT_FOUND,
            Self::TooManyRequests => StatusCode::TOO_MANY_REQUESTS,
            Self::Database(_) | Self::Url(_) | Self::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let status = self.status();
        if status.is_server_error() {
            tracing::error!(error = %self, "request failed");
        }
        let mut response = error_page(status);
        if matches!(self, Self::UnknownAssociation) {
            response.extensions_mut().insert(SessionUnread);
        }
        response
    }
}

/// Marks a response produced before Flask would have read the session.
#[derive(Debug, Clone, Copy)]
pub struct SessionUnread;

/// Werkzeug's default HTML error page for `status`.
pub fn error_page(status: StatusCode) -> Response {
    let (name, description) = match status {
        StatusCode::BAD_REQUEST => {
            ("Bad Request", "The browser (or proxy) sent a request that this server could not understand.")
        }
        StatusCode::UNAUTHORIZED => (
            "Unauthorized",
            "The server could not verify that you are authorized to access the URL requested. You either supplied the \
             wrong credentials (e.g. a bad password), or your browser doesn&#39;t understand how to supply the \
             credentials required.",
        ),
        StatusCode::FORBIDDEN => (
            "Forbidden",
            "You don&#39;t have the permission to access the requested resource. It is either read-protected or not \
             readable by the server.",
        ),
        StatusCode::NOT_FOUND => (
            "Not Found",
            "The requested URL was not found on the server. If you entered the URL manually please check your \
             spelling and try again.",
        ),
        StatusCode::METHOD_NOT_ALLOWED => ("Method Not Allowed", "The method is not allowed for the requested URL."),
        StatusCode::TOO_MANY_REQUESTS => {
            ("Too Many Requests", "This user has exceeded an allotted request count. Try again later.")
        }
        _ => (
            "Internal Server Error",
            "The server encountered an internal error and was unable to complete your request. Either the server is \
             overloaded or there is an error in the application.",
        ),
    };
    let code = if name == "Internal Server Error" { StatusCode::INTERNAL_SERVER_ERROR } else { status };
    let body = format!(
        "<!doctype html>\n<html lang=en>\n<title>{} {name}</title>\n<h1>{name}</h1>\n<p>{description}</p>\n",
        code.as_u16()
    );
    (code, [(header::CONTENT_TYPE, "text/html; charset=utf-8")], body).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use http_body_util::BodyExt;

    async fn body(response: Response) -> String {
        let bytes = response.into_body().collect().await.unwrap().to_bytes();
        String::from_utf8(bytes.to_vec()).unwrap()
    }

    // Expected bodies printed by werkzeug 3.1 (`NotFound().get_response()` etc.).
    #[tokio::test]
    async fn pages_match_werkzeug() {
        let cases = [
            (
                AppError::BadRequest,
                400,
                "<!doctype html>\n<html lang=en>\n<title>400 Bad Request</title>\n<h1>Bad Request</h1>\n<p>The browser (or proxy) sent a request that this server could not understand.</p>\n",
            ),
            (
                AppError::Unauthorized,
                401,
                "<!doctype html>\n<html lang=en>\n<title>401 Unauthorized</title>\n<h1>Unauthorized</h1>\n<p>The server could not verify that you are authorized to access the URL requested. You either supplied the wrong credentials (e.g. a bad password), or your browser doesn&#39;t understand how to supply the credentials required.</p>\n",
            ),
            (
                AppError::Forbidden,
                403,
                "<!doctype html>\n<html lang=en>\n<title>403 Forbidden</title>\n<h1>Forbidden</h1>\n<p>You don&#39;t have the permission to access the requested resource. It is either read-protected or not readable by the server.</p>\n",
            ),
            (
                AppError::NotFound,
                404,
                "<!doctype html>\n<html lang=en>\n<title>404 Not Found</title>\n<h1>Not Found</h1>\n<p>The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.</p>\n",
            ),
            (
                AppError::TooManyRequests,
                429,
                "<!doctype html>\n<html lang=en>\n<title>429 Too Many Requests</title>\n<h1>Too Many Requests</h1>\n<p>This user has exceeded an allotted request count. Try again later.</p>\n",
            ),
            (
                AppError::Internal("boom".into()),
                500,
                "<!doctype html>\n<html lang=en>\n<title>500 Internal Server Error</title>\n<h1>Internal Server Error</h1>\n<p>The server encountered an internal error and was unable to complete your request. Either the server is overloaded or there is an error in the application.</p>\n",
            ),
        ];
        for (error, status, expected) in cases {
            let response = error.into_response();
            assert_eq!(response.status().as_u16(), status);
            assert_eq!(response.headers()[header::CONTENT_TYPE], "text/html; charset=utf-8");
            assert_eq!(body(response).await, expected);
        }
    }

    #[tokio::test]
    async fn method_not_allowed_page() {
        let response = error_page(StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(
            body(response).await,
            "<!doctype html>\n<html lang=en>\n<title>405 Method Not Allowed</title>\n<h1>Method Not Allowed</h1>\n<p>The method is not allowed for the requested URL.</p>\n"
        );
    }
}
