//! Printing: each type's sticker sheet (`register_sticker_routes`) and the print page
//! (`routes/print_page.py`), which prints stickers or a list for everything, one
//! category, or only the items without a sticker yet. Admin only.
//!
//! Generating stickers **marks the items as printed**: the sheet is assumed to be printed
//! and stuck on. The list does not.

use axum::Router;
use axum::body::Body;
use axum::extract::{Extension, Path, RawQuery, State};
use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use minijinja::context;
use sqlx::Connection as _;

use crate::AppState;
use crate::db::items::{self, Item};
use crate::error::AppError;
use crate::extract::FormData;
use crate::handlers::items::{Params, association, require_admin};
use crate::kinds::{CATEGORIES, ItemKind};
use crate::labels::{list_row, sticker_lines};
use crate::pdf::{make_list_pdf, make_stickers_pdf};
use crate::templates::Page;
use crate::urls::UrlContext;

pub fn sticker_routes(kind: ItemKind) -> Router<AppState> {
    Router::new().route(&format!("/{{slug}}/{}/stickers", kind.segment()), get(type_stickers)).layer(Extension(kind))
}

pub fn print_routes() -> Router<AppState> {
    Router::new()
        .route("/{slug}/print/", get(index))
        .route("/{slug}/print/stickers", post(stickers))
        .route("/{slug}/print/list", post(print_list))
}

/// `send_file(BytesIO(pdf), mimetype='application/pdf', as_attachment=False, ...)`.
fn pdf_response(pdf: Vec<u8>, filename: &str) -> Response {
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "application/pdf".to_owned()),
            (header::CONTENT_DISPOSITION, format!("inline; filename={filename}")),
            (header::CACHE_CONTROL, "no-cache".to_owned()),
        ],
        Body::from(pdf),
    )
        .into_response()
}

/// `(lines, absolute URL of the item's page)` for each item.
fn sticker_data(items: &[Item], url: &UrlContext) -> Result<Vec<(Vec<String>, String)>, AppError> {
    items
        .iter()
        .map(|item| {
            let link =
                url.external_url_for(&format!("{}.show", item.kind.blueprint()), &[("id", item.id.to_string())])?;
            Ok((sticker_lines(item), link))
        })
        .collect()
}

/// Flags every item that went on the sheet, in one transaction.
async fn mark_printed(state: &AppState, items: &[Item]) -> Result<(), AppError> {
    let mut conn = state.pool.acquire().await?;
    let mut tx = conn.begin().await?;
    for kind in ItemKind::ALL {
        let ids: Vec<i64> = items.iter().filter(|item| item.kind == kind).map(|item| item.id).collect();
        items::mark_printed(&mut *tx, kind, &ids).await?;
    }
    tx.commit().await?;
    Ok(())
}

/// `/<slug>/<items>/stickers`: every item of the type.
async fn type_stickers(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
) -> Result<Response, AppError> {
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let items = items::list(&state.pool, kind, assoc.id).await?;
    let pdf = make_stickers_pdf(&sticker_data(&items, page.with_slug(&assoc.slug).url())?);
    mark_printed(&state, &items).await?;
    Ok(pdf_response(pdf, "stickers.pdf"))
}

async fn index(
    State(state): State<AppState>,
    Path(params): Path<Params>,
    RawQuery(query): RawQuery,
    page: Page,
) -> Result<Response, AppError> {
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let args = FormData::parse(query.unwrap_or_default().as_bytes());
    let vars = context! { categories => CATEGORIES, selected => args.get("category").unwrap_or_default() };
    Ok(page.with_slug(&assoc.slug).render("print/index.html", Some("print_page"), vars)?.into_response())
}

/// `_scope()`: the category to keep (`None` for all), and whether to skip printed items.
fn scope(form: &FormData) -> (Option<String>, bool) {
    let mode = form.get("mode").unwrap_or("full");
    let category = if mode == "category" { form.get("category").unwrap_or_default() } else { "" };
    ((!category.is_empty()).then(|| category.to_owned()), mode == "new")
}

/// The items in scope, type by type in the print page's order.
async fn items_in_scope(
    state: &AppState,
    association_id: i64,
    form: &FormData,
) -> Result<(Option<String>, Vec<Item>), AppError> {
    let (category, new_only) = scope(form);
    let mut selected = Vec::new();
    for kind in ItemKind::ALL {
        if category.as_deref().is_some_and(|category| category != kind.category()) {
            continue;
        }
        let items = items::list(&state.pool, kind, association_id).await?;
        selected.extend(items.into_iter().filter(|item| !(new_only && item.sticker_printed)));
    }
    Ok((category, selected))
}

async fn stickers(
    State(state): State<AppState>,
    Path(params): Path<Params>,
    page: Page,
    form: FormData,
) -> Result<Response, AppError> {
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let (_, items) = items_in_scope(&state, assoc.id, &form).await?;
    let pdf = make_stickers_pdf(&sticker_data(&items, page.with_slug(&assoc.slug).url())?);
    mark_printed(&state, &items).await?;
    Ok(pdf_response(pdf, "stickers.pdf"))
}

async fn print_list(
    State(state): State<AppState>,
    Path(params): Path<Params>,
    page: Page,
    form: FormData,
) -> Result<Response, AppError> {
    let assoc = association(&state, &params).await?;
    require_admin(page.user())?;
    let (category, items) = items_in_scope(&state, assoc.id, &form).await?;
    let rows: Vec<_> = items.iter().map(list_row).collect();
    let title = category.unwrap_or_else(|| "Inventaire".to_owned());
    Ok(pdf_response(make_list_pdf(&title, &rows), "list.pdf"))
}
