import sqlite3
from datetime import UTC, datetime, timedelta

from app.config import SESSION_DAYS
from app.db import transaction
from app.security import hash_token, new_token


def iso_utc(dt: datetime) -> str:
    """`2026-11-04T12:00:00.000Z` — same format JS `toISOString()` writes.

    `sessions.expires_at` is compared as text, so the format must match the
    rows written by the Node app.
    """
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def create_session(conn: sqlite3.Connection, user_id: int) -> tuple[str, datetime]:
    """Purge expired sessions, then insert a new one. Returns (raw token, expiry)."""
    token = new_token()
    now = datetime.now(UTC)
    expires = now + timedelta(days=SESSION_DAYS)
    with transaction(conn):
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (iso_utc(now),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
            (hash_token(token), user_id, iso_utc(expires)),
        )
    return token, expires


def get_user_for_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    """The active user owning a non-expired session for this raw token."""
    return conn.execute(
        """SELECT u.id, u.username, u.name, u.role, u.active FROM sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
        (hash_token(token), iso_utc(datetime.now(UTC))),
    ).fetchone()


def destroy_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
