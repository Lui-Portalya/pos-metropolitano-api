import sqlite3

from app.db import transaction

DEFAULT_STORE_NAME = "POS Metropolitano"


def _num(v: float) -> int | float:
    return int(v) if float(v).is_integer() else v


def _num_to_text(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def get_settings(conn: sqlite3.Connection) -> dict:
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    try:
        tax = _num(float(rows.get("tax_rate_percent", "0")))
    except ValueError:
        tax = 0
    return {
        "store_name": rows.get("store_name") or DEFAULT_STORE_NAME,
        "tax_rate_percent": tax,
        "receipt_footer": rows.get("receipt_footer", ""),
    }


def update_settings(
    conn: sqlite3.Connection, *, store_name: str, tax_rate_percent: float, receipt_footer: str
) -> dict:
    values = {
        "store_name": store_name,
        "tax_rate_percent": _num_to_text(tax_rate_percent),
        "receipt_footer": receipt_footer,
    }
    with transaction(conn):
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
    return get_settings(conn)
