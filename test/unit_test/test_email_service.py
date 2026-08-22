import smtplib

import pytest

import utils.email_service as email_service


class FakeSMTPServer:
    """Records what would have been sent, instead of opening a real connection."""

    last_instance = None

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.starttls_called_with = "not-called"
        self.login_args = None
        self.sendmail_args = None
        FakeSMTPServer.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        self.starttls_called_with = context

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, from_addr, to_addr, message):
        self.sendmail_args = (from_addr, to_addr, message)


@pytest.fixture()
def configured_smtp(monkeypatch):
    monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_service, "SMTP_PORT", 587)
    monkeypatch.setattr(email_service, "SMTP_USERNAME", "bot@example.com")
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(email_service, "SMTP_FROM_EMAIL", "bot@example.com")
    monkeypatch.setattr(email_service, "SMTP_FROM_NAME", "AI-ShopKeeper")
    monkeypatch.setattr(email_service, "SMTP_USE_TLS", True)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTPServer)
    return FakeSMTPServer


def test_send_email_raises_when_smtp_not_configured(monkeypatch):
    """send_email() raises RuntimeError when SMTP host/username/password aren't set."""
    monkeypatch.setattr(email_service, "SMTP_HOST", None)
    monkeypatch.setattr(email_service, "SMTP_USERNAME", None)
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", None)

    with pytest.raises(RuntimeError):
        email_service.send_email("user@example.com", "Subject", "<p>Body</p>")


def test_send_email_sends_via_smtp_with_tls(configured_smtp):
    """send_email() opens TLS, logs in, and sends the message with the right envelope/content."""
    email_service.send_email(
        to_email="user@example.com",
        subject="Hello",
        html_body="<p>Hi</p>",
        text_body="Hi",
    )

    server = configured_smtp.last_instance
    assert server.host == "smtp.example.com"
    assert server.port == 587
    assert server.starttls_called_with is not None  # starttls() was actually called
    assert server.login_args == ("bot@example.com", "app-password")

    from_addr, to_addr, message = server.sendmail_args
    assert from_addr == "bot@example.com"
    assert to_addr == "user@example.com"
    assert "Hello" in message
    assert "Hi" in message


def test_send_email_skips_starttls_when_use_tls_false(configured_smtp, monkeypatch):
    """send_email() does not call starttls() when SMTP_USE_TLS is False."""
    monkeypatch.setattr(email_service, "SMTP_USE_TLS", False)

    email_service.send_email("user@example.com", "Subject", "<p>Body</p>")

    server = configured_smtp.last_instance
    assert server.starttls_called_with == "not-called"


def test_send_verification_code_email_includes_code_and_expiry(configured_smtp):
    """send_verification_code_email() embeds the code, expiry text, and recipient name in the email body."""
    email_service.send_verification_code_email(
        to_email="user@example.com",
        name="Ravi",
        code="482913",
        expires_in_minutes=15,
    )

    server = configured_smtp.last_instance
    _, to_addr, message = server.sendmail_args
    assert to_addr == "user@example.com"
    assert "482913" in message
    assert "15 minutes" in message
    assert "Ravi" in message
