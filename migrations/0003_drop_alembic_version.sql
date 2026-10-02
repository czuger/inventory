-- The Python app is gone, and with it Alembic: its bookkeeping table has no reader left.
-- `inventory migrate` still recognizes a database Alembic built and never upgraded since
-- (it baselines it as migration 0001 first), so this only drops what that left behind.
DROP TABLE IF EXISTS alembic_version;
