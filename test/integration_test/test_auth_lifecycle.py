"""
End-to-end auth scenarios driven through the real /auth/* endpoints against the
mock in-memory DB — signup, signin, protected access, password change, and the
full forgot-password loop, each as a multi-step user journey rather than one
isolated call.
"""
import routers.auth as auth_module


def test_signup_signin_access_and_change_password_full_journey(app_client):
    """A brand-new user can sign up, sign in, use a protected endpoint, and rotate their password."""
    signup = app_client.post("/auth/signup", json={
        "name": "Priya Shah", "email": "priya@example.com", "password": "OldPass1",
    })
    assert signup.status_code == 201

    signin = app_client.post("/auth/signin", json={"email": "priya@example.com", "password": "OldPass1"})
    assert signin.status_code == 200
    token = signin.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    my_files = app_client.get("/document/my-files", headers=headers)
    assert my_files.status_code == 200
    assert my_files.json() == {"total": 0, "files": []}

    change = app_client.post(
        "/auth/change-password",
        json={"old_password": "OldPass1", "new_password": "NewPass1"},
        headers=headers,
    )
    assert change.status_code == 200

    old_signin = app_client.post("/auth/signin", json={"email": "priya@example.com", "password": "OldPass1"})
    assert old_signin.status_code == 401

    new_signin = app_client.post("/auth/signin", json={"email": "priya@example.com", "password": "NewPass1"})
    assert new_signin.status_code == 200


def test_forgot_password_full_loop(app_client, monkeypatch):
    """Signup -> request reset code -> reset with the correct code -> old password dead, new one works."""
    app_client.post("/auth/signup", json={
        "name": "Ravi Kumar", "email": "ravi.reset@example.com", "password": "OldPass1",
    })

    sent_codes = []
    monkeypatch.setattr(
        auth_module, "send_verification_code_email",
        lambda email, name, code, expires: sent_codes.append(code),
    )

    send = app_client.post("/auth/forgot-password/send-code", json={"email": "ravi.reset@example.com"})
    assert send.status_code == 200
    assert len(sent_codes) == 1
    code = sent_codes[0]

    reset = app_client.post("/auth/forgot-password/reset", json={
        "email": "ravi.reset@example.com",
        "verification_code": code,
        "new_password": "FreshPass1",
        "confirm_password": "FreshPass1",
    })
    assert reset.status_code == 200

    old_signin = app_client.post("/auth/signin", json={"email": "ravi.reset@example.com", "password": "OldPass1"})
    assert old_signin.status_code == 401

    new_signin = app_client.post("/auth/signin", json={"email": "ravi.reset@example.com", "password": "FreshPass1"})
    assert new_signin.status_code == 200

    # The code was single-use — trying to reuse it now fails even though it hasn't expired.
    reuse = app_client.post("/auth/forgot-password/reset", json={
        "email": "ravi.reset@example.com",
        "verification_code": code,
        "new_password": "AnotherPass1",
        "confirm_password": "AnotherPass1",
    })
    assert reuse.status_code == 400


def test_forgot_password_lockout_then_fresh_code_recovers(app_client, monkeypatch):
    """Five wrong codes lock the user out; requesting a brand-new code resets attempts and allows success."""
    app_client.post("/auth/signup", json={
        "name": "Anita Desai", "email": "anita.lockout@example.com", "password": "OldPass1",
    })

    sent_codes = []
    monkeypatch.setattr(
        auth_module, "send_verification_code_email",
        lambda email, name, code, expires: sent_codes.append(code),
    )
    # Cooldown between requests would block a second immediate send-code call —
    # skip forward in time instead of sleeping in the test.
    monkeypatch.setattr(auth_module, "PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", 0)

    app_client.post("/auth/forgot-password/send-code", json={"email": "anita.lockout@example.com"})
    assert len(sent_codes) == 1

    for _ in range(5):
        resp = app_client.post("/auth/forgot-password/reset", json={
            "email": "anita.lockout@example.com",
            "verification_code": "000000",
            "new_password": "NewPass1",
            "confirm_password": "NewPass1",
        })
        assert resp.status_code == 400

    locked = app_client.post("/auth/forgot-password/reset", json={
        "email": "anita.lockout@example.com",
        "verification_code": sent_codes[0],
        "new_password": "NewPass1",
        "confirm_password": "NewPass1",
    })
    assert locked.status_code == 429

    # A fresh code request resets the attempt counter.
    app_client.post("/auth/forgot-password/send-code", json={"email": "anita.lockout@example.com"})
    assert len(sent_codes) == 2

    recovered = app_client.post("/auth/forgot-password/reset", json={
        "email": "anita.lockout@example.com",
        "verification_code": sent_codes[1],
        "new_password": "NewPass1",
        "confirm_password": "NewPass1",
    })
    assert recovered.status_code == 200


def test_two_users_complete_independent_auth_journeys_without_interference(app_client, monkeypatch):
    """Two users going through signup/signin/change-password concurrently never affect each other."""
    monkeypatch.setattr(auth_module, "send_verification_code_email", lambda *a, **k: None)

    app_client.post("/auth/signup", json={"name": "User A", "email": "usera.auth@example.com", "password": "PassA123"})
    app_client.post("/auth/signup", json={"name": "User B", "email": "userb.auth@example.com", "password": "PassB123"})

    signin_a = app_client.post("/auth/signin", json={"email": "usera.auth@example.com", "password": "PassA123"})
    signin_b = app_client.post("/auth/signin", json={"email": "userb.auth@example.com", "password": "PassB123"})
    headers_a = {"Authorization": f"Bearer {signin_a.json()['access_token']}"}
    headers_b = {"Authorization": f"Bearer {signin_b.json()['access_token']}"}

    app_client.post(
        "/auth/change-password",
        json={"old_password": "PassA123", "new_password": "NewPassA123"},
        headers=headers_a,
    )

    # User A's password changed; user B's is untouched.
    assert app_client.post("/auth/signin", json={"email": "usera.auth@example.com", "password": "PassA123"}).status_code == 401
    assert app_client.post("/auth/signin", json={"email": "usera.auth@example.com", "password": "NewPassA123"}).status_code == 200
    assert app_client.post("/auth/signin", json={"email": "userb.auth@example.com", "password": "PassB123"}).status_code == 200

    me_b = app_client.post("/auth/me", params={"token": headers_b["Authorization"]})
    assert me_b.json()["email"] == "userb.auth@example.com"
