import pytest

URL = "/api/v1/settings"
VALID = {"storeName": "Cafe Uno", "taxRatePercent": 7.5, "receiptFooter": "Gracias!"}


def test_get_requires_auth(client):
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize("role", ["admin", "cashier", "cook"])
def test_get_defaults_from_seed_for_every_role(client, headers, role):
    res = client.get(URL, headers=headers(role))
    assert res.status_code == 200
    assert res.json() == {
        "storeName": "POS Metropolitano",
        "taxRatePercent": 0,
        "receiptFooter": "Thank you! God bless you.",
    }


def test_get_falls_back_to_defaults_when_keys_missing(client, headers, db):
    h = headers("cashier")
    db.execute("DELETE FROM settings")
    assert client.get(URL, headers=h).json() == {
        "storeName": "POS Metropolitano",
        "taxRatePercent": 0,
        "receiptFooter": "",
    }


def test_get_tolerates_garbage_tax_value(client, headers, db):
    h = headers("cashier")
    db.execute("UPDATE settings SET value = 'abc' WHERE key = 'tax_rate_percent'")
    assert client.get(URL, headers=h).json()["taxRatePercent"] == 0


def test_put_as_admin_saves_and_returns(client, admin_h, headers):
    res = client.put(URL, json=VALID, headers=admin_h)
    assert res.status_code == 200
    assert res.json() == VALID
    # persisted and visible to other roles
    assert client.get(URL, headers=headers("cook")).json() == VALID


def test_put_trims_and_allows_empty_footer(client, admin_h):
    res = client.put(
        URL, json={"storeName": "  Shop  ", "taxRatePercent": 0, "receiptFooter": "   "}, headers=admin_h
    )
    assert res.status_code == 200
    assert res.json() == {"storeName": "Shop", "taxRatePercent": 0, "receiptFooter": ""}


@pytest.mark.parametrize("tax", [0, 100, 8.875, 0.1])
def test_put_tax_boundaries_and_decimals(client, admin_h, tax):
    res = client.put(URL, json={**VALID, "taxRatePercent": tax}, headers=admin_h)
    assert res.status_code == 200
    assert res.json()["taxRatePercent"] == tax
    assert client.get(URL, headers=admin_h).json()["taxRatePercent"] == tax


def test_put_stores_the_three_keys_as_text(client, admin_h, db):
    client.put(URL, json={**VALID, "taxRatePercent": 10}, headers=admin_h)
    stored = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}
    assert stored == {"store_name": "Cafe Uno", "tax_rate_percent": "10", "receipt_footer": "Gracias!"}


@pytest.mark.parametrize("role", ["cashier", "cook"])
def test_put_forbidden_for_non_admin(client, headers, role):
    res = client.put(URL, json=VALID, headers=headers(role))
    assert res.status_code == 403
    assert res.json() == {"error": "Forbidden"}


def test_put_requires_auth(client):
    assert client.put(URL, json=VALID).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**VALID, "storeName": ""},
        {**VALID, "storeName": "   "},
        {**VALID, "storeName": "x" * 61},
        {**VALID, "taxRatePercent": -0.01},
        {**VALID, "taxRatePercent": 100.01},
        {**VALID, "taxRatePercent": "7"},
        {**VALID, "taxRatePercent": True},
        {**VALID, "taxRatePercent": None},
        {**VALID, "receiptFooter": "x" * 121},
        {**VALID, "receiptFooter": None},
        {"storeName": "A", "taxRatePercent": 1},
    ],
)
def test_put_validation(client, admin_h, db, payload):
    res = client.put(URL, json=payload, headers=admin_h)
    assert res.status_code == 422
    assert res.json() == {"error": "Check the settings values."}
    assert client.get(URL, headers=admin_h).json()["storeName"] == "POS Metropolitano"  # unchanged


def test_put_length_limits_accepted_at_edge(client, admin_h):
    payload = {"storeName": "x" * 60, "taxRatePercent": 1, "receiptFooter": "y" * 120}
    assert client.put(URL, json=payload, headers=admin_h).status_code == 200


def test_put_is_atomic_on_db_failure(client, admin_h, db):
    # A trigger makes the 3rd upsert fail; nothing from the first two may stick.
    db.execute(
        "CREATE TRIGGER boom BEFORE UPDATE ON settings WHEN NEW.key = 'receipt_footer' "
        "BEGIN SELECT RAISE(ABORT, 'boom'); END"
    )
    with pytest.raises(Exception):  # noqa: B017 - TestClient re-raises the server error
        client.put(URL, json=VALID, headers=admin_h)
    db.execute("DROP TRIGGER boom")
    assert client.get(URL, headers=admin_h).json()["storeName"] == "POS Metropolitano"
