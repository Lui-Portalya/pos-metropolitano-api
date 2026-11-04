import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.main import create_app
from app.security import hash_password

PASSWORD = "secret1"


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return Settings(database_path=str(tmp_path / "pos.db"), _env_file=None)


@pytest.fixture
def client(cfg) -> TestClient:
    with TestClient(create_app(cfg)) as c:
        yield c


@pytest.fixture
def db(cfg, client) -> sqlite3.Connection:
    """Direct DB handle for arranging / inspecting state (app already initialised)."""
    conn = connect(cfg.database_path)
    yield conn
    conn.close()


@pytest.fixture
def make_user(db):
    def _make(username: str, role: str = "cashier", *, password: str = PASSWORD, active: bool = True,
              name: str | None = None, password_hash: str | None = None) -> int:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, name, role, active) VALUES (?,?,?,?,?)",
            (username, password_hash or hash_password(password), name or username.title(), role, int(active)),
        )
        return cur.lastrowid

    return _make


@pytest.fixture
def login(client):
    """Log in and return the response JSON. Cookies are cleared so tests choose Bearer vs cookie."""

    def _login(username: str, password: str = PASSWORD) -> dict:
        res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert res.status_code == 200, res.text
        client.cookies.clear()
        return res.json()

    return _login


@pytest.fixture
def headers(make_user, login):
    """Bearer headers for a freshly created user of the given role."""

    def _headers(role: str, username: str | None = None) -> dict:
        username = username or f"{role}_user"
        make_user(username, role)
        return {"Authorization": f"Bearer {login(username)['token']}"}

    return _headers


@pytest.fixture
def admin_h(headers):
    return headers("admin", "boss")
