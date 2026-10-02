//! Borrowing and returning (`register_borrow_routes`). Any logged-in user may do either;
//! each writes a `Borrowing` event and moves the item's `borrowing_count`.

use axum::Router;
use axum::extract::{Extension, Path, State};
use axum::http::HeaderMap;
use axum::response::Response;
use axum::routing::post;
use sqlx::Connection as _;

use crate::AppState;
use crate::db::{borrowings, items};
use crate::error::AppError;
use crate::handlers::items::{Params, association, item_id, scoped_item, show_url};
use crate::kinds::ItemKind;
use crate::templates::Page;
use crate::web::{redirect, referrer};

pub fn routes(kind: ItemKind) -> Router<AppState> {
    let base = format!("/{{slug}}/{}", kind.segment());
    Router::new()
        .route(&format!("{base}/{{id}}/borrow"), post(borrow))
        .route(&format!("{base}/{{id}}/return"), post(return_item))
        .layer(Extension(kind))
}

async fn borrow(
    state: State<AppState>,
    kind: Extension<ItemKind>,
    params: Path<Params>,
    page: Page,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    act(state, kind, params, page, headers, true).await
}

async fn return_item(
    state: State<AppState>,
    kind: Extension<ItemKind>,
    params: Path<Params>,
    page: Page,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    act(state, kind, params, page, headers, false).await
}

async fn act(
    State(state): State<AppState>,
    Extension(kind): Extension<ItemKind>,
    Path(params): Path<Params>,
    page: Page,
    headers: HeaderMap,
    borrowed: bool,
) -> Result<Response, AppError> {
    let id = item_id(&params)?;
    let assoc = association(&state, &params).await?;
    let user = page.user().user().ok_or(AppError::Unauthorized)?;
    let item = scoped_item(&state, kind, id, &assoc).await?;

    let mut conn = state.pool.acquire().await?;
    let mut tx = conn.begin().await?;
    let action = if borrowed { "borrow" } else { "return" };
    borrowings::record(&mut *tx, assoc.id, user.id, kind, item.id, action).await?;
    items::adjust_borrowing_count(&mut *tx, kind, item.id, borrowed).await?;
    tx.commit().await?;

    // Python redirected to the referrer and crashed without one; the item page instead.
    let target = match referrer(&headers) {
        Some(referrer) => referrer,
        None => show_url(&page.with_slug(&assoc.slug), kind, item.id)?,
    };
    Ok(redirect(&target))
}
