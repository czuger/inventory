//! The Jinja templates, rendered by minijinja the way Flask's Jinja2 rendered them.
//!
//! What it takes to get the same HTML out of the same templates:
//!
//! - **Output formatting.** Jinja2 prints `None` as `None` and booleans as
//!   `True`/`False`, and its autoescape (MarkupSafe) writes `&#39;`/`&#34;` and leaves `/`
//!   alone, where minijinja would print `none`/`true` and escape `/`.
//! - **Python string methods** (`category.lower().replace(' ', '_')`) come from
//!   minijinja-contrib's pycompat.
//! - **Flask's template context**: `t`, `lang`, `admin`, `current_user` (the context
//!   processor), `request.blueprint`, `url_for` and `get_flashed_messages`.
//! - **Globals that queried the database** (`get_borrow_status` and friends) cannot run
//!   inside a synchronous render: handlers load that data first and pass it in.

use std::sync::Arc;

use axum::extract::FromRequestParts;
use axum::http::request::Parts;
use axum::response::Html;
use chrono::NaiveDateTime;
use chrono::format::{Item, StrftimeItems};
use minijinja::value::{Kwargs, Object, Value, ValueKind, from_args};
use minijinja::{AutoEscape, Environment, Error, ErrorKind, Output, State, context};

use crate::AppState;
use crate::db::types::parse_datetime;
use crate::error::AppError;
use crate::extract::CurrentUser;
use crate::session::Session;
use crate::urls::UrlContext;
use crate::web::escape_html;

const URL_CONTEXT: &str = "__url";
const FLASHES: &str = "__flashes";
const ITEM_EXTRAS: &str = "__item_extras";

/// The parsed `translations.json` (dumped from `inventory/api/translations.py`).
pub struct Translations {
    en: Value,
    fr: Value,
}

impl Translations {
    fn load() -> Result<Self, serde_json::Error> {
        let all: serde_json::Value = serde_json::from_str(include_str!("../i18n/translations.json"))?;
        Ok(Self { en: Value::from_serialize(&all["en"]), fr: Value::from_serialize(&all["fr"]) })
    }

    /// `TRANSLATIONS[lang]`, French for anything but English.
    pub fn get(&self, lang: &str) -> &Value {
        if lang == "en" { &self.en } else { &self.fr }
    }
}

mod embedded {
    include!(concat!(env!("OUT_DIR"), "/templates.rs"));
}

#[derive(Debug, thiserror::Error)]
pub enum TemplatesError {
    #[error("cannot load the translations: {0}")]
    Translations(#[from] serde_json::Error),
    #[error("invalid template: {0:#}")]
    Template(#[from] Error),
}

pub struct Templates {
    env: Environment<'static>,
    pub translations: Translations,
}

impl Templates {
    pub fn new() -> Result<Self, TemplatesError> {
        let mut env = Environment::new();
        for (name, source) in embedded::TEMPLATES {
            env.add_template(name, source)?;
        }
        env.set_formatter(jinja2_formatter);
        env.set_unknown_method_callback(minijinja_contrib::pycompat::unknown_method_callback);
        env.add_function("url_for", url_for);
        env.add_function("get_flashed_messages", get_flashed_messages);
        env.add_function("get_borrow_status", get_borrow_status);
        env.add_function("get_borrow_history", get_borrow_history);
        env.add_function("get_duplicate_links", get_duplicate_links);
        Ok(Self { env, translations: Translations::load()? })
    }

    pub fn render(&self, name: &str, ctx: Value) -> Result<String, Error> {
        self.env.get_template(name)?.render(ctx)
    }
}

/// How Jinja2 prints a value: see the module documentation.
fn jinja2_formatter(out: &mut Output, state: &State, value: &Value) -> Result<(), Error> {
    let text = match value.kind() {
        ValueKind::Undefined => return Ok(()),
        ValueKind::None => "None".to_owned(),
        ValueKind::Bool => if value.is_true() { "True" } else { "False" }.to_owned(),
        _ => value.to_string(),
    };
    let escape = matches!(state.auto_escape(), AutoEscape::Html) && !value.is_safe();
    out.write_str(&if escape { escape_html(&text) } else { text }).map_err(Error::from)
}

impl Object for UrlContext {}

/// A template argument as werkzeug would turn it into a URL part (`str(value)`).
fn url_arg(value: &Value) -> String {
    match value.as_str() {
        Some(text) => text.to_owned(),
        None => value.to_string(),
    }
}

/// `url_for(endpoint, **values)`, inside a template.
fn url_for(state: &State, endpoint: &str, kwargs: Kwargs) -> Result<String, Error> {
    let ctx = state
        .lookup(URL_CONTEXT)
        .and_then(|value| value.downcast_object::<UrlContext>())
        .ok_or_else(|| Error::new(ErrorKind::InvalidOperation, "url_for needs a request context"))?;
    let mut args = Vec::new();
    for name in kwargs.args() {
        let value: Value = kwargs.get(name)?;
        args.push((name, url_arg(&value)));
    }
    kwargs.assert_all_used()?;
    ctx.url_for(endpoint, &args).map_err(|err| Error::new(ErrorKind::InvalidOperation, err.to_string()))
}

/// `get_flashed_messages(with_categories=False)`: the flashes taken from the session for
/// this render, as `(category, message)` pairs or bare messages.
fn get_flashed_messages(state: &State, kwargs: Kwargs) -> Result<Value, Error> {
    let with_categories: Option<bool> = kwargs.get("with_categories")?;
    kwargs.assert_all_used()?;
    let flashes = state.lookup(FLASHES).unwrap_or_else(|| Value::from(Vec::<Value>::new()));
    if with_categories.unwrap_or(false) {
        return Ok(flashes);
    }
    let messages: Result<Vec<Value>, Error> = flashes.try_iter()?.map(|pair| pair.get_item(&Value::from(1))).collect();
    Ok(Value::from(messages?))
}

/// A Python `datetime` in a template: `{{ b.date.strftime('%Y-%m-%d %H:%M') }}` works, and
/// printing it gives `str(datetime)`.
#[derive(Debug)]
pub struct TemplateDate(pub NaiveDateTime);

impl Object for TemplateDate {
    fn call_method(self: &Arc<Self>, _state: &State<'_, '_>, method: &str, args: &[Value]) -> Result<Value, Error> {
        if method != "strftime" {
            return Err(Error::from(ErrorKind::UnknownMethod));
        }
        let (format,): (&str,) = from_args(args)?;
        let items: Vec<Item<'_>> = StrftimeItems::new(format).collect();
        if items.iter().any(|item| matches!(item, Item::Error)) {
            return Err(Error::new(ErrorKind::InvalidOperation, format!("bad strftime format {format:?}")));
        }
        Ok(Value::from(self.0.format_with_items(items.into_iter()).to_string()))
    }

    fn render(self: &Arc<Self>, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // str(datetime): the microseconds only when there are some.
        if self.0.and_utc().timestamp_subsec_micros() == 0 {
            write!(f, "{}", self.0.format("%Y-%m-%d %H:%M:%S"))
        } else {
            write!(f, "{}", self.0.format("%Y-%m-%d %H:%M:%S%.6f"))
        }
    }
}

/// A stored datetime as a template value (`None` if it cannot be read).
pub fn date_value(stored: &str) -> Value {
    parse_datetime(stored).map_or(Value::from(()), |date| Value::from_object(TemplateDate(date)))
}

/// What the Flask templates fetched through `get_borrow_status`, `get_borrow_history` and
/// `get_duplicate_links`, loaded by the handler for the page's item.
#[derive(Debug, Default)]
pub struct ItemExtras {
    pub item_type: String,
    pub item_id: i64,
    /// Latest first; each `{id, action, date, borrower}`.
    pub history: Vec<Value>,
    /// Each `{link_id, label, endpoint, other_id}`.
    pub duplicates: Vec<Value>,
}

impl Object for ItemExtras {}

fn item_extras(state: &State, item_id: i64, item_type: &str, function: &str) -> Option<Arc<ItemExtras>> {
    let extras = state.lookup(ITEM_EXTRAS).and_then(|value| value.downcast_object::<ItemExtras>());
    match extras {
        Some(extras) if extras.item_id == item_id && extras.item_type == item_type => Some(extras),
        _ => {
            tracing::warn!("{function}({item_id}, {item_type:?}) was not prefetched for {}", state.name());
            None
        }
    }
}

fn get_borrow_status(state: &State, item_id: i64, item_type: &str) -> Value {
    item_extras(state, item_id, item_type, "get_borrow_status")
        .and_then(|extras| extras.history.first().cloned())
        .unwrap_or_else(|| Value::from(()))
}

fn get_borrow_history(state: &State, item_id: i64, item_type: &str) -> Value {
    Value::from(
        item_extras(state, item_id, item_type, "get_borrow_history").map(|e| e.history.clone()).unwrap_or_default(),
    )
}

fn get_duplicate_links(state: &State, item_id: i64, item_type: &str) -> Value {
    Value::from(
        item_extras(state, item_id, item_type, "get_duplicate_links").map(|e| e.duplicates.clone()).unwrap_or_default(),
    )
}

/// What every page needs from the request: Flask's `inject_globals` context processor
/// plus `request` and the URL-building context.
pub struct Page {
    state: AppState,
    session: Session,
    user: CurrentUser,
    url: UrlContext,
}

impl FromRequestParts<AppState> for Page {
    type Rejection = AppError;

    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, Self::Rejection> {
        Ok(Self {
            session: Session::from_request_parts(parts, state).await?,
            user: CurrentUser::from_request_parts(parts, state).await?,
            url: UrlContext::from_parts(parts, &state.config.url_prefix),
            state: state.clone(),
        })
    }
}

impl Page {
    /// Pages under `/<slug>/` build their links with that association's slug.
    pub fn with_slug(mut self, slug: &str) -> Self {
        self.url = self.url.with_slug(slug);
        self
    }

    pub fn url(&self) -> &UrlContext {
        &self.url
    }

    pub fn session(&self) -> &Session {
        &self.session
    }

    pub fn user(&self) -> &CurrentUser {
        &self.user
    }

    /// Renders `name` with the template's own `vars` on top of the common context.
    /// `blueprint` is `request.blueprint` (`None` for app-level pages).
    pub fn render(&self, name: &str, blueprint: Option<&str>, vars: Value) -> Result<Html<String>, AppError> {
        self.render_with(name, blueprint, vars, None)
    }

    /// `render`, with the prefetched data of the page's item.
    pub fn render_with(
        &self,
        name: &str,
        blueprint: Option<&str>,
        vars: Value,
        extras: Option<ItemExtras>,
    ) -> Result<Html<String>, AppError> {
        let lang = self.session.lang();
        let flashes: Vec<Value> = self
            .session
            .take_flashes()
            .into_iter()
            .map(|(category, message)| Value::from(vec![Value::from(category), Value::from(message)]))
            .collect();
        let ctx = context! {
            t => self.state.templates.translations.get(&lang).clone(),
            lang => lang,
            admin => self.user.is_admin(),
            current_user => self.user.user().map(Value::from_serialize),
            request => context! { blueprint => blueprint },
            __url => Value::from_object(self.url.clone()),
            __flashes => flashes,
            __item_extras => extras.map(Value::from_object),
            ..vars
        };
        self.state.templates.render(name, ctx).map(Html).map_err(|err| AppError::Internal(format!("{err:#}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn render(template: &str, ctx: Value) -> String {
        let mut env = Environment::new();
        env.set_formatter(jinja2_formatter);
        env.set_unknown_method_callback(minijinja_contrib::pycompat::unknown_method_callback);
        env.add_template("t.html", template).unwrap();
        env.get_template("t.html").unwrap().render(ctx).unwrap()
    }

    #[test]
    fn prints_like_jinja2() {
        assert_eq!(
            render("{{ a }}|{{ b }}|{{ c }}|{{ d }}|{{ e }}", context! { a => (), b => true, c => false, d => 3 }),
            "None|True|False|3|"
        );
        assert_eq!(
            render("{{ s }}", context! { s => "l'objet <b>\"x\"</b> & a/b" }),
            "l&#39;objet &lt;b&gt;&#34;x&#34;&lt;/b&gt; &amp; a/b"
        );
        assert_eq!(render("{{ s|safe }}", context! { s => "<b>" }), "<b>");
        assert_eq!(render("{{ c.lower().replace(' ', '_') }}", context! { c => "Board Game" }), "board_game");
    }

    #[test]
    fn dates_like_python_datetimes() {
        let date = date_value("2026-10-01 14:03:07.000120");
        assert_eq!(
            render("{{ d.strftime('%Y-%m-%d %H:%M') }}|{{ d }}", context! { d => date }),
            "2026-10-01 14:03|2026-10-01 14:03:07.000120"
        );
        assert_eq!(
            render("{{ d }}", context! { d => date_value("2026-10-01 14:03:07.000000") }),
            "2026-10-01 14:03:07"
        );
    }

    #[test]
    fn set_inside_if_is_visible_after_it() {
        // show.html sets `borrow` inside `{% if current_user %}` and reads it further down.
        assert_eq!(render("{% if x %}{% set y = 2 %}{% endif %}[{{ y }}]", context! { x => true }), "[2]");
    }

    #[test]
    fn all_templates_parse() {
        let templates = Templates::new().unwrap();
        for (name, _) in templates.env.templates() {
            templates.env.get_template(name).unwrap();
        }
        assert!(templates.env.templates().count() >= 26);
    }
}
