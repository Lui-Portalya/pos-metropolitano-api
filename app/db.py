import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import Settings

# Subset of the shared schema (see API_ENDPOINTS.md §4) needed by auth, settings
# and users. Later modules add their own tables; all statements are idempotent
# so the same file can be opened by this API and the Node app.
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

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES
  ('store_name', 'POS Metropolitano'),
  ('tax_rate_percent', '0'),
  ('receipt_footer', 'Thank you! God bless you.');
"""


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


def init_db(settings: Settings) -> None:
    from app.security import hash_password  # local import: avoids a cycle at module load

    if settings.database_path != ":memory:":
        Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.database_path)
    try:
        conn.executescript(SCHEMA)
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
