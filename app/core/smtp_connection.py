"""
Persistent SMTP connection management.

This module provides a production-oriented SMTP connection wrapper with
auto-reconnect, TLS support, optional authentication, circuit breaker protection,
statistics tracking, and structured logging.
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from email.message import Message
from typing import Iterable, Optional, Sequence, Union

from .smtp_circuit import CircuitBreaker, CircuitBreakerOpen
from .smtp_statistics import SMTPStatistics


logger = logging.getLogger(__name__)

RecipientInput = Union[str, Sequence[str]]


class SMTPConnectionError(RuntimeError):
    """Raised when an SMTP connection cannot be established or used."""


@dataclass(frozen=True)
class SMTPConnectionConfig:
    """Configuration for an SMTP connection."""

    host: str
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    use_ssl: bool = False
    starttls: bool = True
    require_starttls: bool = True
    timeout_seconds: float = 30.0
    local_hostname: Optional[str] = None
    source_address: Optional[tuple[str, int]] = None
    debug_level: int = 0
    max_reconnect_attempts: int = 3
    reconnect_base_delay_seconds: float = 0.5
    reconnect_max_delay_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("host is required")
        if self.port < 1 or self.port > 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if self.use_ssl and self.starttls:
            raise ValueError("use_ssl and starttls cannot both be enabled")
        if self.require_starttls and not self.starttls:
            raise ValueError("require_starttls requires starttls to be enabled")
        if self.max_reconnect_attempts < 0:
            raise ValueError("max_reconnect_attempts cannot be negative")
        if self.reconnect_base_delay_seconds < 0:
            raise ValueError("reconnect_base_delay_seconds cannot be negative")
        if self.reconnect_max_delay_seconds < self.reconnect_base_delay_seconds:
            raise ValueError(
                "reconnect_max_delay_seconds must be greater than or equal to "
                "reconnect_base_delay_seconds"
            )


class SMTPConnection:
    """
    Persistent SMTP connection with automatic reconnect.

    Instances are thread-safe, but SMTP operations are serialized because the
    underlying smtplib client is not safe for concurrent commands.
    """

    def __init__(
        self,
        config: SMTPConnectionConfig,
        statistics: Optional[SMTPStatistics] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
    ) -> None:
        self.config = config
        self.statistics = statistics or SMTPStatistics()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(name="smtp_connection")
        self.ssl_context = ssl_context or ssl.create_default_context()

        self._smtp: Optional[smtplib.SMTP] = None
        self._connected = False
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        """Return whether the connection believes it is connected."""
        with self._lock:
            return self._connected and self._smtp is not None

    def connect(self) -> None:
        """Establish a new SMTP connection."""
        with self._lock:
            self._connect_locked()

    def close(self) -> None:
        """Close the SMTP connection."""
        with self._lock:
            self._close_locked()

    def noop(self) -> tuple[int, bytes]:
        """
        Send an SMTP NOOP command.

        Returns the SMTP response code and message.
        """
        with self._lock:
            self._ensure_connected_locked()
            assert self._smtp is not None

            try:
                code, response = self._smtp.noop()
            except (smtplib.SMTPException, OSError, socket.error) as exc:
                logger.warning("SMTP NOOP failed; connection will be reset: %r", exc)
                self._mark_disconnected_locked()
                raise SMTPConnectionError("SMTP NOOP failed") from exc

            if code < 200 or code >= 400:
                raise SMTPConnectionError(f"SMTP NOOP returned unexpected code {code}")

            return code, response

    def send_mail(
        self,
        sender: str,
        recipients: RecipientInput,
        message: Union[str, bytes],
        mail_options: Iterable[str] = (),
        rcpt_options: Iterable[str] = (),
    ) -> dict[str, tuple[int, bytes]]:
        """
        Send a raw SMTP message.

        Returns a dictionary of refused recipients as provided by smtplib.
        """
        normalized_recipients = self._normalize_recipients(recipients)
        message_size = self._message_size(message)

        self.statistics.record_attempt()
        started_at = time.monotonic()

        try:
            refused = self.circuit_breaker.call(
                self._send_mail_with_retry,
                sender,
                normalized_recipients,
                message,
                tuple(mail_options),
                tuple(rcpt_options),
            )
        except CircuitBreakerOpen:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=False, latency_seconds=elapsed)
            logger.warning("SMTP send rejected because circuit breaker is open")
            raise
        except smtplib.SMTPRecipientsRefused:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=True, latency_seconds=elapsed)
            logger.exception("SMTP send failed; all recipients were refused")
            raise
        except smtplib.SMTPSenderRefused:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=True, latency_seconds=elapsed)
            logger.exception("SMTP send failed; sender was refused")
            raise
        except smtplib.SMTPDataError as exc:
            elapsed = time.monotonic() - started_at
            permanent = 500 <= getattr(exc, "smtp_code", 0) < 600
            self.statistics.record_failure(
                permanent=permanent,
                latency_seconds=elapsed,
            )
            logger.exception("SMTP DATA command failed")
            raise
        except (smtplib.SMTPException, OSError, socket.error) as exc:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=False, latency_seconds=elapsed)
            logger.exception("SMTP send failed due to transport or protocol error")
            raise SMTPConnectionError("SMTP send failed") from exc
        except Exception:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=False, latency_seconds=elapsed)
            logger.exception("Unexpected SMTP send failure")
            raise

        elapsed = time.monotonic() - started_at
        self.statistics.record_delivery(latency_seconds=elapsed, bytes_sent=message_size)

        if refused:
            logger.warning("SMTP send completed with refused recipients: %s", refused)

        return refused

    def send_message(
        self,
        message: Message,
        sender: Optional[str] = None,
        recipients: Optional[RecipientInput] = None,
        mail_options: Iterable[str] = (),
        rcpt_options: Iterable[str] = (),
    ) -> dict[str, tuple[int, bytes]]:
        """
        Send an email.message.Message through the persistent SMTP connection.

        If sender or recipients are omitted, smtplib derives them from the
        message headers.
        """
        message_size = len(message.as_bytes())
        normalized_recipients = (
            self._normalize_recipients(recipients) if recipients is not None else None
        )

        self.statistics.record_attempt()
        started_at = time.monotonic()

        try:
            refused = self.circuit_breaker.call(
                self._send_message_with_retry,
                message,
                sender,
                normalized_recipients,
                tuple(mail_options),
                tuple(rcpt_options),
            )
        except CircuitBreakerOpen:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=False, latency_seconds=elapsed)
            logger.warning("SMTP message send rejected because circuit breaker is open")
            raise
        except smtplib.SMTPRecipientsRefused:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=True, latency_seconds=elapsed)
            logger.exception("SMTP message send failed; all recipients were refused")
            raise
        except smtplib.SMTPSenderRefused:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=True, latency_seconds=elapsed)
            logger.exception("SMTP message send failed; sender was refused")
            raise
        except smtplib.SMTPDataError as exc:
            elapsed = time.monotonic() - started_at
            permanent = 500 <= getattr(exc, "smtp_code", 0) < 600
            self.statistics.record_failure(
                permanent=permanent,
                latency_seconds=elapsed,
            )
            logger.exception("SMTP message DATA command failed")
            raise
        except (smtplib.SMTPException, OSError, socket.error) as exc:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=False, latency_seconds=elapsed)
            logger.exception("SMTP message send failed due to transport or protocol error")
            raise SMTPConnectionError("SMTP message send failed") from exc
        except Exception:
            elapsed = time.monotonic() - started_at
            self.statistics.record_failure(permanent=False, latency_seconds=elapsed)
            logger.exception("Unexpected SMTP message send failure")
            raise

        elapsed = time.monotonic() - started_at
        self.statistics.record_delivery(latency_seconds=elapsed, bytes_sent=message_size)

        if refused:
            logger.warning(
                "SMTP message send completed with refused recipients: %s",
                refused,
            )

        return refused

    def _connect_locked(self) -> None:
        self._close_locked()

        logger.info(
            "Connecting to SMTP server %s:%s using %s",
            self.config.host,
            self.config.port,
            "SSL" if self.config.use_ssl else "plain TCP",
        )

        try:
            if self.config.use_ssl:
                smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                    host=self.config.host,
                    port=self.config.port,
                    local_hostname=self.config.local_hostname,
                    timeout=self.config.timeout_seconds,
                    source_address=self.config.source_address,
                    context=self.ssl_context,
                )
            else:
                smtp = smtplib.SMTP(
                    host=self.config.host,
                    port=self.config.port,
                    local_hostname=self.config.local_hostname,
                    timeout=self.config.timeout_seconds,
                    source_address=self.config.source_address,
                )

            smtp.set_debuglevel(self.config.debug_level)

            smtp.ehlo_or_helo_if_needed()

            if self.config.starttls:
                if not smtp.has_extn("starttls"):
                    if self.config.require_starttls:
                        raise SMTPConnectionError(
                            "SMTP server does not advertise STARTTLS"
                        )
                    logger.warning("SMTP server does not advertise STARTTLS")
                else:
                    smtp.starttls(context=self.ssl_context)
                    smtp.ehlo()

            if self.config.username is not None:
                smtp.login(self.config.username, self.config.password or "")

            self._smtp = smtp
            self._connected = True

            logger.info("SMTP connection established to %s:%s", self.config.host, self.config.port)

        except Exception:
            self._connected = False
            self._smtp = None
            logger.exception(
                "Failed to establish SMTP connection to %s:%s",
                self.config.host,
                self.config.port,
            )
            raise

    def _close_locked(self) -> None:
        smtp = self._smtp
        self._smtp = None
        self._connected = False

        if smtp is None:
            return

        try:
            smtp.quit()
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError):
            try:
                smtp.close()
            except Exception:
                logger.debug("Ignoring error while closing SMTP socket", exc_info=True)

    def _ensure_connected_locked(self) -> None:
        if not self._connected or self._smtp is None:
            self._reconnect_locked()
            return

        try:
            code, _response = self._smtp.noop()
        except (smtplib.SMTPException, OSError, socket.error):
            logger.warning("SMTP connection check failed; reconnecting", exc_info=True)
            self._mark_disconnected_locked()
            self._reconnect_locked()
            return

        if code < 200 or code >= 400:
            logger.warning("SMTP NOOP returned %s; reconnecting", code)
            self._mark_disconnected_locked()
            self._reconnect_locked()

    def _reconnect_locked(self) -> None:
        attempts = self.config.max_reconnect_attempts + 1
        last_exc: Optional[BaseException] = None

        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1 or self._smtp is not None:
                    self.statistics.record_reconnect()

                self._connect_locked()
                return
            except BaseException as exc:
                last_exc = exc

                if attempt >= attempts:
                    break

                delay = self._reconnect_delay(attempt)
                logger.warning(
                    "SMTP reconnect attempt %s/%s failed; retrying in %.2fs",
                    attempt,
                    attempts,
                    delay,
                    exc_info=True,
                )
                time.sleep(delay)

        raise SMTPConnectionError("Unable to reconnect to SMTP server") from last_exc

    def _send_mail_with_retry(
        self,
        sender: str,
        recipients: list[str],
        message: Union[str, bytes],
        mail_options: tuple[str, ...],
        rcpt_options: tuple[str, ...],
    ) -> dict[str, tuple[int, bytes]]:
        with self._lock:
            self._ensure_connected_locked()
            assert self._smtp is not None

            try:
                return self._smtp.sendmail(
                    sender,
                    recipients,
                    message,
                    mail_options=mail_options,
                    rcpt_options=rcpt_options,
                )
            except (smtplib.SMTPServerDisconnected, OSError, socket.error):
                logger.warning(
                    "SMTP connection lost during send; reconnecting and retrying once",
                    exc_info=True,
                )
                self._mark_disconnected_locked()
                self._reconnect_locked()
                assert self._smtp is not None
                return self._smtp.sendmail(
                    sender,
                    recipients,
                    message,
                    mail_options=mail_options,
                    rcpt_options=rcpt_options,
                )

    def _send_message_with_retry(
        self,
        message: Message,
        sender: Optional[str],
        recipients: Optional[list[str]],
        mail_options: tuple[str, ...],
        rcpt_options: tuple[str, ...],
    ) -> dict[str, tuple[int, bytes]]:
        with self._lock:
            self._ensure_connected_locked()
            assert self._smtp is not None

            try:
                return self._smtp.send_message(
                    message,
                    from_addr=sender,
                    to_addrs=recipients,
                    mail_options=mail_options,
                    rcpt_options=rcpt_options,
                )
            except (smtplib.SMTPServerDisconnected, OSError, socket.error):
                logger.warning(
                    "SMTP connection lost during message send; reconnecting and retrying once",
                    exc_info=True,
                )
                self._mark_disconnected_locked()
                self._reconnect_locked()
                assert self._smtp is not None
                return self._smtp.send_message(
                    message,
                    from_addr=sender,
                    to_addrs=recipients,
                    mail_options=mail_options,
                    rcpt_options=rcpt_options,
                )

    def _mark_disconnected_locked(self) -> None:
        smtp = self._smtp
        self._smtp = None
        self._connected = False

        if smtp is not None:
            try:
                smtp.close()
            except Exception:
                logger.debug("Ignoring error while closing broken SMTP socket", exc_info=True)

    def _reconnect_delay(self, attempt: int) -> float:
        delay = self.config.reconnect_base_delay_seconds * (2 ** max(0, attempt - 1))
        return min(delay, self.config.reconnect_max_delay_seconds)

    @staticmethod
    def _normalize_recipients(recipients: RecipientInput) -> list[str]:
        if isinstance(recipients, str):
            normalized = [recipients]
        else:
            normalized = [recipient for recipient in recipients]

        normalized = [recipient.strip() for recipient in normalized if recipient.strip()]

        if not normalized:
            raise ValueError("at least one recipient is required")

        return normalized

    @staticmethod
    def _message_size(message: Union[str, bytes]) -> int:
        if isinstance(message, bytes):
            return len(message)

        return len(message.encode("utf-8"))
