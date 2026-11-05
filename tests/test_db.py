import sqlite3

from app.config import Settings
from app.db import connect, init_db
from app.seed import ensure_admin, seed_sample_data

TABLES = {
    "users", "sessions", "categories", "items", "ingredients", "sales", "sale_items",
    "recipe_lines", "preparations", "preparation_ingredient_usage", "settings",
}

LEGACY_SCHEMA = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','cashier')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);
CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id), price_cents INTEGER NOT NULL,
  track_stock INTEGER NOT NULL DEFAULT 0, stock INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  unit TEXT NOT NULL DEFAULT '', track_stock INTEGER NOT NULL DEFAULT 1, stock INTEGER NOT NULL DEFAULT 0);
CREATE TABLE sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
  subtotal_cents INTEGER NOT NULL, tax_cents INTEGER NOT NULL, total_cents INTEGER NOT NULL,
  payment_method TEXT NOT NULL, amount_paid_cents INTEGER NOT NULL, change_cents INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
INSERT INTO users (username, password_hash, name, role) VALUES ('old_admin', 'h', 'Old Admin', 'admin');
INSERT INTO sessions VALUES ('tok', 1, '2999-01-01T00:00:00.000Z');
INSERT INTO sales (user_id, subtotal_cents, tax_cents, total_cents, payment_method, amount_paid_cents, change_cents)
  VALUES (1, 100, 0, 100, 'cash', 100, 0);
"""


def cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_init_creates_every_table(cfg):
    init_db(cfg)
    conn = connect(cfg.database_path)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_init_is_idempotent_and_seeds_users_once(cfg):
    init_db(cfg)
    init_db(cfg)
    conn = connect(cfg.database_path)
    rows = conn.execute("SELECT username, name, role FROM users ORDER BY id").fetchall()
    assert [(r["username"], r["name"], r["role"]) for r in rows] == [
        ("admin", "Administrator", "admin"), ("cashier", "Cashier", "cashier"), ("kitchen", "Kitchen", "cook"),
    ]
    assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 3


def test_legacy_database_is_migrated_without_losing_data(cfg):
    raw = sqlite3.connect(cfg.database_path)
    raw.executescript(LEGACY_SCHEMA)
    raw.commit()
    raw.close()

    init_db(cfg)
    conn = connect(cfg.database_path)

    assert {"min_stock"} <= cols(conn, "items") and "min_stock" in cols(conn, "ingredients")
    assert {"fulfillment", "delivered_at"} <= cols(conn, "sales")
    # old sales are backfilled as delivered so the kitchen queue starts empty
    assert conn.execute("SELECT fulfillment FROM sales").fetchone()[0] == "delivered"
    # users table rebuilt: data + sessions kept, 'cook' now allowed, FKs intact
    assert conn.execute("SELECT username, name FROM users").fetchall()[0]["username"] == "old_admin"
    assert conn.execute("SELECT user_id FROM sessions WHERE token_hash='tok'").fetchone()[0] == 1
    conn.execute("INSERT INTO users (username, password_hash, name, role) VALUES ('c','h','C','cook')")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    # existing users -> no extra seed users on a populated DB
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    # legacy rows are not re-backfilled on a second start; new sales default to pending
    conn.execute(
        "INSERT INTO sales (user_id, subtotal_cents, tax_cents, total_cents, payment_method,"
        " amount_paid_cents, change_cents) VALUES (1,1,0,1,'cash',1,0)"
    )
    init_db(cfg)
    assert [r[0] for r in conn.execute("SELECT fulfillment FROM sales ORDER BY id")] == ["delivered", "pending"]


def test_pos_db_path_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("POS_DB_PATH", str(tmp_path / "x.db"))
    assert Settings(_env_file=None).database_path == str(tmp_path / "x.db")


def test_database_path_env_alias(monkeypatch, tmp_path):
    monkeypatch.delenv("POS_DB_PATH", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "y.db"))
    assert Settings(_env_file=None).database_path == str(tmp_path / "y.db")


# ---- sample-data seed --------------------------------------------------------


def test_seed_sample_data(cfg):
    init_db(cfg)
    conn = connect(cfg.database_path)
    messages = seed_sample_data(conn)
    assert messages == ["Seeded sample menu", "Seeded sample ingredients", "Seeded sample recipe: Ham Sandwich"]
    assert [r["name"] for r in conn.execute("SELECT name FROM categories ORDER BY sort_order")] == [
        "Drinks", "Food", "Pastries"]
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 10
    sandwich = conn.execute(
        "SELECT i.price_cents, i.track_stock, i.stock, i.min_stock, c.name AS cat FROM items i "
        "JOIN categories c ON c.id = i.category_id WHERE i.name='Ham Sandwich'").fetchone()
    assert tuple(sandwich) == (450, 1, 0, 10, "Food")
    recipe = conn.execute(
        "SELECT g.name, r.qty FROM recipe_lines r JOIN ingredients g ON g.id = r.ingredient_id "
        "ORDER BY g.name").fetchall()
    assert [(r["name"], r["qty"]) for r in recipe] == [("Bread", 2), ("Cheese", 1), ("Ham", 1)]


def test_seed_sample_data_is_idempotent(cfg):
    init_db(cfg)
    conn = connect(cfg.database_path)
    seed_sample_data(conn)
    assert seed_sample_data(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 10
    assert conn.execute("SELECT COUNT(*) FROM recipe_lines").fetchone()[0] == 3


def test_ensure_admin_only_when_missing(cfg):
    init_db(cfg)
    conn = connect(cfg.database_path)
    assert ensure_admin(conn, cfg) == []
    conn.execute("DELETE FROM users WHERE role='admin'")
    assert len(ensure_admin(conn, cfg)) == 1
    assert conn.execute("SELECT name FROM users WHERE role='admin'").fetchone()[0] == "Administrator"
