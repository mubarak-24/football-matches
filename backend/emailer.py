# backend/emailer.py
import os
import ssl
import smtplib
from email.message import EmailMessage

def send_email(subject: str, body: str, to: str | None = None) -> None:
    """
    Sends an email using SMTP creds from .env.
    If creds missing, prints the body instead (safe fallback for local dev).
    """
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASS")
    to   = to or os.getenv("EMAIL_TO")

    if not (user and pwd and to):
        print("⚠️ Missing SMTP creds; printing body instead.\n")
        print("SUBJECT:", subject)
        print(body)
        return

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"✉️ Email sent to {to}")