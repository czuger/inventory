//! Item photos: upload, display, delete (no Python tests covered them).
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::body::Body;
use axum::http::{Request, StatusCode, header};

use common::{Client, Seed, TestDb};
use inventory::db::items::{self, Value, Values};
use inventory::kinds::ItemKind;

async fn make_board_game(db: &TestDb, seed: &Seed) -> i64 {
    let values = Values {
        category: "Board Game".into(),
        quantity: 1,
        location_id: seed.loc,
        own: vec![("name", Value::Text("Chess".into())), ("universe", Value::OptText(None))],
        sticker_printed: None,
    };
    items::insert(&db.pool, ItemKind::BoardGame, seed.assoc, &values).await.unwrap()
}

fn multipart(files: &[(&str, &str, &[u8])]) -> (String, Vec<u8>) {
    let boundary = "XBOUNDARYX";
    let mut body = Vec::new();
    for (field, filename, data) in files {
        body.extend_from_slice(
            format!(
                "--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n\
                 Content-Type: image/jpeg\r\n\r\n"
            )
            .as_bytes(),
        );
        body.extend_from_slice(data);
        body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
    (format!("multipart/form-data; boundary={boundary}"), body)
}

async fn images_of(db: &TestDb, id: i64) -> Vec<String> {
    let json: String =
        sqlx::query_scalar("SELECT images FROM board_games WHERE id = ?").bind(id).fetch_one(&db.pool).await.unwrap();
    serde_json::from_str(&json).unwrap()
}

#[tokio::test]
async fn upload_show_delete() {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let id = make_board_game(&db, &seed).await;
    let mut admin = Client::new(db.app());
    admin.login(seed.admin);

    let (content_type, body) =
        multipart(&[("images", "Partie d'été.jpg", b"one"), ("images", "", b""), ("images", "b.png", b"two")]);
    let request = Request::post(format!("/test/board-games/{id}/images"))
        .header(header::CONTENT_TYPE, content_type)
        .header(header::REFERER, "http://localhost/back")
        .body(Body::from(body))
        .unwrap();
    let response = admin.send(request).await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert_eq!(response.headers[header::LOCATION], "http://localhost/back");

    // The empty file input is skipped; names are uuid-prefixed and sanitized.
    let images = images_of(&db, id).await;
    assert_eq!(images.len(), 2);
    assert!(images[0].ends_with("_Partie_dete.jpg"), "{images:?}");
    assert!(images[1].ends_with("_b.png"));
    let stored = db.config().uploads_dir.join(format!("board_game/{id}")).join(&images[0]);
    assert_eq!(std::fs::read(&stored).unwrap(), b"one");
    // The column is written as json.dumps would.
    let raw: String = sqlx::query_scalar("SELECT images FROM board_games").fetch_one(&db.pool).await.unwrap();
    assert_eq!(raw, format!("[\"{}\", \"{}\"]", images[0], images[1]));

    // Shown, and served.
    let page = admin.get(&format!("/test/board-games/{id}")).await;
    let src = format!("/static/uploads/board_game/{id}/{}", images[0]);
    assert!(page.body.contains(&src), "{}", page.body);
    assert_eq!(admin.get(&src).await.body, "one");

    // Delete one: file and list entry go.
    let response = admin.post(&format!("/test/board-games/{id}/images/{}/delete", images[0])).await;
    assert_eq!(response.headers[header::LOCATION], format!("/test/board-games/{id}"));
    assert!(!stored.exists());
    assert_eq!(images_of(&db, id).await, vec![images[1].clone()]);

    // A name that is not the item's is ignored.
    admin.post(&format!("/test/board-games/{id}/images/..%2Fsecret/delete")).await;
    assert_eq!(images_of(&db, id).await.len(), 1);
}

#[tokio::test]
async fn admin_only_and_tolerant() {
    let db = TestDb::new().await;
    let seed = db.seed().await;
    let id = make_board_game(&db, &seed).await;
    let mut user = Client::new(db.app());
    user.login(seed.user);
    let (content_type, body) = multipart(&[("images", "a.jpg", b"x")]);
    let request = Request::post(format!("/test/board-games/{id}/images"))
        .header(header::CONTENT_TYPE, content_type)
        .body(Body::from(body))
        .unwrap();
    assert_eq!(user.send(request).await.status, StatusCode::FORBIDDEN);
    assert_eq!(user.post(&format!("/test/board-games/{id}/images/a.jpg/delete")).await.status, StatusCode::FORBIDDEN);

    // Not multipart at all: nothing saved, still a redirect (as Flask with no files).
    let mut admin = Client::new(db.app());
    admin.login(seed.admin);
    let response = admin.post(&format!("/test/board-games/{id}/images")).await;
    assert_eq!(response.status, StatusCode::FOUND);
    assert!(images_of(&db, id).await.is_empty());
}
