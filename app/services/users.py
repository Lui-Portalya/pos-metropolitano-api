import sqlite3

from app.db import transaction
from app.errors import ApiError
from app.security import DUMMY_HASH, hash_password, verify_password

USER_COLUMNS = "id, username, name, role, active"


def to_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row["name"],
        "role": row["role"],
        "active": bool(row["active"]),
    }


def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {USER_COLUMNS} FROM users ORDER BY username").fetchall()
    return [to_user(r) for r in rows]


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone()
    return to_user(row) if row else None


def create_user(conn: sqlite3.Connection, *, username: str, name: str, password: str, role: str) -> dict:
    password_hash = hash_password(password)  # slow on purpose; keep it outside the write lock
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, name, role) VALUES (?,?,?,?)",
                (username, password_hash, name, role),
            )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc).upper():
            raise ApiError(409, "That username is taken.") from exc
        raise
    return get_user(conn, cur.lastrowid)  # type: ignore[return-value]


def set_user_active(conn: sqlite3.Connection, actor_id: int, user_id: int, active: bool) -> dict:
    if actor_id == user_id:
        raise ApiError(403, "You cannot change your own active status")
    with transaction(conn):
        target = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise ApiError(404, "User not found")
        if not active and target["role"] == "admin":
            other_admins = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND active = 1 AND id <> ?",
                (user_id,),
            ).fetchone()["c"]
            if other_admins == 0:
                raise ApiError(409, "Cannot deactivate the last admin")
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user_id))
        if not active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return get_user(conn, user_id)  # type: ignore[return-value]


def reset_password(conn: sqlite3.Connection, user_id: int, password: str) -> None:
    password_hash = hash_password(password)
    with transaction(conn):
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        if cur.rowcount == 0:
            raise ApiError(404, "User not found")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def verify_credentials(conn: sqlite3.Connection, username: str, password: str) -> dict | None:
    """The user if the credentials are valid and the account is active, else None."""
    row = conn.execute(
        "SELECT id, username, name, role, active, password_hash FROM users "
        "WHERE username = ? COLLATE NOCASE",
        (username,),
    ).fetchone()
    # Always run one bcrypt comparison so unknown users cost the same as wrong passwords.
    ok = verify_password(password, row["password_hash"] if row else DUMMY_HASH)
    if row is None or not ok or not row["active"]:
        return None
    return to_user(row)
