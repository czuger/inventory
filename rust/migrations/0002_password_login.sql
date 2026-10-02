-- Username/password login (MIGRATION_PLAN.md §5.9).
--
-- `users` gains `login` (the name typed on the login form, unique whatever the letter
-- case) and `password_hash` (argon2id, PHC string), and `discord_id` becomes optional: an
-- account made on the sign-up form has none. Every user keeps a way in (the CHECK).
--
-- SQLite cannot drop a NOT NULL constraint, so the table is rebuilt the way SQLite
-- documents (create, copy, drop, rename), with foreign keys off — `inventory migrate`
-- runs `PRAGMA foreign_key_check` before committing. Ids are copied as they are, so
-- `borrowings.borrower_id` stays valid, and the AUTOINCREMENT counter is carried over so
-- the id of a deleted user is still never handed out again.

CREATE TABLE users_new (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	discord_id TEXT,
	username TEXT NOT NULL,
	display_name TEXT,
	is_admin INTEGER NOT NULL,
	login TEXT COLLATE NOCASE,
	password_hash TEXT,
	CONSTRAINT uq_users_discord_id UNIQUE (discord_id),
	CONSTRAINT uq_users_login UNIQUE (login),
	CONSTRAINT ck_users_has_credentials CHECK (discord_id IS NOT NULL OR (login IS NOT NULL AND password_hash IS NOT NULL))
)
 STRICT;

INSERT INTO users_new (id, discord_id, username, display_name, is_admin)
    SELECT id, discord_id, username, display_name, is_admin FROM users ORDER BY id;

-- The copy set users_new's counter to the highest id copied (or none at all if there
-- was nothing to copy); keep the old one if it is higher.
INSERT INTO sqlite_sequence (name, seq)
    SELECT 'users_new', seq FROM sqlite_sequence
     WHERE name = 'users' AND NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'users_new');
UPDATE sqlite_sequence
   SET seq = MAX(seq, COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'users'), 0))
 WHERE name = 'users_new';

DROP TABLE users;

ALTER TABLE users_new RENAME TO users;
