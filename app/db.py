import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import Settings

# Mirrors src/lib/db/schema.ts of the Node app (the two apps share one SQLite file).
# Every statement is idempotent. Keep this in sync with schema.ts.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','cashier','cook')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
  track_stock INTEGER NOT NULL DEFAULT 0,
  stock INTEGER NOT NULL DEFAULT 0,
  min_stock INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ingredients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  unit TEXT NOT NULL DEFAULT '',
  track_stock INTEGER NOT NULL DEFAULT 1,
  stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  min_stock INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  subtotal_cents INTEGER NOT NULL,
  tax_cents INTEGER NOT NULL,
  total_cents INTEGER NOT NULL,
  payment_method TEXT NOT NULL CHECK (payment_method IN ('cash','card','other')),
  amount_paid_cents INTEGER NOT NULL,
  change_cents INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','voided')),
  -- Kitchen hand-off: every sale starts 'pending' and the cooking team marks it 'delivered'.
  fulfillment TEXT NOT NULL DEFAULT 'pending' CHECK (fulfillment IN ('pending','delivered')),
  delivered_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_sales_created ON sales(created_at);

CREATE TABLE IF NOT EXISTS sale_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES items(id),
  name_snapshot TEXT NOT NULL,
  unit_price_cents INTEGER NOT NULL,
  qty INTEGER NOT NULL CHECK (qty > 0),
  line_total_cents INTEGER NOT NULL
);

-- Per unit sold, an item consumes qty of each ingredient in its recipe.
CREATE TABLE IF NOT EXISTS recipe_lines (
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
  qty INTEGER NOT NULL CHECK (qty > 0),
  PRIMARY KEY (item_id, ingredient_id)
);

-- Preparation stage: the cooking team records a batch of an item they made.
-- Ingredients are deducted here (per the recipe) and the item's stock goes up.
CREATE TABLE IF NOT EXISTS preparations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES items(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  qty INTEGER NOT NULL CHECK (qty > 0),
  status TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('done','undone')),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_preparations_created ON preparations(created_at);

-- What a preparation actually deducted from tracked ingredients (restored if undone).
CREATE TABLE IF NOT EXISTS preparation_ingredient_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  preparation_id INTEGER NOT NULL REFERENCES preparations(id) ON DELETE CASCADE,
  ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
  name_snapshot TEXT NOT NULL,
  qty INTEGER NOT NULL CHECK (qty > 0)
);
CREATE INDEX IF NOT EXISTS idx_prep_usage ON preparation_ingredient_usage(preparation_id);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES
  ('store_name', 'POS Metropolitano'),
  ('tax_rate_percent', '0'),
  ('receipt_footer', 'Thank you! God bless you.');
"""

# Columns added after the first release; `CREATE TABLE IF NOT EXISTS` doesn't alter
# existing tables, so each is added when missing. `backfill` runs once, right after.
COLUMN_MIGRATIONS: list[dict[str, str | None]] = [
    {"table": "items", "column": "min_stock", "ddl": "INTEGER NOT NULL DEFAULT 0", "backfill": None},
    {"table": "ingredients", "column": "min_stock", "ddl": "INTEGER NOT NULL DEFAULT 0", "backfill": None},
    # Sales that predate the kitchen screen were handed over long ago; keep the queue empty.
    {
        "table": "sales",
        "column": "fulfillment",
        "ddl": "TEXT NOT NULL DEFAULT 'pending' CHECK (fulfillment IN ('pending','delivered'))",
        "backfill": "UPDATE sales SET fulfillment = 'delivered'",
    },
    {"table": "sales", "column": "delivered_at", "ddl": "TEXT", "backfill": None},
]

# SQLite can't alter a CHECK constraint, so databases whose `users.role` predates the
# 'cook' role are rebuilt: create new table, copy rows, drop old, rename.
USERS_ROLE_MARKER = "'cook'"
USERS_ROLE_REBUILD: tuple[str, ...] = (
    """CREATE TABLE users_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','cashier','cook')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
)""",
    """INSERT INTO users_new (id, username, password_hash, name, role, active, created_at)
  SELECT id, username, password_hash, name, role, active, created_at FROM users""",
    "DROP TABLE users",
    "ALTER TABLE users_new RENAME TO users",
)


def connect(path: str) -> sqlite3.Connection:
    """Open a connection in autocommit mode; use `transaction()` for atomic writes."""
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def apply_column_migrations(conn: sqlite3.Connection) -> None:
    for m in COLUMN_MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({m['table']})")}
        if m["column"] in cols:
            continue
        with transaction(conn):
            conn.execute(f"ALTER TABLE {m['table']} ADD COLUMN {m['column']} {m['ddl']}")
            if m["backfill"]:
                conn.execute(m["backfill"])


def apply_users_role_rebuild(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if row is None or USERS_ROLE_MARKER in row["sql"]:
        return
    # Foreign keys must be off while the old table is dropped; the pragma is a no-op
    # inside a transaction, so toggle it around the rebuild.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with transaction(conn):
            for statement in USERS_ROLE_REBUILD:
                conn.execute(statement)
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("users rebuild left dangling foreign keys")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_db(settings: Settings) -> None:
    from app.security import hash_password  # local import: avoids a cycle at module load

    if settings.database_path != ":memory:":
        Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.database_path)
    try:
        conn.executescript(SCHEMA)
        apply_column_migrations(conn)
        apply_users_role_rebuild(conn)
        has_users = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        if not has_users:
            seeds = (
                (settings.seed_admin_username, settings.seed_admin_password, settings.seed_admin_name, "admin"),
                (settings.seed_cashier_username, settings.seed_cashier_password, settings.seed_cashier_name, "cashier"),
                (settings.seed_cook_username, settings.seed_cook_password, settings.seed_cook_name, "cook"),
            )
            for username, password, name, role in seeds:
                conn.execute(
                    "INSERT INTO users (username, password_hash, name, role) VALUES (?,?,?,?)",
                    (username, hash_password(password), name, role),
                )
    finally:
        conn.close()
