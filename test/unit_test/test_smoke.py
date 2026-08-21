from models.shop_owner import ShopOwner


def test_root_endpoint(app_client):
    """GET / returns the hello-world payload."""
    resp = app_client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"Hello": "World"}


def test_db_isolated_between_tests_a(db_session):
    """A fresh test DB starts empty, and a row added here should not leak into other tests."""
    assert db_session.query(ShopOwner).count() == 0
    db_session.add(ShopOwner(name="A", email="a@example.com", password_hash="x"))
    db_session.commit()
    assert db_session.query(ShopOwner).count() == 1


def test_db_isolated_between_tests_b(db_session):
    """The DB is empty again here, proving fixtures don't share state across tests."""
    # If fixtures leaked state between tests, this would see the row from test A.
    assert db_session.query(ShopOwner).count() == 0


def test_make_user_and_auth_headers(auth_headers):
    """The auth_headers factory fixture returns a usable bearer-token header."""
    headers = auth_headers(email="smoke@example.com", password="Passw0rd")
    assert headers["Authorization"].startswith("Bearer ")
