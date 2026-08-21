from datetime import datetime, timedelta, timezone

import routers.auth as auth_module
from utils.otp import hash_otp


# ── Signup ──────────────────────────────────────────────────────────────────

def test_signup_success(app_client):
    """Signing up with valid data returns 201 with the created profile and never leaks the password."""
    resp = app_client.post("/auth/signup", json={
        "name": "Ravi Kumar",
        "email": "ravi@example.com",
        "password": "Passw0rd",
    })

    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "ravi@example.com"
    assert body["plan"] == "free"
    assert "password" not in body
    assert "password_hash" not in body


def test_signup_duplicate_email_rejected(app_client):
    """Signing up twice with the same email is rejected with a 409 on the second attempt."""
    payload = {"name": "Ravi Kumar", "email": "dup@example.com", "password": "Passw0rd"}
    assert app_client.post("/auth/signup", json=payload).status_code == 201

    resp = app_client.post("/auth/signup", json=payload)
    assert resp.status_code == 409


def test_signup_duplicate_username_rejected(app_client):
    """Two different accounts can't share the same username — the second signup gets a 409."""
    app_client.post("/auth/signup", json={
        "name": "User One", "email": "one@example.com", "password": "Passw0rd", "username": "shopkeeper",
    })

    resp = app_client.post("/auth/signup", json={
        "name": "User Two", "email": "two@example.com", "password": "Passw0rd", "username": "shopkeeper",
    })
    assert resp.status_code == 409


def test_signup_rejects_weak_password_too_short(app_client):
    """A password shorter than the minimum length is rejected with a 422."""
    resp = app_client.post("/auth/signup", json={
        "name": "Ravi", "email": "weak1@example.com", "password": "Pass1",
    })
    assert resp.status_code == 422


def test_signup_rejects_password_without_uppercase(app_client):
    """A password with no uppercase letter is rejected with a 422."""
    resp = app_client.post("/auth/signup", json={
        "name": "Ravi", "email": "weak2@example.com", "password": "password1",
    })
    assert resp.status_code == 422


def test_signup_rejects_password_without_digit(app_client):
    """A password with no digit is rejected with a 422."""
    resp = app_client.post("/auth/signup", json={
        "name": "Ravi", "email": "weak3@example.com", "password": "Password",
    })
    assert resp.status_code == 422


def test_signup_rejects_short_name(app_client):
    """A name shorter than the minimum length is rejected with a 422."""
    resp = app_client.post("/auth/signup", json={
        "name": "R", "email": "shortname@example.com", "password": "Passw0rd",
    })
    assert resp.status_code == 422


def test_signup_rejects_invalid_username_characters(app_client):
    """A username containing disallowed characters (like a space) is rejected with a 422."""
    resp = app_client.post("/auth/signup", json={
        "name": "Ravi", "email": "badu@example.com", "password": "Passw0rd", "username": "bad name!",
    })
    assert resp.status_code == 422


# ── Signin ──────────────────────────────────────────────────────────────────

def test_signin_success_returns_token(app_client, make_user):
    """Signing in with correct credentials returns a bearer access token and the user's profile."""
    make_user(email="signin@example.com", password="Passw0rd")

    resp = app_client.post("/auth/signin", json={"email": "signin@example.com", "password": "Passw0rd"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["email"] == "signin@example.com"
    assert body["access_token"]


def test_signin_wrong_password_rejected(app_client, make_user):
    """Signing in with the wrong password is rejected with a 401."""
    make_user(email="wrongpass@example.com", password="Passw0rd")

    resp = app_client.post("/auth/signin", json={"email": "wrongpass@example.com", "password": "WrongPass1"})
    assert resp.status_code == 401


def test_signin_unknown_email_rejected(app_client):
    """Signing in with an email that has no account is rejected with a 401."""
    resp = app_client.post("/auth/signin", json={"email": "ghost@example.com", "password": "Passw0rd"})
    assert resp.status_code == 401


def test_signin_inactive_account_rejected(app_client, make_user):
    """A deactivated account cannot sign in even with the correct password — rejected with a 403."""
    make_user(email="inactive@example.com", password="Passw0rd", is_active=False)

    resp = app_client.post("/auth/signin", json={"email": "inactive@example.com", "password": "Passw0rd"})
    assert resp.status_code == 403


def test_signin_updates_last_login(app_client, make_user, db_session):
    """A successful signin stamps the user's last_login_at, which starts out unset."""
    user = make_user(email="lastlogin@example.com", password="Passw0rd")
    assert user.last_login_at is None

    app_client.post("/auth/signin", json={"email": "lastlogin@example.com", "password": "Passw0rd"})

    db_session.refresh(user)
    assert user.last_login_at is not None


# ── /auth/token (swagger OAuth2 form) ──────────────────────────────────────

def test_token_endpoint_success(app_client, make_user):
    """The OAuth2 form-based /auth/token endpoint issues a bearer token for correct credentials."""
    make_user(email="tokenuser@example.com", password="Passw0rd")

    resp = app_client.post("/auth/token", data={"username": "tokenuser@example.com", "password": "Passw0rd"})

    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"


def test_token_endpoint_wrong_password(app_client, make_user):
    """The OAuth2 form-based /auth/token endpoint rejects incorrect credentials with a 401."""
    make_user(email="tokenuser2@example.com", password="Passw0rd")

    resp = app_client.post("/auth/token", data={"username": "tokenuser2@example.com", "password": "WrongPass1"})
    assert resp.status_code == 401


# ── /auth/me ────────────────────────────────────────────────────────────────

def test_me_returns_profile_for_valid_token(app_client, make_user):
    """/auth/me returns the signed-in user's profile when given a valid "Bearer <token>" value."""
    make_user(email="me@example.com", password="Passw0rd")
    signin = app_client.post("/auth/signin", json={"email": "me@example.com", "password": "Passw0rd"})
    token = signin.json()["access_token"]

    resp = app_client.post("/auth/me", params={"token": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"


def test_me_rejects_missing_bearer_prefix(app_client, make_user):
    """/auth/me rejects a token value that's missing the required "Bearer " prefix."""
    make_user(email="me2@example.com", password="Passw0rd")
    signin = app_client.post("/auth/signin", json={"email": "me2@example.com", "password": "Passw0rd"})
    token = signin.json()["access_token"]

    resp = app_client.post("/auth/me", params={"token": token})  # no "Bearer " prefix
    assert resp.status_code == 401


def test_me_rejects_garbage_token(app_client):
    """/auth/me rejects a syntactically well-formed but invalid JWT with a 401."""
    resp = app_client.post("/auth/me", params={"token": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401


# ── Forgot password: send-code ─────────────────────────────────────────────

def test_send_code_returns_generic_message_for_unknown_email(app_client):
    """Requesting a reset code for an email with no account still returns a generic 200 (no account enumeration)."""
    resp = app_client.post("/auth/forgot-password/send-code", json={"email": "ghost@example.com"})

    assert resp.status_code == 200
    assert "message" in resp.json()


def test_send_code_success_sets_reset_fields_and_sends_email(app_client, make_user, db_session, monkeypatch):
    """A valid reset request emails the user and stores a hashed code with an expiry and zeroed attempt count."""
    user = make_user(email="reset@example.com", password="Passw0rd")

    sent = []
    monkeypatch.setattr(
        auth_module, "send_verification_code_email",
        lambda email, name, code, expires: sent.append((email, name, code, expires)),
    )

    resp = app_client.post("/auth/forgot-password/send-code", json={"email": "reset@example.com"})

    assert resp.status_code == 200
    assert len(sent) == 1
    assert sent[0][0] == "reset@example.com"

    db_session.refresh(user)
    assert user.reset_code_hash is not None
    assert user.reset_code_expires_at is not None
    assert user.reset_code_attempts == 0


def test_send_code_respects_resend_cooldown(app_client, make_user, monkeypatch):
    """Requesting a second reset code immediately after the first is rejected with a 429 cooldown error."""
    make_user(email="cooldown@example.com", password="Passw0rd")
    monkeypatch.setattr(auth_module, "send_verification_code_email", lambda *a, **k: None)

    first = app_client.post("/auth/forgot-password/send-code", json={"email": "cooldown@example.com"})
    assert first.status_code == 200

    second = app_client.post("/auth/forgot-password/send-code", json={"email": "cooldown@example.com"})
    assert second.status_code == 429


def test_send_code_returns_500_when_email_fails(app_client, make_user, monkeypatch):
    """If the email-sending call raises, the endpoint surfaces a 500 instead of silently succeeding."""
    make_user(email="emailfail@example.com", password="Passw0rd")

    def raise_error(*a, **k):
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr(auth_module, "send_verification_code_email", raise_error)

    resp = app_client.post("/auth/forgot-password/send-code", json={"email": "emailfail@example.com"})
    assert resp.status_code == 500


# ── Forgot password: reset ─────────────────────────────────────────────────

def _seed_reset_code(db_session, user, code="482913", minutes_until_expiry=10, attempts=0):
    user.reset_code_hash = hash_otp(code)
    user.reset_code_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes_until_expiry)
    user.reset_code_attempts = attempts
    db_session.commit()
    return code


def test_reset_password_success(app_client, make_user, db_session):
    """A correct verification code resets the password (usable for a new signin) and clears the stored code."""
    user = make_user(email="doreset@example.com", password="OldPass1")
    code = _seed_reset_code(db_session, user)

    resp = app_client.post("/auth/forgot-password/reset", json={
        "email": "doreset@example.com",
        "verification_code": code,
        "new_password": "NewPass1",
        "confirm_password": "NewPass1",
    })

    assert resp.status_code == 200

    signin = app_client.post("/auth/signin", json={"email": "doreset@example.com", "password": "NewPass1"})
    assert signin.status_code == 200

    db_session.refresh(user)
    assert user.reset_code_hash is None


def test_reset_password_wrong_code_increments_attempts(app_client, make_user, db_session):
    """Submitting the wrong verification code is rejected with a 400 and increments the failed-attempt counter."""
    user = make_user(email="wrongcode@example.com", password="OldPass1")
    _seed_reset_code(db_session, user)

    resp = app_client.post("/auth/forgot-password/reset", json={
        "email": "wrongcode@example.com",
        "verification_code": "000000",
        "new_password": "NewPass1",
        "confirm_password": "NewPass1",
    })

    assert resp.status_code == 400
    db_session.refresh(user)
    assert user.reset_code_attempts == 1


def test_reset_password_expired_code_rejected(app_client, make_user, db_session):
    """A verification code past its expiry timestamp is rejected with a 400."""
    user = make_user(email="expired@example.com", password="OldPass1")
    code = _seed_reset_code(db_session, user, minutes_until_expiry=-1)

    resp = app_client.post("/auth/forgot-password/reset", json={
        "email": "expired@example.com",
        "verification_code": code,
        "new_password": "NewPass1",
        "confirm_password": "NewPass1",
    })
    assert resp.status_code == 400


def test_reset_password_too_many_attempts_locks_out(app_client, make_user, db_session):
    """Once the failed-attempt count reaches the limit, further reset attempts are rejected with a 429."""
    user = make_user(email="lockout@example.com", password="OldPass1")
    code = _seed_reset_code(db_session, user, attempts=5)

    resp = app_client.post("/auth/forgot-password/reset", json={
        "email": "lockout@example.com",
        "verification_code": code,
        "new_password": "NewPass1",
        "confirm_password": "NewPass1",
    })
    assert resp.status_code == 429


def test_reset_password_no_pending_code_rejected(app_client, make_user):
    """Resetting a password when no verification code was ever requested is rejected with a 400."""
    make_user(email="nocode@example.com", password="OldPass1")

    resp = app_client.post("/auth/forgot-password/reset", json={
        "email": "nocode@example.com",
        "verification_code": "123456",
        "new_password": "NewPass1",
        "confirm_password": "NewPass1",
    })
    assert resp.status_code == 400


def test_reset_password_mismatched_confirmation_rejected(app_client, make_user, db_session):
    """A new_password/confirm_password mismatch is rejected with a 422, even with a valid code."""
    user = make_user(email="mismatch@example.com", password="OldPass1")
    code = _seed_reset_code(db_session, user)

    resp = app_client.post("/auth/forgot-password/reset", json={
        "email": "mismatch@example.com",
        "verification_code": code,
        "new_password": "NewPass1",
        "confirm_password": "Different1",
    })
    assert resp.status_code == 422


def test_reset_password_weak_new_password_rejected(app_client, make_user, db_session):
    """A weak new_password is rejected with a 422, even with a valid code."""
    user = make_user(email="weakreset@example.com", password="OldPass1")
    code = _seed_reset_code(db_session, user)

    resp = app_client.post("/auth/forgot-password/reset", json={
        "email": "weakreset@example.com",
        "verification_code": code,
        "new_password": "weak",
        "confirm_password": "weak",
    })
    assert resp.status_code == 422


# ── Change password ─────────────────────────────────────────────────────────

def test_change_password_requires_auth(app_client):
    """POST /auth/change-password rejects requests without a bearer token."""
    resp = app_client.post("/auth/change-password", json={
        "old_password": "OldPass1", "new_password": "NewPass1",
    })
    assert resp.status_code == 401


def test_change_password_success(app_client, auth_headers):
    """A signed-in user can change their password given the correct old password, and sign in with the new one."""
    headers = auth_headers(email="changepw@example.com", password="OldPass1")

    resp = app_client.post("/auth/change-password", json={
        "old_password": "OldPass1", "new_password": "NewPass1",
    }, headers=headers)
    assert resp.status_code == 200

    signin = app_client.post("/auth/signin", json={"email": "changepw@example.com", "password": "NewPass1"})
    assert signin.status_code == 200


def test_change_password_wrong_old_password_rejected(app_client, auth_headers):
    """Changing the password with an incorrect old password is rejected with a 401."""
    headers = auth_headers(email="changepw2@example.com", password="OldPass1")

    resp = app_client.post("/auth/change-password", json={
        "old_password": "WrongOld1", "new_password": "NewPass1",
    }, headers=headers)
    assert resp.status_code == 401


def test_change_password_same_as_old_rejected(app_client, auth_headers):
    """Setting the new password identical to the old one is rejected with a 400."""
    headers = auth_headers(email="changepw3@example.com", password="OldPass1")

    resp = app_client.post("/auth/change-password", json={
        "old_password": "OldPass1", "new_password": "OldPass1",
    }, headers=headers)
    assert resp.status_code == 400


def test_change_password_weak_new_password_rejected(app_client, auth_headers):
    """A weak new_password is rejected with a 422, even with the correct old password."""
    headers = auth_headers(email="changepw4@example.com", password="OldPass1")

    resp = app_client.post("/auth/change-password", json={
        "old_password": "OldPass1", "new_password": "weak",
    }, headers=headers)
    assert resp.status_code == 422
