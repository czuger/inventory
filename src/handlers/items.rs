//! The item pages of all eight types (`inventory/api/routes/<type>.py`), written once.
//!
//! Each handler checks in the order Flask did, since that decides the status code when
//! several things are wrong at once:
//!
//! 1. the `<int:id>` in the URL (routing: anything else is a 404);
//! 2. the association slug (`url_value_preprocessor`: 404);
//! 3. the admin gate on `create`/`edit`/`delete`/... (`before_request`: 403);
//! 4. the item, within the association (`get_or_404`: 404);
//! 5. the form, field by field in the view's order (missing field 400, unknown game or
//!    location 404).

use std::collections::{BTreeMap, HashMap};

use axum::Router;
use axum::extract::{Extension, Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use minijinja::Value;
use minijinja::context;

use crate::AppState;
use crate::db::items::{self, Item, Values};
use crate::db::models::Association;
use crate::db::{borrowings, duplicates, legacy, refs};
use crate::error::AppError;
use crate::extract::{CurrentUser, FormData, py_int};
use crate::kinds::{CATEGORIES, ItemKind, SCALES, TABLECLOTH_MATERIALS, TABLECLOTH_SIZES};
use crate::labels::display_label;
use crate::templates::{ItemExtras, Page, date_value};
use crate::web::{parse_int_segment, redirect, redirect_with};

pub fn routes(kind: ItemKind) -> Router<AppState> {
    let base = format!("/{{slug}}/{}", kind.segment());
    Router::new()
        .route(&format!("{base}/"), get(index))
        .route(&format!("{base}/new"), get(create_form).post(create))
        .route(&format!("{base}/{{id}}"), get(show))
        .route(&format!("{base}/{{id}}/edit"), get(edit_form).post(edit))
        .route(&format!("{base}/{{id}}/delete"), post(delete))
        .layer(Extension(kind))
}

pub type Params = HashMap<String, String>;

/// The `<int:id>` of the URL.
pub fn item_id(params: &Params) -> Result<i64, AppError> {
    params.get("id").and_then(|id| parse_int_segment(id)).ok_or(AppError::NotFound)
}

/// `g.assoc`: the association the URL's slug names.
pub async fn association(state: &AppState, params: &Params) -> Result<Association, AppError> {
    let slug = params.get("slug").ok_or(AppError::UnknownAssociation)?;
    refs::association_by_slug(&state.pool, slug).await?.ok_or(AppError::UnknownAssociation)
}

/// The admin gate of `register_assoc_hooks`.
pub fn require_admin(user: &CurrentUser) -> Result<(), AppError> {
    if user.is_admin() { Ok(()) } else { Err(AppError::Forbidden) }
}

/// `get_or_404(Model, id)`: an item of another association is a 404 too.
pub async fn scoped_item(state: &AppState, kind: ItemKind, id: i64, assoc: &Association) -> Result<Item, AppError> {
    match items::get(&state.pool, kind, id).await? {
        Some(item) if item.association_id == assoc.id => Ok(item),
        _ => Err(AppError::NotFound),
    }
}

fn template(kind: ItemKind, page: &str) -> String {
    format!("{}/{page}.html", kind.template_dir())
}

fn sizes_inches() -> BTreeMap<&'static str, &'static str> {
    TABLECLOTH_SIZES.into_iter().collect()
}

/// The borrowing history and duplicate links of the page's item (see `ItemExtras`).
pub async fn item_extras(state: &AppState, assoc: &Association, item: &Item) -> Result<ItemExtras, AppError> {
    let history = borrowings::history(&state.pool, item.kind, item.id)
        .await?
        .into_iter()
        .map(|b| {
            context! {
                id => b.id,
                action => b.action,
                date => date_value(&b.date),
                borrower => Value::from_serialize(&b.borrower),
            }
        })
        .collect();

    let mut links = Vec::new();
    for link in duplicates::for_item(&state.pool, assoc.id, item.kind, item.id).await? {
        let (other_type, other_id) = link.other_end(item.kind.item_type(), item.id);
        // A link whose other end is gone (or never resolved) is skipped, as in Python.
        let Some(other_kind) = ItemKind::from_item_type(other_type) else { continue };
        let Some(other) = items::get(&state.pool, other_kind, other_id).await? else { continue };
        if other.association_id != assoc.id {
            continue;
        }
        links.push(context! {
            link_id => link.id,
            label => display_label(&other),
            endpoint => format!("{}.show", other_kind.blueprint()),
            other_id => other_id,
        });
    }
    Ok(ItemExtras { item_type: item.kind.item_type().to_owned(), item_id: item.id, history, duplicates: links })
}

async fn index(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
) -> Result<Response, AppError> {
    let assoc = association(&state, &params).await?;
    let items = items::list(&state.pool, kind, assoc.id).await?;
    let vars = context! { items => Value::from_serialize(&items), sizes_inches => sizes_inches() };
    Ok(page.with_slug(&assoc.slug).render(&template(kind, "list"), Some(kind.blueprint()), vars)?.into_response())
}

async fn show(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
) -> Result<Response, AppError> {
    // `/<slug>/<items>/<objectid>`: an old sticker's QR code. Flask routed it before
    // looking at the slug, which is passed on as is.
    if let Some(raw) = params.get("id")
        && legacy::is_object_id(raw)
    {
        let new_id = legacy::resolve(&state.pool, kind, raw).await?.ok_or(AppError::NotFound)?;
        let slug = params.get("slug").cloned().unwrap_or_default();
        let url =
            page.url().url_for(&format!("{}.show", kind.blueprint()), &[("slug", slug), ("id", new_id.to_string())])?;
        return Ok(redirect_with(&url, StatusCode::MOVED_PERMANENTLY));
    }
    let id = item_id(&params)?;
    let assoc = association(&state, &params).await?;
    let item = scoped_item(&state, kind, id, &assoc).await?;
    let extras = item_extras(&state, &assoc, &item).await?;
    let vars = context! { item => Value::from_serialize(&item), sizes_inches => sizes_inches() };
    Ok(page
        .with_slug(&assoc.slug)
        .render_with(&template(kind, "show"), Some(kind.blueprint()), vars, Some(extras))?
        .into_response())
}

/// What the form template needs besides the item (`_refs()` in each route module).
async fn form_refs(state: &AppState, kind: ItemKind, assoc: &Association) -> Result<Value, AppError> {
    let locations = refs::locations(&state.pool, assoc.id).await?;
    let games = if items::has_game(kind) { refs::games(&state.pool).await? } else { Vec::new() };
    Ok(context! {
        default_category => kind.category(),
        categories => CATEGORIES,
        locations => Value::from_serialize(&locations),
        games => Value::from_serialize(&games),
        scales => SCALES,
        sizes => TABLECLOTH_SIZES.map(|(cm, inches)| [cm, inches]),
        sizes_inches => sizes_inches(),
        materials => TABLECLOTH_MATERIALS,
    })
}

async fn create_form(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
) -> Result<Response, AppError> {
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let page = page.with_slug(&assoc.slug);
    let action = page.url().url_for(&format!("{}.create", kind.blueprint()), &[])?;
    let vars = context! { obj => (), action => action, ..form_refs(&state, kind, &assoc).await? };
    Ok(page.render(&template(kind, "form"), Some(kind.blueprint()), vars)?.into_response())
}

async fn edit_form(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
) -> Result<Response, AppError> {
    let id = item_id(&params)?;
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let item = scoped_item(&state, kind, id, &assoc).await?;
    let extras = item_extras(&state, &assoc, &item).await?;
    let page = page.with_slug(&assoc.slug);
    let action = page.url().url_for(&format!("{}.edit", kind.blueprint()), &[("id", item.id.to_string())])?;
    let vars = context! {
        obj => Value::from_serialize(&item),
        action => action,
        ..form_refs(&state, kind, &assoc).await?
    };
    Ok(page.render_with(&template(kind, "form"), Some(kind.blueprint()), vars, Some(extras))?.into_response())
}

/// One field of a type's form, in the order its view reads them.
#[derive(Clone, Copy)]
enum Field {
    Category,
    /// `request.form[name]`
    Text(&'static str),
    /// `request.form.get(name, '')`: an empty string is stored, not NULL.
    TextOrEmpty(&'static str),
    /// `request.form.get(name) or None`
    TextOrNone(&'static str),
    /// `name in request.form`
    Checkbox(&'static str),
    /// `get_or_404(Game, request.form['game'])`
    Game,
    /// `int(request.form.get('quantity') or <default>)`
    Quantity,
    /// `get_or_404(Location, request.form['location'])`, within the association.
    Location,
}

fn form_fields(kind: ItemKind) -> &'static [Field] {
    use Field::*;
    match kind {
        ItemKind::Miniature => &[Category, Text("type"), Game, Text("scale"), Quantity, Location],
        ItemKind::Terrain => &[Category, Text("type"), Game, Text("scale"), TextOrEmpty("theater"), Quantity, Location],
        ItemKind::Tablecloth => &[
            Category,
            Quantity,
            Text("type"),
            TextOrNone("material"),
            Game,
            Text("size"),
            TextOrNone("remarks"),
            Location,
        ],
        ItemKind::Rulebook => &[Category, Text("name"), Game, Checkbox("supplement"), Quantity, Location],
        ItemKind::BoardGame => &[Category, Text("name"), TextOrEmpty("universe"), Quantity, Location],
        ItemKind::Book => &[Category, Text("name"), TextOrEmpty("universe"), TextOrEmpty("period"), Quantity, Location],
        ItemKind::Equipment => &[Category, Text("type"), Quantity, Location],
        ItemKind::Consumable => &[Category, Text("type"), TextOrEmpty("unit"), Quantity, Location],
    }
}

/// `get_or_404` on an id from a form: not an integer, or not found, is a 404.
fn form_id(value: &str) -> Result<i64, AppError> {
    py_int(value).ok_or(AppError::NotFound)
}

async fn parse_form(
    state: &AppState,
    kind: ItemKind,
    assoc: &Association,
    form: &FormData,
    edit: bool,
) -> Result<Values, AppError> {
    let mut values = Values {
        category: String::new(),
        quantity: kind.default_quantity(),
        location_id: 0,
        own: Vec::new(),
        sticker_printed: edit.then(|| form.contains("sticker_printed")),
    };
    for field in form_fields(kind) {
        match *field {
            Field::Category => values.category = form.require("category")?.to_owned(),
            Field::Text(name) => values.own.push((name, items::Value::Text(form.require(name)?.to_owned()))),
            Field::TextOrEmpty(name) => {
                values.own.push((name, items::Value::OptText(Some(form.get(name).unwrap_or_default().to_owned()))));
            }
            Field::TextOrNone(name) => {
                let value = form.get(name).filter(|v| !v.is_empty()).map(str::to_owned);
                values.own.push((name, items::Value::OptText(value)));
            }
            Field::Checkbox(name) => values.own.push((name, items::Value::Bool(form.contains(name)))),
            Field::Game => {
                let game = refs::game(&state.pool, form_id(form.require("game")?)?).await?.ok_or(AppError::NotFound)?;
                values.own.push(("game_id", items::Value::Int(game.id)));
            }
            Field::Quantity => {
                // Python crashed (500) on a non-number here; it is a 400 now.
                if let Some(quantity) = form.get("quantity").filter(|q| !q.is_empty()) {
                    values.quantity = py_int(quantity).ok_or(AppError::BadRequest)?;
                }
            }
            Field::Location => {
                let location = refs::location(&state.pool, form_id(form.require("location")?)?).await?;
                values.location_id = location.filter(|l| l.association_id == assoc.id).ok_or(AppError::NotFound)?.id;
            }
        }
    }
    // The CHECK constraint, checked before the database would refuse it at commit (a 500
    // in Python, a 400 now) — after the other fields, as the commit came after them.
    let bad_material = values.own.iter().any(|(column, value)| {
        *column == "material"
            && matches!(value, items::Value::OptText(Some(material)) if !TABLECLOTH_MATERIALS.contains(&material.as_str()))
    });
    if bad_material {
        return Err(AppError::BadRequest);
    }
    Ok(values)
}

pub fn show_url(page: &Page, kind: ItemKind, id: i64) -> Result<String, AppError> {
    Ok(page.url().url_for(&format!("{}.show", kind.blueprint()), &[("id", id.to_string())])?)
}

async fn create(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
    form: FormData,
) -> Result<Response, AppError> {
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let values = parse_form(&state, kind, &assoc, &form, false).await?;
    let id = items::insert(&state.pool, kind, assoc.id, &values).await?;
    page.session().flash("success", &format!("{} created.", kind.noun()));
    let page = page.with_slug(&assoc.slug);
    Ok(redirect(&show_url(&page, kind, id)?))
}

async fn edit(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
    form: FormData,
) -> Result<Response, AppError> {
    let id = item_id(&params)?;
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let item = scoped_item(&state, kind, id, &assoc).await?;
    let values = parse_form(&state, kind, &assoc, &form, true).await?;
    items::update(&state.pool, kind, item.id, &values).await?;
    page.session().flash("success", &format!("{} updated.", kind.noun()));
    let page = page.with_slug(&assoc.slug);
    Ok(redirect(&show_url(&page, kind, item.id)?))
}

async fn delete(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
) -> Result<Response, AppError> {
    let id = item_id(&params)?;
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let item = scoped_item(&state, kind, id, &assoc).await?;
    items::delete(&state.pool, kind, item.id).await?;
    page.session().flash("success", &format!("{} deleted.", kind.noun()));
    let page = page.with_slug(&assoc.slug);
    Ok(redirect(&page.url().url_for(&format!("{}.index", kind.blueprint()), &[])?))
}
