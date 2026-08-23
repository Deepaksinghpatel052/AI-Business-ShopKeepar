import os
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME   = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)
SMTP_FROM_NAME  = os.getenv("SMTP_FROM_NAME", "AI-ShopKeeper")
SMTP_USE_TLS    = os.getenv("SMTP_USE_TLS", "true").lower() == "true"


def send_email(to_email: str, subject: str, html_body: str, text_body: str | None = None) -> None:
    """
    SMTP ke through email bhejo.
    Raises RuntimeError agar SMTP configure nahi hai, ya smtplib.SMTPException agar bhejne me fail ho.
    """
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP is not configured. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD in .env"
        )

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    message["To"] = to_email

    if text_body:
        message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    logger.info(f"Sending email — to={to_email} subject={subject!r}")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USE_TLS:
                server.starttls(context=context)
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, message.as_string())
    except Exception:
        logger.exception(f"Failed to send email — to={to_email} subject={subject!r}")
        raise

    logger.info(f"Email sent successfully — to={to_email}")


def send_verification_code_email(to_email: str, name: str, code: str, expires_in_minutes: int = 10) -> None:
    subject = "Your AI-ShopKeeper password reset code"

    text_body = (
        f"Hi {name},\n\n"
        f"Your password reset verification code is: {code}\n"
        f"This code expires in {expires_in_minutes} minutes.\n\n"
        f"If you did not request this, you can ignore this email."
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: auto;">
      <h2>Password Reset Code</h2>
      <p>Hi {name},</p>
      <p>Use the code below to reset your AI-ShopKeeper password:</p>
      <p style="font-size: 28px; font-weight: bold; letter-spacing: 4px; color: #1E3A5F;">{code}</p>
      <p>This code expires in {expires_in_minutes} minutes.</p>
      <p style="color: #888; font-size: 12px;">If you did not request this, you can safely ignore this email.</p>
    </div>
    """

    send_email(to_email, subject, html_body, text_body)
