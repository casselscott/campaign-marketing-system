"""
SMTP health monitoring.

This module provides active SMTP health checks, latency tracking, and background
monitoring for a persistent SMTP connection.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Deque, Optional

from .smtp_connection import SMTPConnection


logger = logging.getLogger(__name__)


class SMTPHealthStatus(str, Enum):
    """SMTP health status values."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class SMTPHealthSnapshot:
    """Immutable snapshot of SMTP health."""

    status: SMTPHealthStatus
    checked_at: Optional[float]
    healthy: bool
    latency_ms: Optional[float]
    consecutive_successes: int
    consecutive_failures: int
    total_checks: int
    successful_checks: int
    failed_checks: int
    last_error: Optional[str]
    average_latency_ms: Optional[float]
    min_latency_ms: Optional[float]
    max_latency_ms: Optional[float]

    def as_dict(self) -> dict[str, Any]:
        """Return the snapshot as a JSON-serializable dictionary."""
        return {
            "status": self.status.value,
            "checked_at": self.checked_at,
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "consecutive_successes": self.consecutive_successes,
            "consecutive_failures": self.consecutive_failures,
            "total_checks": self.total_checks,
            "successful_checks": self.successful_checks,
            "failed_checks": self.failed_checks,
            "last_error": self.last_error,
            "average_latency_ms": self.average_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
        }


HealthCallback = Callable[[SMTPHealthSnapshot], None]


class SMTPMonitor:
    """
    Active SMTP health monitor.

    The monitor can run checks manually with check_once() or continuously in a
    background daemon thread with start().
    """

    def __init__(
        self,
        connection: SMTPConnection,
        interval_seconds: float = 30.0,
        degraded_after_failures: int = 1,
        unhealthy_after_failures: int = 3,
        latency_window_size: int = 1_000,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")
        if degraded_after_failures < 1:
            raise ValueError("degraded_after_failures must be at least 1")
        if unhealthy_after_failures < degraded_after_failures:
            raise ValueError(
                "unhealthy_after_failures must be greater than or equal to "
                "degraded_after_failures"
            )
        if latency_window_size < 1:
            raise ValueError("latency_window_size must be at least 1")

        self.connection = connection
        self.interval_seconds = interval_seconds
        self.degraded_after_failures = degraded_after_failures
        self.unhealthy_after_failures = unhealthy_after_failures

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callbacks: list[HealthCallback] = []

        self._latencies_ms: Deque[float] = deque(maxlen=latency_window_size)
        self._checked_at: Optional[float] = None
        self._latency_ms: Optional[float] = None
        self._last_error: Optional[str] = None

        self._consecutive_successes = 0
        self._consecutive_failures = 0
        self._total_checks = 0
        self._successful_checks = 0
        self._failed_checks = 0
        self._status = SMTPHealthStatus.UNKNOWN

    @property
    def is_running(self) -> bool:
        """Return whether the background monitor is running."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start background health monitoring."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="smtp-health-monitor",
                daemon=True,
            )
            self._thread.start()

        logger.info("SMTP health monitor started")

    def stop(self, timeout_seconds: float = 5.0) -> None:
        """Stop background health monitoring."""
        self._stop_event.set()

        thread: Optional[threading.Thread]
        with self._lock:
            thread = self._thread

        if thread is not None:
            thread.join(timeout=timeout_seconds)

        with self._lock:
            if self._thread is thread:
                self._thread = None

        logger.info("SMTP health monitor stopped")

    def add_callback(self, callback: HealthCallback) -> None:
        """Register a callback invoked after every health check."""
        with self._lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: HealthCallback) -> None:
        """Remove a previously registered callback."""
        with self._lock:
            self._callbacks = [
                registered
                for registered in self._callbacks
                if registered is not callback
            ]

    def check_once(self) -> SMTPHealthSnapshot:
        """
        Perform a single SMTP health check.

        The health check uses SMTP NOOP through the managed connection.
        """
        started_at = time.monotonic()
        checked_at = time.time()
        healthy = False
        error: Optional[str] = None
        latency_ms: Optional[float] = None

        try:
            code, response = self.connection.noop()
            latency_ms = (time.monotonic() - started_at) * 1000.0

            if 200 <= code < 400:
                healthy = True
            else:
                error = f"SMTP NOOP returned code {code}: {response!r}"
        except Exception as exc:
            latency_ms = (time.monotonic() - started_at) * 1000.0
            error = str(exc)
            logger.warning("SMTP health check failed", exc_info=True)

        snapshot = self._record_check(
            checked_at=checked_at,
            healthy=healthy,
            latency_ms=latency_ms,
            error=error,
        )
        self._notify_callbacks(snapshot)

        return snapshot

    def snapshot(self) -> SMTPHealthSnapshot:
        """Return the latest health snapshot without running a check."""
        with self._lock:
            return self._build_snapshot_locked()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception:
                logger.exception("Unexpected error in SMTP monitor loop")

            self._stop_event.wait(self.interval_seconds)

    def _record_check(
        self,
        checked_at: float,
        healthy: bool,
        latency_ms: Optional[float],
        error: Optional[str],
    ) -> SMTPHealthSnapshot:
        with self._lock:
            self._checked_at = checked_at
            self._latency_ms = latency_ms
            self._last_error = error
            self._total_checks += 1

            if latency_ms is not None:
                self._latencies_ms.append(max(0.0, latency_ms))

            if healthy:
                self._successful_checks += 1
                self._consecutive_successes += 1
                self._consecutive_failures = 0
            else:
                self._failed_checks += 1
                self._consecutive_failures += 1
                self._consecutive_successes = 0

            self._status = self._calculate_status_locked(healthy)

            return self._build_snapshot_locked()

    def _calculate_status_locked(self, healthy: bool) -> SMTPHealthStatus:
        if healthy:
            return SMTPHealthStatus.HEALTHY

        if self._consecutive_failures >= self.unhealthy_after_failures:
            return SMTPHealthStatus.UNHEALTHY

        if self._consecutive_failures >= self.degraded_after_failures:
            return SMTPHealthStatus.DEGRADED

        return SMTPHealthStatus.UNKNOWN

    def _build_snapshot_locked(self) -> SMTPHealthSnapshot:
        latencies = list(self._latencies_ms)

        average_latency_ms = (
            sum(latencies) / len(latencies) if len(latencies) > 0 else None
        )
        min_latency_ms = min(latencies) if len(latencies) > 0 else None
        max_latency_ms = max(latencies) if len(latencies) > 0 else None

        return SMTPHealthSnapshot(
            status=self._status,
            checked_at=self._checked_at,
            healthy=self._status == SMTPHealthStatus.HEALTHY,
            latency_ms=self._latency_ms,
            consecutive_successes=self._consecutive_successes,
            consecutive_failures=self._consecutive_failures,
            total_checks=self._total_checks,
            successful_checks=self._successful_checks,
            failed_checks=self._failed_checks,
            last_error=self._last_error,
            average_latency_ms=average_latency_ms,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
        )

    def _notify_callbacks(self, snapshot: SMTPHealthSnapshot) -> None:
        with self._lock:
            callbacks = list(self._callbacks)

        for callback in callbacks:
            try:
                callback(snapshot)
            except Exception:
                logger.exception("SMTP health callback failed")
