//! Responses shaped like werkzeug's: redirects, HTML escaping, and the routing behaviour
//! axum does differently (405/OPTIONS, the trailing-slash redirect).

use axum::body::Body;
use axum::extract::{Request, State};
use axum::http::{HeaderValue, Method, StatusCode, header};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};

use crate::AppState;
use crate::error::{AppError, error_page};
use crate::urls::UrlContext;

/// MarkupSafe's `escape`, which Jinja's autoescape and werkzeug use.
pub fn escape_html(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&#34;"),
            '\'' => out.push_str("&#39;"),
            c => out.push(c),
        }
    }
    out
}

/// The part of werkzeug's `iri_to_uri` that matters for a header: non-ASCII bytes are
/// percent-encoded (a referrer can carry them).
fn iri_to_uri(location: &str) -> String {
    let mut out = String::with_capacity(location.len());
    for c in location.chars() {
        if c.is_ascii() && !c.is_ascii_control() {
            out.push(c);
        } else {
            let mut buf = [0u8; 4];
            for byte in c.encode_utf8(&mut buf).bytes() {
                out.push_str(&format!("%{byte:02X}"));
            }
        }
    }
    out
}

/// `flask.redirect(location, code)`: the same Location header and HTML body.
pub fn redirect_with(location: &str, status: StatusCode) -> Response {
    let location = iri_to_uri(location);
    let html = escape_html(&location);
    let body = format!(
        "<!doctype html>\n<html lang=en>\n<title>Redirecting...</title>\n<h1>Redirecting...</h1>\n<p>You should be \
         redirected automatically to the target URL: <a href=\"{html}\">{html}</a>. If not, click the link.\n"
    );
    match HeaderValue::from_str(&location) {
        Ok(value) => (
            status,
            [(header::CONTENT_TYPE, HeaderValue::from_static("text/html; charset=utf-8")), (header::LOCATION, value)],
            body,
        )
            .into_response(),
        Err(_) => AppError::Internal(format!("cannot redirect to {location:?}")).into_response(),
    }
}

/// `flask.redirect(location)`: a 302.
pub fn redirect(location: &str) -> Response {
    redirect_with(location, StatusCode::FOUND)
}

/// `request.referrer`.
pub fn referrer(headers: &axum::http::HeaderMap) -> Option<String> {
    headers.get(header::REFERER).and_then(|v| v.to_str().ok()).filter(|v| !v.is_empty()).map(str::to_owned)
}

/// What werkzeug's router answers where axum's differs:
///
/// - a method the route does not take: 405 with werkzeug's page (axum sends an empty body);
/// - `OPTIONS`: 200 with an empty body and the `Allow` list (axum has no automatic OPTIONS).
///
/// Both list `OPTIONS` among the allowed methods, as werkzeug does.
pub async fn werkzeug_compat(request: Request, next: Next) -> Response {
    let is_options = request.method() == Method::OPTIONS;
    let response = next.run(request).await;
    if response.status() != StatusCode::METHOD_NOT_ALLOWED || response.headers().get(header::ALLOW).is_none() {
        return response;
    }
    let mut methods: Vec<String> = response
        .headers()
        .get(header::ALLOW)
        .and_then(|v| v.to_str().ok())
        .unwrap_or_default()
        .split(',')
        .map(|m| m.trim().to_owned())
        .filter(|m| !m.is_empty())
        .collect();
    if !methods.iter().any(|m| m == "OPTIONS") {
        methods.push("OPTIONS".to_owned());
    }
    let allow = HeaderValue::from_str(&methods.join(", ")).unwrap_or_else(|_| HeaderValue::from_static("OPTIONS"));

    let mut answer = if is_options {
        (StatusCode::OK, [(header::CONTENT_TYPE, "text/html; charset=utf-8")], Body::empty()).into_response()
    } else {
        error_page(StatusCode::METHOD_NOT_ALLOWED)
    };
    answer.headers_mut().insert(header::ALLOW, allow);
    for vary in response.headers().get_all(header::VARY) {
        answer.headers_mut().append(header::VARY, vary.clone());
    }
    for cookie in response.headers().get_all(header::SET_COOKIE) {
        answer.headers_mut().append(header::SET_COOKIE, cookie.clone());
    }
    answer
}

/// A rule ending in `/` requested without it (`/<slug>/miniatures`): werkzeug's
/// strict-slashes redirect, a 308 to the absolute URL with the slash, query kept. Only for
/// methods the rule takes; any other gets a 404, as in werkzeug.
pub async fn add_trailing_slash(State(state): State<AppState>, request: Request) -> Response {
    if !matches!(*request.method(), Method::GET | Method::HEAD | Method::OPTIONS) {
        return AppError::NotFound.into_response();
    }
    let ctx = UrlContext::from_request(request.headers(), &state.config.url_prefix);
    let mut location = format!("{}{}{}/", ctx.origin(), ctx.script_name, request.uri().path());
    if let Some(query) = request.uri().query() {
        location.push('?');
        location.push_str(query);
    }
    redirect_with(&location, StatusCode::PERMANENT_REDIRECT)
}

/// werkzeug's `<int:id>`: ASCII digits only (so `007` is 7, and `-1` is no match).
pub fn parse_int_segment(segment: &str) -> Option<i64> {
    if segment.is_empty() || !segment.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    segment.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use http_body_util::BodyExt;

    #[tokio::test]
    async fn redirect_matches_werkzeug() {
        // `werkzeug.utils.redirect('/x?a=1&b=<2>')`.
        let response = redirect("/x?a=1&b=<2>");
        assert_eq!(response.status(), StatusCode::FOUND);
        assert_eq!(response.headers()[header::LOCATION], "/x?a=1&b=<2>");
        assert_eq!(response.headers()[header::CONTENT_TYPE], "text/html; charset=utf-8");
        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(
            body,
            "<!doctype html>\n<html lang=en>\n<title>Redirecting...</title>\n<h1>Redirecting...</h1>\n<p>You should \
             be redirected automatically to the target URL: <a href=\"/x?a=1&amp;b=&lt;2&gt;\">/x?a=1&amp;b=&lt;2&gt;</a>. \
             If not, click the link.\n"
        );
    }

    #[test]
    fn escaping_and_ints() {
        assert_eq!(
            escape_html(r#"<a href="x">l'objet & co</a>"#),
            "&lt;a href=&#34;x&#34;&gt;l&#39;objet &amp; co&lt;/a&gt;"
        );
        assert_eq!(parse_int_segment("007"), Some(7));
        assert_eq!(parse_int_segment("-1"), None);
        assert_eq!(parse_int_segment(""), None);
        assert_eq!(parse_int_segment("65f0c0ffee0123456789abcd"), None);
        assert_eq!(parse_int_segment("99999999999999999999999"), None);
    }
}
