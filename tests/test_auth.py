import re
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest

from app.security import hash_token
from app.services.sessions import iso_utc

from .conftest import PASSWORD

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- login -------------------------------------------------------------------


def test_login_success_shape_and_cookie(client, make_user):
    uid = make_user("ana", "cashier", name="Ana")
    res = client.post(LOGIN, json={"username": "ana", "password": PASSWORD})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"token", "expiresAt", "user", "home"}
    assert re.fullmatch(r"[0-9a-f]{64}", body["token"])
    assert body["user"] == {"id": uid, "username": "ana", "name": "Ana", "role": "cashier", "active": True}
    assert body["home"] == "/"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", body["expiresAt"])
    expires = datetime.fromisoformat(body["expiresAt"].replace("Z", "+00:00"))
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)

    cookie = res.headers["set-cookie"]
    assert f"pos_session={body['token']}" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie


def test_login_cookie_secure_flag(tmp_path, make_user):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    cfg = Settings(database_path=str(tmp_path / "s.db"), cookie_secure=True, _env_file=None)
    with TestClient(create_app(cfg)) as c:
        res = c.post(LOGIN, json={"username": "admin", "password": "admin123"})
        assert res.status_code == 200
        assert "Secure" in res.headers["set-cookie"]


def test_cook_lands_on_kitchen(client, make_user):
    make_user("cora", "cook")
    assert client.post(LOGIN, json={"username": "cora", "password": PASSWORD}).json()["home"] == "/kitchen"


def test_login_username_is_case_insensitive_and_trimmed(client, make_user):
    make_user("Ana", "cashier")
    res = client.post(LOGIN, json={"username": "  aNA ", "password": PASSWORD})
    assert res.status_code == 200
    assert res.json()["user"]["username"] == "Ana"


def test_login_wrong_password(client, make_user):
    make_user("ana")
    res = client.post(LOGIN, json={"username": "ana", "password": "nope"})
    assert res.status_code == 401
    assert res.json() == {"error": "Incorrect username or password."}
    assert "set-cookie" not in res.headers


def test_login_unknown_user_same_error(client):
    res = client.post(LOGIN, json={"username": "ghost", "password": "whatever"})
    assert res.status_code == 401
    assert res.json() == {"error": "Incorrect username or password."}


def test_login_deactivated_user(client, make_user):
    make_user("ana", active=False)
    res = client.post(LOGIN, json={"username": "ana", "password": PASSWORD})
    assert res.status_code == 401
    assert res.json() == {"error": "Incorrect username or password."}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"username": "ana"},
        {"password": "x"},
        {"username": "", "password": "x"},
        {"username": "   ", "password": "x"},
        {"username": "ana", "password": ""},
        {"username": 5, "password": "x"},
        {"username": None, "password": None},
    ],
)
def test_login_validation(client, payload):
    res = client.post(LOGIN, json=payload)
    assert res.status_code == 422
    assert res.json() == {"error": "Enter your username and password."}


def test_login_non_json_body(client):
    res = client.post(LOGIN, content="not json", headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    assert res.json() == {"error": "Enter your username and password."}


def test_seed_admin_can_log_in(client):
    res = client.post(LOGIN, json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "admin"


@pytest.mark.parametrize(
    ("username", "password", "role", "home"),
    [("cashier", "cashier123", "cashier", "/"), ("kitchen", "kitchen123", "cook", "/kitchen")],
)
def test_seed_cashier_and_kitchen_can_log_in(client, username, password, role, home):
    res = client.post(LOGIN, json={"username": username, "password": password})
    assert res.status_code == 200
    assert res.json()["user"]["role"] == role
    assert res.json()["home"] == home


def test_seed_skipped_when_users_exist(tmp_path, cfg):
    from app.db import connect, init_db

    init_db(cfg)
    conn = connect(cfg.database_path)
    conn.execute("DELETE FROM users WHERE username <> 'admin'")
    conn.close()
    init_db(cfg)
    conn = connect(cfg.database_path)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_login_accepts_bcryptjs_style_2a_hash(client, make_user):
    legacy = bcrypt.hashpw(b"legacy-pw", bcrypt.gensalt(10, prefix=b"2a")).decode()
    assert legacy.startswith("$2a$10$")
    make_user("old", password_hash=legacy)
    res = client.post(LOGIN, json={"username": "old", "password": "legacy-pw"})
    assert res.status_code == 200


def test_login_long_password_is_truncated_like_bcryptjs(client, make_user):
    long_pw = "x" * 100
    make_user("lng", password=long_pw)
    assert client.post(LOGIN, json={"username": "lng", "password": "x" * 72 + "different"}).status_code == 200


def test_login_stores_only_sha256_of_token(client, make_user, db):
    make_user("ana")
    token = client.post(LOGIN, json={"username": "ana", "password": PASSWORD}).json()["token"]
    rows = db.execute("SELECT token_hash, user_id FROM sessions").fetchall()
    assert [r["token_hash"] for r in rows] == [hash_token(token)]
    assert token not in rows[0]["token_hash"]


def test_login_purges_expired_sessions(client, make_user, db):
    uid = make_user("ana")
    past = iso_utc(datetime.now(UTC) - timedelta(minutes=1))
    future = iso_utc(datetime.now(UTC) + timedelta(days=1))
    db.execute("INSERT INTO sessions VALUES ('expired', ?, ?)", (uid, past))
    db.execute("INSERT INTO sessions VALUES ('alive', ?, ?)", (uid, future))
    client.post(LOGIN, json={"username": "ana", "password": PASSWORD})
    hashes = {r["token_hash"] for r in db.execute("SELECT token_hash FROM sessions")}
    assert "expired" not in hashes and "alive" in hashes and len(hashes) == 2


# ---- me ----------------------------------------------------------------------


def test_me_requires_auth(client):
    res = client.get(ME)
    assert res.status_code == 401
    assert res.json() == {"error": "Unauthorized"}


def test_me_with_bearer_token(client, make_user, login):
    make_user("ana", "cashier", name="Ana")
    token = login("ana")["token"]
    res = client.get(ME, headers=bearer(token))
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["username"] == "ana"
    assert body["storeName"] == "POS Metropolitano"
    assert body["home"] == "/"


def test_me_with_cookie(client, make_user):
    make_user("ana")
    client.post(LOGIN, json={"username": "ana", "password": PASSWORD})  # cookie jar keeps pos_session
    assert client.get(ME).status_code == 200


def test_bearer_takes_precedence_over_cookie(client, make_user):
    make_user("ana", "cashier")
    make_user("bob", "cook")
    client.post(LOGIN, json={"username": "ana", "password": PASSWORD})  # cookie = ana
    bob = client.post(LOGIN, json={"username": "bob", "password": PASSWORD}).json()["token"]
    client.cookies.clear()
    client.post(LOGIN, json={"username": "ana", "password": PASSWORD})  # cookie = ana again
    assert client.get(ME, headers=bearer(bob)).json()["user"]["username"] == "bob"


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Basic abc", "Bearer not-a-real-token", "token"])
def test_me_rejects_bad_authorization_headers(client, header):
    assert client.get(ME, headers={"Authorization": header}).status_code == 401


def test_me_rejects_expired_session(client, make_user, login, db):
    make_user("ana")
    token = login("ana")["token"]
    db.execute("UPDATE sessions SET expires_at = ?", (iso_utc(datetime.now(UTC) - timedelta(seconds=1)),))
    assert client.get(ME, headers=bearer(token)).status_code == 401


def test_me_rejects_deactivated_user_with_live_session(client, make_user, login, db):
    uid = make_user("ana")
    token = login("ana")["token"]
    db.execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))
    assert client.get(ME, headers=bearer(token)).status_code == 401


@pytest.mark.parametrize(
    ("role", "modules"),
    [
        ("admin", ["sell", "kitchen", "prepare", "sales", "summary", "menu", "restock", "admin"]),
        ("cashier", ["sell", "kitchen", "prepare", "sales", "summary"]),
        ("cook", ["kitchen", "prepare"]),
    ],
)
def test_me_allowed_modules_and_home(client, headers, role, modules):
    body = client.get(ME, headers=headers(role)).json()
    assert body["allowedModules"] == modules
    assert body["home"] == ("/kitchen" if role == "cook" else "/")


def test_me_reflects_store_name_setting(client, headers, db):
    h = headers("cashier")
    db.execute("UPDATE settings SET value = 'Cafe Uno' WHERE key = 'store_name'")
    assert client.get(ME, headers=h).json()["storeName"] == "Cafe Uno"


# ---- logout ------------------------------------------------------------------


def test_logout_requires_auth(client):
    assert client.post(LOGOUT).status_code == 401


def test_logout_bearer_invalidates_only_that_session(client, make_user, login, db):
    make_user("ana")
    t1 = login("ana")["token"]
    t2 = login("ana")["token"]
    res = client.post(LOGOUT, headers=bearer(t1))
    assert res.status_code == 204 and res.content == b""
    assert client.get(ME, headers=bearer(t1)).status_code == 401
    assert client.get(ME, headers=bearer(t2)).status_code == 200
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_logout_clears_cookie(client, make_user):
    make_user("ana")
    client.post(LOGIN, json={"username": "ana", "password": PASSWORD})
    res = client.post(LOGOUT)
    assert res.status_code == 204
    set_cookie = res.headers["set-cookie"]
    assert "pos_session=" in set_cookie and ("Max-Age=0" in set_cookie or "1970" in set_cookie)
    assert client.get(ME).status_code == 401


def test_logout_twice_second_is_401(client, make_user, login):
    make_user("ana")
    token = login("ana")["token"]
    assert client.post(LOGOUT, headers=bearer(token)).status_code == 204
    assert client.post(LOGOUT, headers=bearer(token)).status_code == 401


# ---- misc --------------------------------------------------------------------


def test_unknown_route_uses_error_envelope(client):
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    assert "error" in res.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
