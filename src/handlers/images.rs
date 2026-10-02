//! Item photos (`register_image_routes`): upload several at once, delete one. Admin only.

use axum::Router;
use axum::extract::multipart::MultipartRejection;
use axum::extract::{DefaultBodyLimit, Extension, Multipart, Path, State};
use axum::http::HeaderMap;
use axum::response::Response;
use axum::routing::post;

use crate::AppState;
use crate::db::items::{self, Item};
use crate::error::AppError;
use crate::handlers::items::{Params, association, item_id, require_admin, scoped_item, show_url};
use crate::kinds::ItemKind;
use crate::templates::Page;
use crate::upload::{item_dir, stored_name};
use crate::web::{redirect, referrer};

/// What nginx lets through (`client_max_body_size 32m`).
const MAX_UPLOAD: usize = 32 * 1024 * 1024;

pub fn routes(kind: ItemKind) -> Router<AppState> {
    let base = format!("/{{slug}}/{}", kind.segment());
    Router::new()
        .route(&format!("{base}/{{id}}/images"), post(upload_image).layer(DefaultBodyLimit::max(MAX_UPLOAD)))
        .route(&format!("{base}/{{id}}/images/{{filename}}/delete"), post(delete_image))
        .layer(Extension(kind))
}

/// The id, association, admin gate and item, in Flask's order.
async fn admin_item(state: &AppState, kind: ItemKind, params: &Params, page: &Page) -> Result<Item, AppError> {
    let id = item_id(params)?;
    let assoc = association(state, params).await?;
    require_admin(page.user())?;
    scoped_item(state, kind, id, &assoc).await
}

/// Back where the form was; Python crashed without a Referer, the item page now.
fn back(page: Page, headers: &HeaderMap, item: &Item, slug: &str) -> Result<Response, AppError> {
    let target = match referrer(headers) {
        Some(referrer) => referrer,
        None => show_url(&page.with_slug(slug), item.kind, item.id)?,
    };
    Ok(redirect(&target))
}

async fn upload_image(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
    headers: HeaderMap,
    multipart: Result<Multipart, MultipartRejection>,
) -> Result<Response, AppError> {
    let mut item = admin_item(&state, kind, &params, &page).await?;
    let dir = item_dir(&state.config.uploads_dir, &item.category_snake(), item.id);
    tokio::fs::create_dir_all(&dir).await.map_err(|err| AppError::Internal(format!("{}: {err}", dir.display())))?;

    // Not a multipart body: no files, as `request.files` would be empty.
    if let Ok(mut multipart) = multipart {
        while let Some(field) = multipart.next_field().await.map_err(|_| AppError::BadRequest)? {
            let original = match (field.name(), field.file_name()) {
                (Some("images"), Some(name)) if !name.is_empty() => name.to_owned(),
                _ => continue,
            };
            let data = field.bytes().await.map_err(|_| AppError::BadRequest)?;
            let filename = stored_name(&original);
            let path = dir.join(&filename);
            tokio::fs::write(&path, &data)
                .await
                .map_err(|err| AppError::Internal(format!("{}: {err}", path.display())))?;
            item.images.push(filename);
        }
    }
    items::set_images(&state.pool, kind, item.id, &item.images).await?;
    let slug = params.get("slug").cloned().unwrap_or_default();
    back(page, &headers, &item, &slug)
}

async fn delete_image(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    let mut item = admin_item(&state, kind, &params, &page).await?;
    let filename = params.get("filename").cloned().unwrap_or_default();
    // Only a name listed on the item is touched, so the URL cannot reach other files.
    if let Some(position) = item.images.iter().position(|image| *image == filename) {
        let path = item_dir(&state.config.uploads_dir, &item.category_snake(), item.id).join(&filename);
        match tokio::fs::remove_file(&path).await {
            Ok(()) => {}
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
            Err(err) => return Err(AppError::Internal(format!("{}: {err}", path.display()))),
        }
        item.images.remove(position);
        items::set_images(&state.pool, kind, item.id, &item.images).await?;
    }
    let slug = params.get("slug").cloned().unwrap_or_default();
    back(page, &headers, &item, &slug)
}
