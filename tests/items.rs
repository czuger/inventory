//! The item pages of all eight types: ported from `tests/test_items.py` (whose
//! `TestItemCRUD` is parametrized over `ITEM_CONFIGS`; here each test loops over them),
//! plus what that suite left implicit.
#![allow(clippy::unwrap_used, clippy::expect_used)]

mod common;

use axum::http::{StatusCode, header};
use sqlx::AssertSqlSafe;

use common::{Client, Seed, TestDb};
use inventory::db::items::{self, Value, Values};
use inventory::kinds::ItemKind;

/// `ITEM_CONFIGS`: how to make an item directly, the form that creates the same one, and
/// the field the edit test changes.
struct Config {
    kind: ItemKind,
    quantity: i64,
    own: fn(&Seed) -> Vec<(&'static str, Value)>,
    form: fn(&Seed) -> Vec<(&'static str, String)>,
    edit_field: (&'static str, &'static str),
}

fn text(value: &str) -> Value {
    Value::Text(value.to_owned())
}

fn configs() -> Vec<Config> {
    vec![
        Config {
            kind: ItemKind::Miniature,
            quantity: 2,
            own: |s| vec![("type", text("Infantry")), ("game_id", Value::Int(s.game)), ("scale", text("28mm"))],
            form: |s| vec![("type", "Infantry".into()), ("game", s.game.to_string()), ("scale", "28mm".into())],
            edit_field: ("type", "Cavalry"),
        },
        Config {
            kind: ItemKind::Terrain,
            quantity: 1,
            own: |s| {
                vec![
                    ("type", text("Forest")),
                    ("game_id", Value::Int(s.game)),
                    ("scale", text("28mm")),
                    ("theater", Value::OptText(None)),
                ]
            },
            form: |s| vec![("type", "Forest".into()), ("game", s.game.to_string()), ("scale", "28mm".into())],
            edit_field: ("type", "Hills"),
        },
        Config {
            kind: ItemKind::Tablecloth,
            quantity: 1,
            own: |s| {
                vec![
                    ("type", text("Green Field")),
                    ("material", Value::OptText(None)),
                    ("game_id", Value::Int(s.game)),
                    ("size", text("120x180")),
                    ("remarks", Value::OptText(None)),
                ]
            },
            form: |s| vec![("type", "Green Field".into()), ("game", s.game.to_string()), ("size", "120x180".into())],
            edit_field: ("type", "Blue Sea"),
        },
        Config {
            kind: ItemKind::Rulebook,
            quantity: 1,
            own: |s| {
                vec![("name", text("Core Rules")), ("game_id", Value::Int(s.game)), ("supplement", Value::Bool(false))]
            },
            form: |s| vec![("name", "Core Rules".into()), ("game", s.game.to_string())],
            edit_field: ("name", "Advanced Rules"),
        },
        Config {
            kind: ItemKind::BoardGame,
            quantity: 1,
            own: |_| vec![("name", text("Chess")), ("universe", Value::OptText(None))],
            form: |_| vec![("name", "Chess".into())],
            edit_field: ("name", "Checkers"),
        },
        Config {
            kind: ItemKind::Book,
            quantity: 1,
            own: |_| {
                vec![
                    ("name", text("War History")),
                    ("universe", Value::OptText(None)),
                    ("period", Value::OptText(None)),
                ]
            },
            form: |_| vec![("name", "War History".into())],
            edit_field: ("name", "Peace History"),
        },
        Config {
            kind: ItemKind::Equipment,
            quantity: 1,
            own: |_| vec![("type", text("Brush"))],
            form: |_| vec![("type", "Brush".into())],
            edit_field: ("type", "Dice Bag"),
        },
        Config {
            kind: ItemKind::Consumable,
            quantity: 3,
            own: |_| vec![("type", text("Paint")), ("unit", Value::OptText(None))],
            form: |_| vec![("type", "Paint".into())],
            edit_field: ("type", "Varnish"),
        },
    ]
}

/// A fresh database, its seed, and an item made the way `cfg['make']` did.
struct Fixture {
    db: TestDb,
    seed: Seed,
    item: i64,
}

impl Fixture {
    async fn new(cfg: &Config) -> Self {
        let db = TestDb::new().await;
        let seed = db.seed().await;
        let values = Values {
            category: cfg.kind.category().to_owned(),
            quantity: cfg.quantity,
            location_id: seed.loc,
            own: (cfg.own)(&seed),
            sticker_printed: None,
        };
        let item = items::insert(&db.pool, cfg.kind, seed.assoc, &values).await.unwrap();
        Self { db, seed, item }
    }

    fn client(&self, user: Option<i64>) -> Client {
        let mut client = Client::new(self.db.app());
        if let Some(user) = user {
            client.login(user);
        }
        client
    }

    fn url(&self, cfg: &Config, rest: &str) -> String {
        format!("/test/{}/{rest}", cfg.kind.segment())
    }

    async fn column(&self, cfg: &Config, column: &str, id: i64) -> Option<String> {
        let sql = format!("SELECT CAST({column} AS TEXT) FROM {} WHERE id = ?", cfg.kind.table());
        sqlx::query_scalar(AssertSqlSafe(sql)).bind(id).fetch_optional(&self.db.pool).await.unwrap().flatten()
    }

    async fn count(&self, cfg: &Config) -> i64 {
        self.db.count(&format!("SELECT count(*) FROM {}", cfg.kind.table())).await
    }
}

/// `cfg['form'](db)` with the shared fields.
fn full_form(cfg: &Config, seed: &Seed) -> Vec<(&'static str, String)> {
    let mut form = vec![("category", cfg.kind.category().to_owned())];
    form.extend((cfg.form)(seed));
    form.push(("quantity", cfg.quantity.to_string()));
    form.push(("location", seed.loc.to_string()));
    form
}

fn pairs<'a>(form: &'a [(&'static str, String)]) -> Vec<(&'static str, &'a str)> {
    form.iter().map(|(k, v)| (*k, v.as_str())).collect()
}

// --- TestItemCRUD ------------------------------------------------------------------

#[tokio::test]
async fn test_index() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let response = fx.client(Some(fx.seed.admin)).get(&fx.url(&cfg, "")).await;
        assert_eq!(response.status, StatusCode::OK, "{:?}", cfg.kind);
        assert_eq!(response.headers[header::CONTENT_TYPE], "text/html; charset=utf-8");
    }
}

#[tokio::test]
async fn test_create() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let before = fx.count(&cfg).await;
        let mut client = fx.client(Some(fx.seed.admin));
        let response = client.post_form(&fx.url(&cfg, "new"), &pairs(&full_form(&cfg, &fx.seed))).await;
        assert_eq!(response.status, StatusCode::FOUND, "{:?}: {}", cfg.kind, response.body);
        let shown = client.follow(response).await;
        assert_eq!(shown.status, StatusCode::OK, "{:?}", cfg.kind);
        assert_eq!(fx.count(&cfg).await, before + 1, "{:?}", cfg.kind);
        let flash = format!("{} created.", cfg.kind.noun());
        assert!(shown.body.contains(&flash), "{:?}: no flash {flash:?}", cfg.kind);
    }
}

#[tokio::test]
async fn test_show() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let response = fx.client(Some(fx.seed.admin)).get(&fx.url(&cfg, &fx.item.to_string())).await;
        assert_eq!(response.status, StatusCode::OK, "{:?}: {}", cfg.kind, response.body);
    }
}

#[tokio::test]
async fn test_edit() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let (field, new_value) = cfg.edit_field;
        let mut form = full_form(&cfg, &fx.seed);
        for (key, value) in &mut form {
            if *key == field {
                *value = new_value.to_owned();
            }
        }
        let mut client = fx.client(Some(fx.seed.admin));
        let response = client.post_form(&fx.url(&cfg, &format!("{}/edit", fx.item)), &pairs(&form)).await;
        assert_eq!(client.follow(response).await.status, StatusCode::OK, "{:?}", cfg.kind);
        assert_eq!(fx.column(&cfg, field, fx.item).await.as_deref(), Some(new_value), "{:?}", cfg.kind);
    }
}

#[tokio::test]
async fn test_delete() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let mut client = fx.client(Some(fx.seed.admin));
        let response = client.post(&fx.url(&cfg, &format!("{}/delete", fx.item))).await;
        assert_eq!(response.headers[header::LOCATION], fx.url(&cfg, ""), "{:?}", cfg.kind);
        assert_eq!(fx.count(&cfg).await, 0, "{:?}", cfg.kind);
    }
}

#[tokio::test]
async fn test_create_requires_admin() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let response =
            fx.client(Some(fx.seed.user)).post_form(&fx.url(&cfg, "new"), &pairs(&full_form(&cfg, &fx.seed))).await;
        assert_eq!(response.status, StatusCode::FORBIDDEN, "{:?}", cfg.kind);
        assert_eq!(fx.count(&cfg).await, 1);
    }
}

#[tokio::test]
async fn test_edit_requires_admin() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let url = fx.url(&cfg, &format!("{}/edit", fx.item));
        let response = fx.client(Some(fx.seed.user)).post_form(&url, &pairs(&full_form(&cfg, &fx.seed))).await;
        assert_eq!(response.status, StatusCode::FORBIDDEN, "{:?}", cfg.kind);
    }
}

#[tokio::test]
async fn test_delete_requires_admin() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let response = fx.client(Some(fx.seed.user)).post(&fx.url(&cfg, &format!("{}/delete", fx.item))).await;
        assert_eq!(response.status, StatusCode::FORBIDDEN, "{:?}", cfg.kind);
        assert_eq!(fx.count(&cfg).await, 1);
    }
}

async fn borrow_events(fx: &Fixture, cfg: &Config, action: &str) -> i64 {
    let sql = format!(
        "SELECT count(*) FROM borrowings WHERE item_id = {} AND item_type = '{}' AND action = '{action}'",
        fx.item,
        cfg.kind.item_type()
    );
    fx.db.count(&sql).await
}

#[tokio::test]
async fn test_borrow() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let mut client = fx.client(Some(fx.seed.user));
        let response = client.post(&fx.url(&cfg, &format!("{}/borrow", fx.item))).await;
        assert_eq!(client.follow(response).await.status, StatusCode::OK, "{:?}", cfg.kind);
        assert_eq!(fx.column(&cfg, "borrowing_count", fx.item).await.as_deref(), Some("1"), "{:?}", cfg.kind);
        assert_eq!(borrow_events(&fx, &cfg, "borrow").await, 1, "{:?}", cfg.kind);
    }
}

#[tokio::test]
async fn test_return() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let sql = format!("UPDATE {} SET borrowing_count = 1 WHERE id = ?", cfg.kind.table());
        sqlx::query(AssertSqlSafe(sql)).bind(fx.item).execute(&fx.db.pool).await.unwrap();
        let mut client = fx.client(Some(fx.seed.user));
        let response = client.post(&fx.url(&cfg, &format!("{}/return", fx.item))).await;
        assert_eq!(client.follow(response).await.status, StatusCode::OK, "{:?}", cfg.kind);
        assert_eq!(fx.column(&cfg, "borrowing_count", fx.item).await.as_deref(), Some("0"), "{:?}", cfg.kind);
        assert_eq!(borrow_events(&fx, &cfg, "return").await, 1, "{:?}", cfg.kind);
    }
}

#[tokio::test]
async fn test_borrow_requires_auth() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let response = fx.client(None).post(&fx.url(&cfg, &format!("{}/borrow", fx.item))).await;
        assert_eq!(response.status, StatusCode::UNAUTHORIZED, "{:?}", cfg.kind);
        assert_eq!(borrow_events(&fx, &cfg, "borrow").await, 0);
    }
}

#[tokio::test]
async fn test_stickers_marks_printed() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        assert_eq!(fx.column(&cfg, "sticker_printed", fx.item).await.as_deref(), Some("0"));
        let response = fx.client(Some(fx.seed.admin)).get(&fx.url(&cfg, "stickers")).await;
        assert_eq!(response.status, StatusCode::OK, "{:?}", cfg.kind);
        assert_eq!(response.headers[header::CONTENT_TYPE], "application/pdf", "{:?}", cfg.kind);
        assert_eq!(fx.column(&cfg, "sticker_printed", fx.item).await.as_deref(), Some("1"), "{:?}", cfg.kind);
        // Admin only.
        let user = fx.client(Some(fx.seed.user)).get(&fx.url(&cfg, "stickers")).await;
        assert_eq!(user.status, StatusCode::FORBIDDEN, "{:?}", cfg.kind);
    }
}

async fn set_printed(fx: &Fixture, cfg: &Config) {
    let sql = format!("UPDATE {} SET sticker_printed = 1 WHERE id = ?", cfg.kind.table());
    sqlx::query(AssertSqlSafe(sql)).bind(fx.item).execute(&fx.db.pool).await.unwrap();
}

#[tokio::test]
async fn test_edit_resets_sticker() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        set_printed(&fx, &cfg).await;
        let url = fx.url(&cfg, &format!("{}/edit", fx.item));
        fx.client(Some(fx.seed.admin)).post_form(&url, &pairs(&full_form(&cfg, &fx.seed))).await;
        assert_eq!(fx.column(&cfg, "sticker_printed", fx.item).await.as_deref(), Some("0"), "{:?}", cfg.kind);
    }
}

#[tokio::test]
async fn test_edit_keeps_sticker_when_checked() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        set_printed(&fx, &cfg).await;
        let mut form = full_form(&cfg, &fx.seed);
        form.push(("sticker_printed", "on".into()));
        let url = fx.url(&cfg, &format!("{}/edit", fx.item));
        fx.client(Some(fx.seed.admin)).post_form(&url, &pairs(&form)).await;
        assert_eq!(fx.column(&cfg, "sticker_printed", fx.item).await.as_deref(), Some("1"), "{:?}", cfg.kind);
    }
}

// --- from tests/test_database.py ---------------------------------------------------

#[tokio::test]
async fn test_item_of_another_association_is_404() {
    let cfg = &configs()[0];
    let fx = Fixture::new(cfg).await;
    let other: i64 =
        sqlx::query_scalar("INSERT INTO associations (name, slug) VALUES ('Other Asso', 'other') RETURNING id")
            .fetch_one(&fx.db.pool)
            .await
            .unwrap();
    let other_loc: i64 = sqlx::query_scalar(
        "INSERT INTO locations (association_id, room, spot) VALUES (?, 'Elsewhere', '') RETURNING id",
    )
    .bind(other)
    .fetch_one(&fx.db.pool)
    .await
    .unwrap();
    let values = Values {
        category: "Miniature".into(),
        quantity: 1,
        location_id: other_loc,
        own: (cfg.own)(&fx.seed),
        sticker_printed: None,
    };
    let item = items::insert(&fx.db.pool, cfg.kind, other, &values).await.unwrap();
    let mut client = fx.client(Some(fx.seed.admin));
    assert_eq!(client.get(&format!("/test/miniatures/{item}")).await.status, StatusCode::NOT_FOUND);
    assert_eq!(client.get(&format!("/other/miniatures/{item}")).await.status, StatusCode::OK);
    assert_eq!(client.get(&format!("/test/miniatures/{item}/edit")).await.status, StatusCode::NOT_FOUND);
    assert_eq!(client.post(&format!("/test/miniatures/{item}/delete")).await.status, StatusCode::NOT_FOUND);

    // Nor can a form point at another association's location.
    let mut form = full_form(cfg, &fx.seed);
    form.retain(|(key, _)| *key != "location");
    let other_loc = other_loc.to_string();
    form.push(("location", other_loc));
    assert_eq!(client.post_form("/test/miniatures/new", &pairs(&form)).await.status, StatusCode::NOT_FOUND);
}

// --- what the Python suite left implicit -------------------------------------------

#[tokio::test]
async fn pages_render_the_items() {
    for cfg in configs() {
        let fx = Fixture::new(&cfg).await;
        let mut anonymous = fx.client(None);
        let list = anonymous.get(&fx.url(&cfg, "")).await;
        assert_eq!(list.status, StatusCode::OK);
        let (_, name) = (cfg.own)(&fx.seed)[0].clone();
        let Value::Text(name) = name else { unreachable!() };
        assert!(list.body.contains(&name), "{:?}: list lacks {name:?}", cfg.kind);
        assert!(!list.body.contains("bi-pencil"), "{:?}: no edit buttons for anonymous", cfg.kind);
        assert!(list.body.contains("<title>"), "{:?}", cfg.kind);

        let mut admin = fx.client(Some(fx.seed.admin));
        assert!(admin.get(&fx.url(&cfg, "")).await.body.contains("bi-pencil"), "{:?}", cfg.kind);
        let form = admin.get(&fx.url(&cfg, &format!("{}/edit", fx.item))).await;
        assert_eq!(form.status, StatusCode::OK, "{:?}: {}", cfg.kind, form.body);
        assert!(form.body.contains(&format!("action=\"/test/{}/{}/edit\"", cfg.kind.segment(), fx.item)));
        let new = admin.get(&fx.url(&cfg, "new")).await;
        assert_eq!(new.status, StatusCode::OK, "{:?}: {}", cfg.kind, new.body);
        assert!(new.body.contains(&format!("value=\"{}\"", cfg.kind.category())), "{:?}", cfg.kind);
    }
}

#[tokio::test]
async fn gates_in_flask_order() {
    let cfg = &configs()[0];
    let fx = Fixture::new(cfg).await;
    let mut user = fx.client(Some(fx.seed.user));
    // The form page is gated too, not only the POST.
    assert_eq!(user.get("/test/miniatures/new").await.status, StatusCode::FORBIDDEN);
    // An unknown slug is a 404 before the admin gate.
    assert_eq!(user.get("/nope/miniatures/new").await.status, StatusCode::NOT_FOUND);
    assert_eq!(user.get("/nope/miniatures/").await.status, StatusCode::NOT_FOUND);
    // A non-integer id is a 404 before anything else.
    assert_eq!(user.get("/test/miniatures/abc/edit").await.status, StatusCode::NOT_FOUND);
    assert_eq!(fx.client(None).get("/test/miniatures/abc").await.status, StatusCode::NOT_FOUND);
    // `<int:id>` takes leading zeros.
    let padded = format!("/test/miniatures/00{}", fx.item);
    assert_eq!(fx.client(None).get(&padded).await.status, StatusCode::OK);
    // Delete only takes POST.
    let get_delete = user.get(&format!("/test/miniatures/{}/delete", fx.item)).await;
    assert_eq!(get_delete.status, StatusCode::METHOD_NOT_ALLOWED);
}

#[tokio::test]
async fn form_errors() {
    let cfg = &configs()[0];
    let fx = Fixture::new(cfg).await;
    let mut admin = fx.client(Some(fx.seed.admin));
    let form = full_form(cfg, &fx.seed);
    let without =
        |key: &str| -> Vec<(&'static str, String)> { form.iter().filter(|(k, _)| *k != key).cloned().collect() };
    let with = |key: &'static str, value: &str| -> Vec<(&'static str, String)> {
        let mut f = without(key);
        f.push((key, value.to_owned()));
        f
    };
    for (name, form, status) in [
        ("missing type", without("type"), StatusCode::BAD_REQUEST),
        ("missing category", without("category"), StatusCode::BAD_REQUEST),
        ("missing game", without("game"), StatusCode::BAD_REQUEST),
        ("unknown game", with("game", "999"), StatusCode::NOT_FOUND),
        ("game not a number", with("game", "x"), StatusCode::NOT_FOUND),
        ("unknown location", with("location", "999"), StatusCode::NOT_FOUND),
        ("quantity not a number (a 500 in Python)", with("quantity", "lots"), StatusCode::BAD_REQUEST),
        // Python evaluated the game before the location: a bad game wins.
        (
            "both bad",
            with("game", "999").into_iter().filter(|(k, _)| *k != "location").collect(),
            StatusCode::NOT_FOUND,
        ),
    ] {
        let response = admin.post_form("/test/miniatures/new", &pairs(&form)).await;
        assert_eq!(response.status, status, "{name}");
    }
    assert_eq!(fx.count(cfg).await, 1, "nothing was created");

    // Empty or absent quantity falls back to the default; Python's int() rules otherwise.
    for (quantity, expected) in [("", "1"), (" 007 ", "7"), ("-2", "-2")] {
        let response = admin.post_form("/test/miniatures/new", &pairs(&with("quantity", quantity))).await;
        let id: i64 = response.headers[header::LOCATION].to_str().unwrap().rsplit('/').next().unwrap().parse().unwrap();
        assert_eq!(fx.column(cfg, "quantity", id).await.as_deref(), Some(expected), "quantity {quantity:?}");
    }
}

#[tokio::test]
async fn per_type_field_rules() {
    let cfgs = configs();
    let by_kind = |kind| cfgs.iter().find(|c| c.kind == kind).unwrap();

    // A consumable defaults to 0, the others to 1.
    let consumable = by_kind(ItemKind::Consumable);
    let fx = Fixture::new(consumable).await;
    let mut form = full_form(consumable, &fx.seed);
    form.retain(|(k, _)| *k != "quantity");
    let response = fx.client(Some(fx.seed.admin)).post_form("/test/consumables/new", &pairs(&form)).await;
    let id: i64 = response.headers[header::LOCATION].to_str().unwrap().rsplit('/').next().unwrap().parse().unwrap();
    assert_eq!(fx.column(consumable, "quantity", id).await.as_deref(), Some("0"));
    // `request.form.get('unit', '')`: stored as an empty string, not NULL.
    assert_eq!(fx.column(consumable, "unit", id).await.as_deref(), Some(""));

    // Tablecloth: an empty material or remark is NULL; an unknown material is refused.
    let tablecloth = by_kind(ItemKind::Tablecloth);
    let fx = Fixture::new(tablecloth).await;
    let mut admin = fx.client(Some(fx.seed.admin));
    let mut form = full_form(tablecloth, &fx.seed);
    form.extend([("material", String::new()), ("remarks", String::new())]);
    let response = admin.post_form("/test/tablecloths/new", &pairs(&form)).await;
    let id: i64 = response.headers[header::LOCATION].to_str().unwrap().rsplit('/').next().unwrap().parse().unwrap();
    assert_eq!(fx.column(tablecloth, "material", id).await, None);
    assert_eq!(fx.column(tablecloth, "remarks", id).await, None);
    let mut bad = full_form(tablecloth, &fx.seed);
    bad.push(("material", "silk".into()));
    assert_eq!(admin.post_form("/test/tablecloths/new", &pairs(&bad)).await.status, StatusCode::BAD_REQUEST);
    let mut vinyl = full_form(tablecloth, &fx.seed);
    vinyl.push(("material", "vinyl".into()));
    let response = admin.post_form("/test/tablecloths/new", &pairs(&vinyl)).await;
    let shown = admin.follow(response).await;
    assert!(shown.body.contains("120x180 (48&#34;x72&#34;)"), "sizes_inches on the show page");

    // Rulebook: the supplement checkbox.
    let rulebook = by_kind(ItemKind::Rulebook);
    let fx = Fixture::new(rulebook).await;
    let mut form = full_form(rulebook, &fx.seed);
    form.push(("supplement", "on".into()));
    let response = fx.client(Some(fx.seed.admin)).post_form("/test/rulebooks/new", &pairs(&form)).await;
    let id: i64 = response.headers[header::LOCATION].to_str().unwrap().rsplit('/').next().unwrap().parse().unwrap();
    assert_eq!(fx.column(rulebook, "supplement", id).await.as_deref(), Some("1"));

    // Terrain: theater NULL (from the database) prints as "—" in the list.
    let terrain = by_kind(ItemKind::Terrain);
    let fx = Fixture::new(terrain).await;
    let list = fx.client(None).get("/test/terrains/").await;
    assert!(list.body.contains("<td>—</td>"));
}

#[tokio::test]
async fn output_is_escaped_like_jinja() {
    let cfg = &configs()[4]; // board game: a free-text name
    let fx = Fixture::new(cfg).await;
    let mut admin = fx.client(Some(fx.seed.admin));
    let mut form = full_form(cfg, &fx.seed);
    form.retain(|(k, _)| *k != "name");
    form.push(("name", "L'Ordre <du> \"Temple\"".into()));
    let response = admin.post_form("/test/board-games/new", &pairs(&form)).await;
    let shown = admin.follow(response).await;
    assert!(shown.body.contains("L&#39;Ordre &lt;du&gt; &#34;Temple&#34;"), "{}", shown.body);
}
