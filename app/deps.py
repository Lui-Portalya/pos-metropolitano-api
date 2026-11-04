import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.config import SESSION_COOKIE, Settings
from app.db import connect
from app.errors import forbidden, unauthorized
from app.services import sessions
from app.services.users import to_user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass
class Principal:
    user: dict
    token: str


def _extract_token(request: Request) -> str | None:
    """`Authorization: Bearer <token>` (mobile) wins over the `pos_session` cookie (web)."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.cookies.get(SESSION_COOKIE)


def current_principal(request: Request, db: Db) -> Principal:
    token = _extract_token(request)
    if not token:
        raise unauthorized()
    row = sessions.get_user_for_token(db, token)
    if row is None:
        raise unauthorized()
    return Principal(user=to_user(row), token=token)


def require_admin(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if principal.user["role"] != "admin":
        raise forbidden()
    return principal


# Guard aliases, named like the spec (`any`, `cashier+`, `admin`).
AnyUser = Annotated[Principal, Depends(current_principal)]
AdminUser = Annotated[Principal, Depends(require_admin)]
