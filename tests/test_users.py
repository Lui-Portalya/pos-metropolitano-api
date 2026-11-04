import pytest

from app.errors import ApiError
from app.services import users as users_service

from .conftest import PASSWORD

URL = "/api/v1/users"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
NEW = {"username": "maria", "name": "Maria", "password": "abcdef", "role": "cashier"}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- guards ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", URL, None),
        ("post", URL, NEW),
        ("patch", f"{URL}/1/active", {"active": False}),
        ("put", f"{URL}/1/password", {"password": "abcdef"}),
    ],
)
def test_requires_auth_and_admin(client, headers, method, path, body):
    assert client.request(method.upper(), path, json=body).status_code == 401
    for role in ("cashier", "cook"):
        res = client.request(method.upper(), path, json=body, headers=headers(role))
        assert res.status_code == 403, role
        assert res.json() == {"error": "Forbidden"}


# ---- list --------------------------------------------------------------------


def test_list_users_ordered_by_username_without_secrets(client, admin_h, make_user):
    make_user("zed", "cook", active=False)
    make_user("Alice", "cashier")
    res = client.get(URL, headers=admin_h)
    assert res.status_code == 200
    users = res.json()["users"]
    assert [u["username"] for u in users] == ["admin", "Alice", "boss", "cashier", "kitchen", "zed"]  # case-insensitive order
    assert users[-1]["active"] is False
    assert all(set(u) == {"id", "username", "name", "role", "active"} for u in users)
    assert "password" not in res.text.lower()


# ---- create ------------------------------------------------------------------


def test_create_user_201_and_can_log_in(client, admin_h, db):
    res = client.post(URL, json=NEW, headers=admin_h)
    assert res.status_code == 201
    user = res.json()["user"]
    assert user["username"] == "maria" and user["role"] == "cashier" and user["active"] is True
    assert client.post(LOGIN, json={"username": "maria", "password": "abcdef"}).status_code == 200
    stored = db.execute("SELECT password_hash FROM users WHERE username='maria'").fetchone()[0]
    assert stored.startswith("$2b$10$")  # bcrypt cost 10, bcryptjs-compatible


def test_create_user_trims_username_and_name(client, admin_h):
    res = client.post(URL, json={**NEW, "username": "  maria ", "name": "  Maria L  "}, headers=admin_h)
    assert res.json()["user"]["username"] == "maria"
    assert res.json()["user"]["name"] == "Maria L"


def test_create_user_duplicate_username_is_409_case_insensitive(client, admin_h):
    assert client.post(URL, json=NEW, headers=admin_h).status_code == 201
    res = client.post(URL, json={**NEW, "username": "MARIA"}, headers=admin_h)
    assert res.status_code == 409
    assert res.json() == {"error": "That username is taken."}


def test_create_user_conflicts_with_seed_admin(client, admin_h):
    assert client.post(URL, json={**NEW, "username": "Admin"}, headers=admin_h).status_code == 409


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"password": "12345"}, "Password must be at least 6 characters"),
        ({"password": ""}, "Password must be at least 6 characters"),
        ({"username": "ab"}, "Username must be 3-32 characters"),
        ({"username": "  ab  "}, "Username must be 3-32 characters"),
        ({"username": "x" * 33}, "Username must be 3-32 characters"),
        ({"name": ""}, "Name must be 1-60 characters"),
        ({"name": "   "}, "Name must be 1-60 characters"),
        ({"name": "n" * 61}, "Name must be 1-60 characters"),
        ({"role": "owner"}, "Invalid value for role."),
        ({"role": None}, "Invalid value for role."),
    ],
)
def test_create_user_validation_messages(client, admin_h, patch, message):
    res = client.post(URL, json={**NEW, **patch}, headers=admin_h)
    assert res.status_code == 422
    assert res.json() == {"error": message}


def test_create_user_missing_field(client, admin_h):
    body = {k: v for k, v in NEW.items() if k != "role"}
    res = client.post(URL, json=body, headers=admin_h)
    assert res.status_code == 422
    assert res.json() == {"error": "role is required."}


@pytest.mark.parametrize("role", ["admin", "cashier", "cook"])
def test_create_user_all_roles(client, admin_h, role):
    assert client.post(URL, json={**NEW, "role": role}, headers=admin_h).json()["user"]["role"] == role


def test_create_user_boundary_lengths(client, admin_h):
    assert client.post(URL, json={**NEW, "username": "abc", "password": "123456"}, headers=admin_h).status_code == 201
    assert client.post(URL, json={**NEW, "username": "u" * 32, "name": "n" * 60}, headers=admin_h).status_code == 201


# ---- active ------------------------------------------------------------------


def test_deactivate_user_kills_sessions_and_blocks_login(client, admin_h, make_user, login, db):
    uid = make_user("ana")
    token = login("ana")["token"]
    assert client.get(ME, headers=bearer(token)).status_code == 200

    res = client.patch(f"{URL}/{uid}/active", json={"active": False}, headers=admin_h)
    assert res.status_code == 200
    assert res.json()["user"]["active"] is False
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (uid,)).fetchone()[0] == 0
    assert client.get(ME, headers=bearer(token)).status_code == 401
    assert client.post(LOGIN, json={"username": "ana", "password": PASSWORD}).status_code == 401


def test_reactivate_user(client, admin_h, make_user):
    uid = make_user("ana", active=False)
    res = client.patch(f"{URL}/{uid}/active", json={"active": True}, headers=admin_h)
    assert res.json()["user"]["active"] is True
    assert client.post(LOGIN, json={"username": "ana", "password": PASSWORD}).status_code == 200


def test_cannot_change_own_active_flag(client, make_user, login, db):
    uid = make_user("root", "admin")
    h = bearer(login("root")["token"])
    for flag in (False, True):
        res = client.patch(f"{URL}/{uid}/active", json={"active": flag}, headers=h)
        assert res.status_code == 403
    assert db.execute("SELECT active FROM users WHERE id=?", (uid,)).fetchone()[0] == 1


def test_deactivating_another_admin_is_allowed_when_not_the_last(client, admin_h, make_user):
    other = make_user("admin2", "admin")
    res = client.patch(f"{URL}/{other}/active", json={"active": False}, headers=admin_h)
    assert res.status_code == 200


def test_cannot_deactivate_last_active_admin(db, make_user):
    # Not reachable over HTTP while the caller is themselves an active admin, but the
    # guard must hold for concurrent / service-level callers.
    cook = make_user("cora", "cook")
    only_admin = db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    with pytest.raises(ApiError) as exc:
        users_service.set_user_active(db, cook, only_admin, False)
    assert exc.value.status_code == 409
    assert exc.value.message == "Cannot deactivate the last admin"
    assert db.execute("SELECT active FROM users WHERE id=?", (only_admin,)).fetchone()[0] == 1


def test_set_active_unknown_user_404(client, admin_h):
    res = client.patch(f"{URL}/9999/active", json={"active": False}, headers=admin_h)
    assert res.status_code == 404
    assert res.json() == {"error": "User not found"}


@pytest.mark.parametrize("body", [{}, {"active": "yes"}, {"active": 1}, {"active": None}])
def test_set_active_validation(client, admin_h, make_user, body):
    uid = make_user("ana")
    assert client.patch(f"{URL}/{uid}/active", json=body, headers=admin_h).status_code == 422


def test_non_integer_user_id_is_422(client, admin_h):
    assert client.patch(f"{URL}/abc/active", json={"active": True}, headers=admin_h).status_code == 422


# ---- password ----------------------------------------------------------------


def test_reset_password_changes_credentials_and_revokes_sessions(client, admin_h, make_user, login, db):
    uid = make_user("ana")
    token = login("ana")["token"]
    res = client.put(f"{URL}/{uid}/password", json={"password": "brandnew"}, headers=admin_h)
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert client.get(ME, headers=bearer(token)).status_code == 401
    assert client.post(LOGIN, json={"username": "ana", "password": PASSWORD}).status_code == 401
    assert client.post(LOGIN, json={"username": "ana", "password": "brandnew"}).status_code == 200


def test_reset_password_leaves_other_users_sessions(client, admin_h, make_user, login):
    uid = make_user("ana")
    make_user("bob")
    bob = login("bob")["token"]
    client.put(f"{URL}/{uid}/password", json={"password": "brandnew"}, headers=admin_h)
    assert client.get(ME, headers=bearer(bob)).status_code == 200
    assert client.get(ME, headers=admin_h).status_code == 200


def test_reset_password_unknown_user_404(client, admin_h):
    res = client.put(f"{URL}/9999/password", json={"password": "brandnew"}, headers=admin_h)
    assert res.status_code == 404
    assert res.json() == {"error": "User not found"}


@pytest.mark.parametrize("body", [{"password": "12345"}, {"password": ""}])
def test_reset_password_too_short(client, admin_h, make_user, body):
    uid = make_user("ana")
    res = client.put(f"{URL}/{uid}/password", json=body, headers=admin_h)
    assert res.status_code == 422
    assert res.json() == {"error": "Password must be at least 6 characters"}


def test_reset_password_missing_field(client, admin_h, make_user):
    uid = make_user("ana")
    assert client.put(f"{URL}/{uid}/password", json={}, headers=admin_h).status_code == 422


def test_reset_password_validation_beats_missing_user(client, admin_h):
    # body is validated before the lookup, so a short password is 422 even for an unknown id
    assert client.put(f"{URL}/9999/password", json={"password": "123"}, headers=admin_h).status_code == 422
