"""Persistent, self-healing SMTP client optimized for Titan SMTP."""

import os
import smtplib
import socket
import ssl
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.smtp_classifier import SMTPClassifier, SMTPStatus
from app.database.db import get_connection
from app.utils.logger import logger
from config import CONFIG


_global_lock = threading.Lock()
_global_stats = {
    "sent": 0,
    "failed": 0,
    "retries": 0,
    "connections": 0,
    "reconnections": 0,
    "last_error": None,
    "last_success_at": None,
}


class SMTPDeliveryError(Exception):
    def __init__(self, message, status=SMTPStatus.UNKNOWN, category="unknown", retryable=False):
        super().__init__(message)
        self.status = status
        self.category = category
        self.retryable = retryable


def _bump(key, value=1):
    with _global_lock:
        if isinstance(value, int):
            _global_stats[key] += value
        else:
            _global_stats[key] = value


def get_smtp_health():
    with _global_lock:
        snapshot = dict(_global_stats)
    snapshot["healthy"] = snapshot["last_error"] is None
    return snapshot


def _get_setting(key, default=""):
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT value FROM smtp_settings WHERE key=?", (key,)).fetchone()
            if row:
                return row[0]
    except Exception:
        logger.debug("Unable to read SMTP setting %s from SQLite", key, exc_info=True)
    return os.getenv(key.upper(), default)


class Mailer:
    def __init__(self, smtp_factory=None, sleep_func=time.sleep):
        self.server = None
        self.connected = False
        self.connection_count = 0
        self.stats = {"sent": 0, "failed": 0, "retries": 0, "connections": 0, "reconnections": 0}
        self._cfg = None
        self._smtp_factory = smtp_factory
        self._sleep = sleep_func
        self._lock = threading.RLock()
        self._last_noop = 0.0
        self.last_error = None

    def _load_config(self):
        return {
            "smtp_server": _get_setting("smtp_server", os.getenv("SMTP_SERVER", "")),
            "smtp_port": int(_get_setting("smtp_port", os.getenv("SMTP_PORT", "465"))),
            "smtp_username": _get_setting("smtp_username", os.getenv("SMTP_USERNAME", "")),
            "smtp_password": _get_setting("smtp_password", os.getenv("SMTP_PASSWORD", "")),
            "sender_name": _get_setting("sender_name", os.getenv("SENDER_NAME", "")),
            "use_ssl": _get_setting("use_ssl", os.getenv("USE_SSL", "true")).lower() == "true",
        }

    def connect(self):
        with self._lock:
            if self.connected and self.server:
                return
            self._cfg = self._load_config()
            if not self._cfg["smtp_server"] or not self._cfg["smtp_username"]:
                raise ValueError("SMTP server and username must be configured")
            context = ssl.create_default_context()
            try:
                if self._smtp_factory:
                    self.server = self._smtp_factory(self._cfg, context)
                elif self._cfg["use_ssl"]:
                    self.server = smtplib.SMTP_SSL(
                        self._cfg["smtp_server"], self._cfg["smtp_port"],
                        context=context, timeout=CONFIG.SMTP_TIMEOUT,
                    )
                else:
                    self.server = smtplib.SMTP(
                        self._cfg["smtp_server"], self._cfg["smtp_port"], timeout=CONFIG.SMTP_TIMEOUT
                    )
                    self.server.ehlo()
                    self.server.starttls(context=context)
                    self.server.ehlo()
                self.server.login(self._cfg["smtp_username"], self._cfg["smtp_password"])
                self.connected = True
                self.last_error = None
                self._last_noop = time.monotonic()
                self.stats["connections"] += 1
                _bump("connections")
                logger.info("SMTP connection established to %s:%s", self._cfg["smtp_server"], self._cfg["smtp_port"])
            except Exception as exc:
                self.connected = False
                self.server = None
                self.last_error = str(exc)
                _bump("last_error", self.last_error)
                raise

    def validate_connection(self, force=False):
        with self._lock:
            if not self.connected or not self.server:
                return False
            interval = getattr(CONFIG, "SMTP_NOOP_INTERVAL", 60)
            if not force and time.monotonic() - self._last_noop < interval:
                return True
            try:
                code, _ = self.server.noop()
                self._last_noop = time.monotonic()
                if int(code) >= 400:
                    raise smtplib.SMTPServerDisconnected(f"SMTP NOOP returned {code}")
                return True
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)
                _bump("last_error", self.last_error)
                return False

    def reconnect(self, delay=1):
        with self._lock:
            logger.info("Reconnecting SMTP session")
            self.disconnect()
            if delay:
                self._sleep(delay)
            self.connect()
            self.stats["reconnections"] += 1
            _bump("reconnections")
            self.connection_count = 0

    def _message(self, recipient, subject, html):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        sender_name = self._cfg.get("sender_name", "").strip()
        msg["From"] = f"{sender_name} <{self._cfg['smtp_username']}>" if sender_name else self._cfg["smtp_username"]
        msg["To"] = recipient
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg

    def send_email(self, recipient, subject, html):
        with self._lock:
            if not self.connected:
                self.connect()
            elif not self.validate_connection():
                self.reconnect(delay=0)
            msg = self._message(recipient, subject, html)
            last_error = None

            for attempt in range(CONFIG.MAX_RETRIES + 1):
                try:
                    self.server.sendmail(self._cfg["smtp_username"], recipient, msg.as_string())
                    self.stats["sent"] += 1
                    self.connection_count += 1
                    self.last_error = None
                    _bump("sent")
                    _bump("last_error", None)
                    _bump("last_success_at", time.time())
                    if self.connection_count >= CONFIG.RECONNECT_AFTER:
                        self.reconnect(delay=0)
                    return {"status": "sent", "attempts": attempt + 1}
                except (smtplib.SMTPException, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
                    last_error = exc
                    status, category = SMTPClassifier.classify(exc)
                    retryable = status in {SMTPStatus.RETRY, SMTPStatus.CONNECTION, SMTPStatus.RATE_LIMIT}
                    self.last_error = str(exc)
                    _bump("last_error", self.last_error)
                    logger.warning("SMTP delivery error for %s: %s (%s)", recipient, category, exc)
                    if retryable and attempt < CONFIG.MAX_RETRIES:
                        self.stats["retries"] += 1
                        _bump("retries")
                        waits = CONFIG.RETRY_WAIT_MINUTES
                        wait_minutes = waits[min(attempt, len(waits) - 1)]
                        self._sleep(wait_minutes * 60)
                        self.reconnect(delay=0)
                        continue
                    self.stats["failed"] += 1
                    _bump("failed")
                    raise SMTPDeliveryError(str(exc), status, category, retryable) from exc

            self.stats["failed"] += 1
            _bump("failed")
            raise SMTPDeliveryError(str(last_error or "Maximum retry attempts exceeded"), retryable=False)

    def disconnect(self):
        with self._lock:
            if self.server:
                try:
                    self.server.quit()
                except Exception:
                    try:
                        self.server.close()
                    except Exception:
                        pass
            self.server = None
            self.connected = False

    def health(self):
        return {
            "connected": self.connected,
            "statistics": dict(self.stats),
            "emails_since_connect": self.connection_count,
            "last_error": self.last_error,
        }
