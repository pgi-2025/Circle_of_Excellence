"""
Minimal SMTP email sending. Currently used for one thing: notifying a newly
approved Campus Ambassador of their login credentials. Kept deliberately
small - stdlib smtplib only, no new dependency.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import Config
from flask import current_app


def _send(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Returns True on success, False on any failure (never raises)."""
    if not Config.SMTP_USER or not Config.SMTP_PASSWORD:
        current_app.logger.warning(
            "Email not sent to %s - SMTP_USER/SMTP_PASSWORD not configured.", to_email
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{Config.EMAIL_FROM_NAME} <{Config.SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.sendmail(Config.SMTP_USER, [to_email], msg.as_string())
        current_app.logger.info("Email sent successfully to %s", to_email)
        return True
    except Exception:
        current_app.logger.exception("Failed to send email to %s", to_email)
        return False


def send_ambassador_credentials_email(
    to_email: str, full_name: str, ambassador_code: str, temp_password: str
) -> bool:
    subject = "You're a Circle Of Excellence Campus Ambassador - Login Details"
    login_url = f"{Config.FRONTEND_URL}"
    text_body = (
        f"Hi {full_name},\n\n"
        f"Congratulations! You have been selected as a Campus Ambassador for Circle Of Excellence.\n\n"
        f"Your Ambassador Login details:\n"
        f"Email: {to_email}\n"
        f"Temporary password: {temp_password}\n"
        f"Ambassador code: {ambassador_code}\n\n"
        f"Log in here: {login_url}\n"
        f"Please log in and change your password as soon as possible.\n\n"
        f"Welcome aboard!\n"
    )
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#1a7a3c;">Welcome, Ambassador!</h2>
      <p>Hi {full_name},</p>
      <p>Congratulations! You have been selected as a <strong>Campus Ambassador</strong> for Circle Of Excellence.</p>
      <div style="background:#f4f8f5;border-radius:8px;padding:16px;margin:16px 0;">
        <p style="margin:4px 0;"><strong>Email:</strong> {to_email}</p>
        <p style="margin:4px 0;"><strong>Temporary password:</strong> {temp_password}</p>
        <p style="margin:4px 0;"><strong>Ambassador code:</strong> {ambassador_code}</p>
      </div>
      <p><a href="{login_url}" style="background:#1a7a3c;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;">Log In Now</a></p>
      <p style="font-size:13px;color:#666;">Please log in and change your password as soon as possible.</p>
    </div>
    """
    return _send(to_email, subject, html_body, text_body)