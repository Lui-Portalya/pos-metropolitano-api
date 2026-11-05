"""Sample menu / ingredients / recipe, ported from the Node app's src/lib/db/seed.ts.

Run with:  python -m app.seed
Safe to re-run: each block only runs while its table is empty. The admin is created
only if no admin exists (users are normally seeded by `init_db` on first start).
"""

import sqlite3

from app.config import Settings
from app.db import connect, init_db, transaction
from app.security import hash_password

# (name, category, price_cents, track_stock, stock, min_stock)
MENU = [
    ("Coffee", "Drinks", 150, 0, 0, 0),
    ("Tea", "Drinks", 125, 0, 0, 0),
    ("Hot Chocolate", "Drinks", 200, 0, 0, 0),
    ("Bottled Water", "Drinks", 100, 1, 48, 24),
    ("Soda", "Drinks", 150, 1, 36, 24),
    ("Ham Sandwich", "Food", 450, 1, 0, 10),  # prepared by the kitchen (recipe below)
    ("Empanada", "Food", 300, 1, 30, 12),
    ("Croissant", "Pastries", 250, 1, 18, 6),
    ("Muffin", "Pastries", 225, 1, 18, 6),
    ("Brownie", "Pastries", 200, 1, 24, 6),
]
CATEGORIES = ["Drinks", "Food", "Pastries"]  # sort_order 1..3
# (name, unit, track_stock, stock, min_stock)
INGREDIENTS = [
    ("Coffee beans", "kg", 1, 5, 2),
    ("Milk", "L", 1, 12, 6),
    ("Sugar", "kg", 0, 0, 0),
    ("Bread", "slices", 1, 40, 20),
    ("Cheese", "slices", 1, 20, 10),
    ("Ham", "slices", 1, 20, 10),
]
HAM_SANDWICH_RECIPE = {"Bread": 2, "Cheese": 1, "Ham": 1}


def seed_sample_data(conn: sqlite3.Connection) -> list[str]:
    done: list[str] = []
    with transaction(conn):
        if not conn.execute("SELECT 1 FROM items").fetchone():
            cat_ids = {}
            for order, name in enumerate(CATEGORIES, start=1):
                cur = conn.execute("INSERT INTO categories (name, sort_order) VALUES (?,?)", (name, order))
                cat_ids[name] = cur.lastrowid
            for name, cat, price, track, stock, min_stock in MENU:
                conn.execute(
                    "INSERT INTO items (name, category_id, price_cents, track_stock, stock, min_stock) "
                    "VALUES (?,?,?,?,?,?)",
                    (name, cat_ids[cat], price, track, stock, min_stock),
                )
            done.append("Seeded sample menu")

        if not conn.execute("SELECT 1 FROM ingredients").fetchone():
            ing_ids = {}
            for name, unit, track, stock, min_stock in INGREDIENTS:
                cur = conn.execute(
                    "INSERT INTO ingredients (name, unit, track_stock, stock, min_stock) VALUES (?,?,?,?,?)",
                    (name, unit, track, stock, min_stock),
                )
                ing_ids[name] = cur.lastrowid
            done.append("Seeded sample ingredients")
            sandwich = conn.execute("SELECT id FROM items WHERE name = 'Ham Sandwich'").fetchone()
            if sandwich:
                for name, qty in HAM_SANDWICH_RECIPE.items():
                    conn.execute(
                        "INSERT INTO recipe_lines (item_id, ingredient_id, qty) VALUES (?,?,?)",
                        (sandwich["id"], ing_ids[name], qty),
                    )
                done.append("Seeded sample recipe: Ham Sandwich")
    return done


def ensure_admin(conn: sqlite3.Connection, settings: Settings) -> list[str]:
    if conn.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone():
        return []
    conn.execute(
        "INSERT INTO users (username, password_hash, name, role) VALUES (?,?,?,'admin')",
        (settings.seed_admin_username, hash_password(settings.seed_admin_password), settings.seed_admin_name),
    )
    return [f"Created admin user: {settings.seed_admin_username} (change this password after first login)"]


def main() -> None:
    settings = Settings()
    init_db(settings)
    conn = connect(settings.database_path)
    try:
        for line in ensure_admin(conn, settings) + seed_sample_data(conn):
            print(line)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
