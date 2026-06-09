import smtplib
import ssl
import os

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.database.db import get_connection


def _get_setting(key, default=""):
    """Read a setting from SQLite settings table, fall back to env var then default."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM smtp_settings WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass
    return os.getenv(key.upper(), default)


class Mailer:

    def __init__(self):
        self.server = None

    def _load_config(self):
        return {
            "smtp_server":   _get_setting("smtp_server",   os.getenv("SMTP_SERVER", "")),
            "smtp_port":     int(_get_setting("smtp_port", os.getenv("SMTP_PORT", "465"))),
            "smtp_username": _get_setting("smtp_username", os.getenv("SMTP_USERNAME", "")),
            "smtp_password": _get_setting("smtp_password", os.getenv("SMTP_PASSWORD", "")),
            "sender_name":   _get_setting("sender_name",   os.getenv("SENDER_NAME", "")),
            "use_ssl":       _get_setting("use_ssl",       os.getenv("USE_SSL", "true")).lower() == "true",
        }

    def connect(self):

        cfg = self._load_config()
        context = ssl.create_default_context()

        if cfg["use_ssl"]:
            # SSL CONNECTION (Port 465) – matches original Titan SMTP setup
            self.server = smtplib.SMTP_SSL(
                cfg["smtp_server"],
                cfg["smtp_port"],
                context=context,
                timeout=30
            )
        else:
            # STARTTLS fallback (Port 587)
            self.server = smtplib.SMTP(
                cfg["smtp_server"],
                cfg["smtp_port"],
                timeout=30
            )
            self.server.starttls(context=context)

        self.server.login(
            cfg["smtp_username"],
            cfg["smtp_password"]
        )

        self._cfg = cfg

    def send_email(
        self,
        recipient,
        subject,
        html_content
    ):

        cfg = self._cfg

        msg = MIMEMultipart("alternative")

        msg["Subject"] = subject
        msg["From"] = (
            f"{cfg['sender_name']} <{cfg['smtp_username']}>"
        )
        msg["To"] = recipient

        html_part = MIMEText(
            html_content,
            "html"
        )

        msg.attach(html_part)

        self.server.sendmail(
            cfg["smtp_username"],
            recipient,
            msg.as_string()
        )

    def disconnect(self):
        if self.server:
            try:
                self.server.quit()
            except Exception:
                pass
            self.server = None
