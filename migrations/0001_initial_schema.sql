-- The schema Alembic's initial migration (7b1fd3535193) created, copied verbatim from
-- sqlite_master of a database built by `alembic upgrade head`, so that sqlite_master of a
-- database built here is identical (tests/schema.rs checks it). A database Alembic
-- already built is not re-created: `inventory migrate` records this migration as
-- applied instead (see src/migrate.rs).

CREATE TABLE associations (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	name TEXT NOT NULL, 
	slug TEXT NOT NULL, 
	CONSTRAINT uq_associations_name UNIQUE (name), 
	CONSTRAINT uq_associations_slug UNIQUE (slug)
)
 STRICT

;

CREATE TABLE games (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	name TEXT NOT NULL, 
	CONSTRAINT uq_games_name UNIQUE (name)
)
 STRICT

;

CREATE TABLE legacy_object_ids (
	object_id TEXT NOT NULL, 
	item_type TEXT NOT NULL, 
	item_id INTEGER NOT NULL, 
	CONSTRAINT pk_legacy_object_ids PRIMARY KEY (object_id)
)
 STRICT

;

CREATE TABLE users (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	discord_id TEXT NOT NULL, 
	username TEXT NOT NULL, 
	display_name TEXT, 
	is_admin INTEGER NOT NULL, 
	CONSTRAINT uq_users_discord_id UNIQUE (discord_id)
)
 STRICT

;

CREATE TABLE borrowings (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	borrower_id INTEGER NOT NULL, 
	item_id INTEGER NOT NULL, 
	item_type TEXT NOT NULL, 
	action TEXT NOT NULL, 
	date TEXT NOT NULL, 
	CONSTRAINT ck_borrowings_action_choices CHECK (action IN ('borrow', 'return')), 
	CONSTRAINT fk_borrowings_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_borrowings_borrower_id_users FOREIGN KEY(borrower_id) REFERENCES users (id)
)
 STRICT

;

CREATE INDEX ix_borrowings_item ON borrowings (item_type, item_id, date);

CREATE TABLE duplicate_links (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	item1_id INTEGER NOT NULL, 
	item1_type TEXT NOT NULL, 
	item2_id INTEGER NOT NULL, 
	item2_type TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	CONSTRAINT fk_duplicate_links_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id)
)
 STRICT

;

CREATE INDEX ix_duplicate_links_association_id ON duplicate_links (association_id);

CREATE TABLE locations (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	room TEXT NOT NULL, 
	spot TEXT NOT NULL, 
	CONSTRAINT fk_locations_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT uq_locations_association_id_room_spot UNIQUE (association_id, room, spot)
)
 STRICT

;

CREATE TABLE board_games (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	name TEXT NOT NULL, 
	universe TEXT, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_board_games_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT fk_board_games_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_board_games_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_board_games_association_id ON board_games (association_id);

CREATE TABLE books (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	name TEXT NOT NULL, 
	universe TEXT, 
	period TEXT, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_books_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT fk_books_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_books_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_books_association_id ON books (association_id);

CREATE TABLE consumables (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	type TEXT NOT NULL, 
	unit TEXT, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_consumables_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT fk_consumables_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_consumables_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_consumables_association_id ON consumables (association_id);

CREATE TABLE equipment (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	type TEXT NOT NULL, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_equipment_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT fk_equipment_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_equipment_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_equipment_association_id ON equipment (association_id);

CREATE TABLE miniatures (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	type TEXT NOT NULL, 
	game_id INTEGER NOT NULL, 
	scale TEXT NOT NULL, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_miniatures_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT fk_miniatures_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_miniatures_game_id_games FOREIGN KEY(game_id) REFERENCES games (id), 
	CONSTRAINT fk_miniatures_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_miniatures_association_id ON miniatures (association_id);

CREATE TABLE rulebooks (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	name TEXT NOT NULL, 
	game_id INTEGER NOT NULL, 
	supplement INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_rulebooks_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT fk_rulebooks_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_rulebooks_game_id_games FOREIGN KEY(game_id) REFERENCES games (id), 
	CONSTRAINT fk_rulebooks_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_rulebooks_association_id ON rulebooks (association_id);

CREATE TABLE tablecloths (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	type TEXT NOT NULL, 
	material TEXT, 
	game_id INTEGER NOT NULL, 
	size TEXT NOT NULL, 
	remarks TEXT, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_tablecloths_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT ck_tablecloths_material_choices CHECK (material IN ('mousepad (neoprene)', 'vinyl', 'cloth', 'textured')), 
	CONSTRAINT fk_tablecloths_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_tablecloths_game_id_games FOREIGN KEY(game_id) REFERENCES games (id), 
	CONSTRAINT fk_tablecloths_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_tablecloths_association_id ON tablecloths (association_id);

CREATE TABLE terrains (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	association_id INTEGER NOT NULL, 
	category TEXT NOT NULL, 
	type TEXT NOT NULL, 
	game_id INTEGER NOT NULL, 
	scale TEXT NOT NULL, 
	theater TEXT, 
	quantity INTEGER NOT NULL, 
	borrowing_count INTEGER NOT NULL, 
	sticker_printed INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	images TEXT NOT NULL, 
	CONSTRAINT ck_terrains_images_is_array CHECK (json_type(images) = 'array'), 
	CONSTRAINT fk_terrains_association_id_associations FOREIGN KEY(association_id) REFERENCES associations (id), 
	CONSTRAINT fk_terrains_game_id_games FOREIGN KEY(game_id) REFERENCES games (id), 
	CONSTRAINT fk_terrains_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)
)
 STRICT

;

CREATE INDEX ix_terrains_association_id ON terrains (association_id);

