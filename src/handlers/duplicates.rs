//! Suspected-duplicate links (`register_duplicate_routes`): an admin pastes the URL of
//! another item, of any type, to link the two; either end can remove the link.

use axum::Router;
use axum::extract::{Extension, Path, State};
use axum::http::HeaderMap;
use axum::response::Response;
use axum::routing::post;

use crate::AppState;
use crate::db::{duplicates, items, legacy};
use crate::error::AppError;
use crate::extract::FormData;
use crate::handlers::items::{Params, association, item_id, scoped_item, show_url};
use crate::kinds::ItemKind;
use crate::templates::Page;
use crate::web::{parse_int_segment, redirect, referrer};

pub fn routes(kind: ItemKind) -> Router<AppState> {
    let base = format!("/{{slug}}/{}", kind.segment());
    Router::new()
        .route(&format!("{base}/{{id}}/duplicates"), post(add_duplicate))
        .route(&format!("{base}/{{id}}/duplicates/{{link_id}}/delete"), post(delete_duplicate))
        .layer(Extension(kind))
}

/// The path of a pasted URL (`urlparse(url).path`), without the app's URL prefix.
fn url_path<'a>(url: &'a str, script_name: &str) -> &'a str {
    let url = url.trim();
    let url = url.split(['?', '#']).next().unwrap_or_default();
    let path = match url.find("://").map(|i| &url[i + 3..]).or_else(|| url.strip_prefix("//")) {
        Some(after_scheme) => after_scheme.find('/').map_or("", |slash| &after_scheme[slash..]),
        None => url,
    };
    // Python looked for the type in the second segment even under a prefix, so a URL
    // copied in production (`/inventory/<slug>/<items>/<id>`) never matched; fixed here.
    match path.strip_prefix(script_name) {
        Some(rest) if !script_name.is_empty() && rest.starts_with('/') => rest,
        _ => path,
    }
}

/// `_parse_item_url`: the type and id of an item URL; an ObjectId from an old sticker
/// is resolved to the new id. `(type, None)` when only the id is unusable.
pub async fn parse_item_url(
    state: &AppState,
    url: &str,
    script_name: &str,
) -> Result<(Option<ItemKind>, Option<i64>), AppError> {
    let parts: Vec<&str> = url_path(url, script_name).split('/').filter(|part| !part.is_empty()).collect();
    if parts.len() < 3 {
        return Ok((None, None));
    }
    let kind = ItemKind::from_segment(parts[1]);
    let raw_id = parts[2];
    let id = if let Some(id) = parse_int_segment(raw_id) {
        Some(id)
    } else if let (Some(kind), true) = (kind, legacy::is_object_id(raw_id)) {
        legacy::resolve(&state.pool, kind, raw_id).await?
    } else {
        None
    };
    Ok((kind, id))
}

async fn add_duplicate(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
    headers: HeaderMap,
    form: FormData,
) -> Result<Response, AppError> {
    let id = item_id(&params)?;
    let assoc = association(&state, &params).await?;
    if !page.user().is_admin() {
        return Err(AppError::Forbidden);
    }
    let item = scoped_item(&state, kind, id, &assoc).await?;
    let page = page.with_slug(&assoc.slug);
    let fallback = match referrer(&headers) {
        Some(referrer) => referrer,
        None => show_url(&page, kind, item.id)?,
    };
    let session = page.session();

    let url = form.get("duplicate_url").unwrap_or_default();
    let (other_kind, other_id) = parse_item_url(&state, url, &page.url().script_name).await?;
    let (Some(other_kind), Some(other_id)) = (other_kind, other_id.filter(|id| *id != 0)) else {
        session.flash("danger", "Invalid item URL.");
        return Ok(redirect(&fallback));
    };
    if other_kind == kind && other_id == item.id {
        session.flash("warning", "Cannot link an item to itself.");
        return Ok(redirect(&fallback));
    }
    let this_end = (kind.item_type(), item.id);
    let other_end = (other_kind.item_type(), other_id);
    if duplicates::exists(&state.pool, assoc.id, this_end, other_end).await? {
        session.flash("warning", "This link already exists.");
        return Ok(redirect(&fallback));
    }
    let other_exists =
        items::get(&state.pool, other_kind, other_id).await?.is_some_and(|o| o.association_id == assoc.id);
    if !other_exists {
        session.flash("danger", "Linked item not found.");
        return Ok(redirect(&fallback));
    }
    duplicates::insert(&state.pool, assoc.id, this_end, other_end).await?;
    session.flash("success", "Suspected duplicate link added.");
    Ok(redirect(&fallback))
}

async fn delete_duplicate(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    let id = item_id(&params)?;
    let link_id = params.get("link_id").and_then(|id| parse_int_segment(id)).ok_or(AppError::NotFound)?;
    let assoc = association(&state, &params).await?;
    if !page.user().is_admin() {
        return Err(AppError::Forbidden);
    }
    let item = scoped_item(&state, kind, id, &assoc).await?;
    if duplicates::delete(&state.pool, assoc.id, link_id).await? {
        page.session().flash("success", "Duplicate link removed.");
    }
    let target = match referrer(&headers) {
        Some(referrer) => referrer,
        None => show_url(&page.with_slug(&assoc.slug), kind, item.id)?,
    };
    Ok(redirect(&target))
}

#[cfg(test)]
mod tests {
    use super::url_path;

    #[test]
    fn paths_of_pasted_urls() {
        assert_eq!(url_path(" http://localhost/test/miniatures/5?x=1#top ", ""), "/test/miniatures/5");
        assert_eq!(url_path("https://apps.ieroe.com/inventory/test/miniatures/5", "/inventory"), "/test/miniatures/5");
        assert_eq!(url_path("/inventory_staging/test/books/2", "/inventory"), "/inventory_staging/test/books/2");
        assert_eq!(url_path("test/books/2", ""), "test/books/2");
        assert_eq!(url_path("not-a-url", ""), "not-a-url");
        assert_eq!(url_path("https://example.com", ""), "");
    }
}
