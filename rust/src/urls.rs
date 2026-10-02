//! `url_for`: every endpoint's URL rule, and how Flask/werkzeug build URLs from them.
//!
//! - Item and print endpoints live under `/<slug>/`; when `slug` is not given, the
//!   current association's is used (each blueprint's `url_defaults` hook).
//! - Arguments that are not part of the rule become the query string.
//! - Everything is prefixed with the script name (`URL_PREFIX`): nginx strips the prefix
//!   before proxying, so routing never sees it, but every generated link needs it.
//! - External URLs use the request's scheme (`X-Forwarded-Proto`, trusted as gunicorn's
//!   `--forwarded-allow-ips *` did) and `Host` header.

use std::collections::HashMap;
use std::fmt::Write as _;
use std::sync::LazyLock;

use axum::http::HeaderMap;
use axum::http::request::Parts;

use crate::kinds::ItemKind;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum UrlError {
    #[error("no endpoint named {0:?}")]
    UnknownEndpoint(String),
    #[error("cannot build {endpoint:?}: missing value for {arg:?}")]
    MissingArgument { endpoint: String, arg: String },
}

struct Rule {
    pattern: String,
    /// Under `/<slug>/`, with the current association as the default slug.
    assoc: bool,
}

static RULES: LazyLock<HashMap<String, Rule>> = LazyLock::new(|| {
    let mut rules = HashMap::new();
    let mut add = |endpoint: String, pattern: String, assoc: bool| {
        rules.insert(endpoint, Rule { pattern, assoc });
    };
    add("index".into(), "/".into(), false);
    add("health".into(), "/health".into(), false);
    add("set_language".into(), "/set-language/<lang>".into(), false);
    add("static".into(), "/static/<filename>".into(), false);
    add("auth.login".into(), "/auth/discord".into(), false);
    add("auth.callback".into(), "/auth/discord/callback".into(), false);
    add("auth.logout".into(), "/auth/logout".into(), false);
    add("auth.signin".into(), "/auth/login".into(), false);
    add("auth.register".into(), "/auth/register".into(), false);
    add("print_page.index".into(), "/<slug>/print/".into(), true);
    add("print_page.stickers".into(), "/<slug>/print/stickers".into(), true);
    add("print_page.print_list".into(), "/<slug>/print/list".into(), true);
    for kind in ItemKind::ALL {
        let base = format!("/<slug>/{}", kind.segment());
        for (view, rest) in [
            ("index", "/"),
            ("show", "/<id>"),
            ("create", "/new"),
            ("edit", "/<id>/edit"),
            ("delete", "/<id>/delete"),
            ("upload_image", "/<id>/images"),
            ("delete_image", "/<id>/images/<filename>/delete"),
            ("borrow", "/<id>/borrow"),
            ("return_item", "/<id>/return"),
            ("add_duplicate", "/<id>/duplicates"),
            ("delete_duplicate", "/<id>/duplicates/<link_id>/delete"),
            ("stickers", "/stickers"),
        ] {
            add(format!("{}.{view}", kind.blueprint()), format!("{base}{rest}"), true);
        }
    }
    rules
});

/// What building a URL needs from the current request.
#[derive(Debug, Clone, Default)]
pub struct UrlContext {
    /// `/inventory`, or empty when served at the root.
    pub script_name: String,
    pub scheme: String,
    pub host: String,
    /// The current association's slug, if the request is under one.
    pub slug: Option<String>,
}

impl UrlContext {
    pub fn from_request(headers: &HeaderMap, url_prefix: &str) -> Self {
        let header = |name: &str| headers.get(name).and_then(|v| v.to_str().ok());
        let scheme = header("x-forwarded-proto")
            .and_then(|proto| proto.split(',').next())
            .map(|proto| proto.trim().to_ascii_lowercase())
            .filter(|proto| !proto.is_empty())
            .unwrap_or_else(|| "http".to_owned());
        Self {
            script_name: if url_prefix.is_empty() { String::new() } else { format!("/{url_prefix}") },
            scheme,
            host: header("host").unwrap_or("localhost").to_owned(),
            slug: None,
        }
    }

    pub fn from_parts(parts: &Parts, url_prefix: &str) -> Self {
        Self::from_request(&parts.headers, url_prefix)
    }

    pub fn with_slug(mut self, slug: &str) -> Self {
        self.slug = Some(slug.to_owned());
        self
    }

    /// `scheme://host`, what `_external=True` puts in front of the path.
    pub fn origin(&self) -> String {
        format!("{}://{}", self.scheme, self.host)
    }

    /// `url_for(endpoint, **args)`.
    pub fn url_for(&self, endpoint: &str, args: &[(&str, String)]) -> Result<String, UrlError> {
        let rule = RULES.get(endpoint).ok_or_else(|| UrlError::UnknownEndpoint(endpoint.to_owned()))?;
        let mut used = vec![false; args.len()];
        let mut path = String::with_capacity(rule.pattern.len() + 16);
        let mut rest = rule.pattern.as_str();
        while let Some(start) = rest.find('<') {
            path.push_str(&rest[..start]);
            let Some(end) = rest[start..].find('>') else { break };
            let name = &rest[start + 1..start + end];
            let value = match args.iter().position(|(arg, _)| *arg == name) {
                Some(index) => {
                    used[index] = true;
                    args[index].1.clone()
                }
                None if name == "slug" && rule.assoc => self.slug.clone().ok_or_else(|| missing(endpoint, name))?,
                None => return Err(missing(endpoint, name)),
            };
            path.push_str(&quote_path(&value));
            rest = &rest[start + end + 1..];
        }
        path.push_str(rest);

        let query: Vec<String> = args
            .iter()
            .zip(used)
            .filter(|(_, used)| !used)
            .map(|((name, value), _)| format!("{}={}", quote_query(name), quote_query(value)))
            .collect();
        let mut url = format!("{}{path}", self.script_name);
        if !query.is_empty() {
            url.push('?');
            url.push_str(&query.join("&"));
        }
        Ok(url)
    }

    /// `url_for(endpoint, _external=True, **args)`.
    pub fn external_url_for(&self, endpoint: &str, args: &[(&str, String)]) -> Result<String, UrlError> {
        Ok(format!("{}{}", self.origin(), self.url_for(endpoint, args)?))
    }
}

fn missing(endpoint: &str, arg: &str) -> UrlError {
    UrlError::MissingArgument { endpoint: endpoint.to_owned(), arg: arg.to_owned() }
}

fn is_unreserved(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || b"-._~".contains(&byte)
}

fn percent_encode(value: &str, safe: &[u8], space_as_plus: bool) -> String {
    let mut out = String::with_capacity(value.len());
    for &byte in value.as_bytes() {
        if is_unreserved(byte) || safe.contains(&byte) {
            out.push(char::from(byte));
        } else if byte == b' ' && space_as_plus {
            out.push('+');
        } else {
            let _ = write!(out, "%{byte:02X}");
        }
    }
    out
}

/// werkzeug's `BaseConverter.to_url`: `quote(value, safe="!$&'()*+,/:;=@")`.
pub fn quote_path(value: &str) -> String {
    percent_encode(value, b"!$&'()*+,/:;=@", false)
}

/// werkzeug's query string encoding: `quote_plus(value, safe="!$'()*,/:;?@")`.
pub fn quote_query(value: &str) -> String {
    percent_encode(value, b"!$'()*,/:;?@", true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx(script_name: &str) -> UrlContext {
        UrlContext {
            script_name: script_name.into(),
            scheme: "https".into(),
            host: "apps.example.com".into(),
            slug: Some("t".into()),
        }
    }

    // Expected values printed by Flask 3.1's url_for under SCRIPT_NAME=/inventory.
    #[test]
    fn matches_flask() {
        let ctx = ctx("/inventory");
        assert_eq!(
            ctx.url_for("miniatures.index", &[("category", "Board Game".into()), ("x", "a/b é&".into())]).unwrap(),
            "/inventory/t/miniatures/?category=Board+Game&x=a/b+%C3%A9%26"
        );
        assert_eq!(
            ctx.url_for("static", &[("filename", "uploads/board_game/3/a b é.png".into())]).unwrap(),
            "/inventory/static/uploads/board_game/3/a%20b%20%C3%A9.png"
        );
        assert_eq!(
            ctx.external_url_for("set_language", &[("lang", "fr".into())]).unwrap(),
            "https://apps.example.com/inventory/set-language/fr"
        );
        assert_eq!(
            ctx.url_for("miniatures.show", &[("slug", "t é".into()), ("id", "3".into())]).unwrap(),
            "/inventory/t%20%C3%A9/miniatures/3"
        );
    }

    #[test]
    fn slug_defaults_to_the_current_association() {
        let ctx = ctx("");
        assert_eq!(ctx.url_for("board_games.edit", &[("id", "4".into())]).unwrap(), "/t/board-games/4/edit");
        assert_eq!(ctx.url_for("print_page.index", &[]).unwrap(), "/t/print/");
        assert_eq!(
            ctx.url_for("tablecloths.delete_duplicate", &[("id", "1".into()), ("link_id", "2".into())]).unwrap(),
            "/t/tablecloths/1/duplicates/2/delete"
        );
        // Endpoints outside the association blueprints never take it.
        assert_eq!(ctx.url_for("index", &[]).unwrap(), "/");
        assert_eq!(ctx.url_for("auth.logout", &[]).unwrap(), "/auth/logout");
    }

    #[test]
    fn build_errors() {
        let mut no_assoc = ctx("");
        no_assoc.slug = None;
        assert_eq!(
            no_assoc.url_for("miniatures.index", &[]),
            Err(UrlError::MissingArgument { endpoint: "miniatures.index".into(), arg: "slug".into() })
        );
        assert_eq!(ctx("").url_for("nope", &[]), Err(UrlError::UnknownEndpoint("nope".into())));
        assert!(ctx("").url_for("miniatures.show", &[]).is_err());
    }

    #[test]
    fn request_scheme_and_host() {
        let mut headers = HeaderMap::new();
        headers.insert("host", "apps.ieroe.com".parse().unwrap());
        headers.insert("x-forwarded-proto", "https".parse().unwrap());
        let ctx = UrlContext::from_request(&headers, "inventory");
        assert_eq!(
            ctx.external_url_for("auth.callback", &[]).unwrap(),
            "https://apps.ieroe.com/inventory/auth/discord/callback"
        );
        let plain = UrlContext::from_request(&HeaderMap::new(), "");
        assert_eq!(plain.origin(), "http://localhost");
    }
}
