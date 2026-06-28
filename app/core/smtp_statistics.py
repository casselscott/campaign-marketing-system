"""
SMTP delivery statistics.

This module provides thread-safe counters and rolling latency metrics for SMTP
delivery operations.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Optional


@dataclass(frozen=True)
class SMTPStatisticsSnapshot:
    """Immutable snapshot of SMTP statistics."""

    started_at: float
    uptime_seconds: float
    total_attempted: int
    total_delivered: int
    total_failed: int
    temporary_failures: int
    permanent_failures: int
    reconnects: int
    circuit_opens: int
    bytes_sent: int
    delivery_rate: float
    failure_rate: float
    throughput_per_minute: float
    average_latency_ms: Optional[float]
    min_latency_ms: Optional[float]
    max_latency_ms: Optional[float]
    p50_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    p99_latency_ms: Optional[float]
    last_attempt_at: Optional[float]
    last_success_at: Optional[float]
    last_failure_at: Optional[float]

    def as_dict(self) -> dict[str, Any]:
        """Return the snapshot as a JSON-serializable dictionary."""
        return {
            "started_at": self.started_at,
            "uptime_seconds": self.uptime_seconds,
            "total_attempted": self.total_attempted,
            "total_delivered": self.total_delivered,
            "total_failed": self.total_failed,
            "temporary_failures": self.temporary_failures,
            "permanent_failures": self.permanent_failures,
            "reconnects": self.reconnects,
            "circuit_opens": self.circuit_opens,
            "bytes_sent": self.bytes_sent,
            "delivery_rate": self.delivery_rate,
            "failure_rate": self.failure_rate,
            "throughput_per_minute": self.throughput_per_minute,
            "average_latency_ms": self.average_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
        }


class SMTPStatistics:
    """
    Thread-safe SMTP statistics tracker.

    Latency metrics are kept in a bounded rolling window to avoid unbounded
    memory growth in long-running processes.
    """

    def __init__(
        self,
        latency_window_size: int = 10_000,
        throughput_window_seconds: float = 60.0,
    ) -> None:
        if latency_window_size < 1:
            raise ValueError("latency_window_size must be at least 1")
        if throughput_window_seconds <= 0:
            raise ValueError("throughput_window_seconds must be greater than 0")

        self.latency_window_size = latency_window_size
        self.throughput_window_seconds = throughput_window_seconds

        self._lock = threading.RLock()
        self._started_at = time.time()

        self._total_attempted = 0
        self._total_delivered = 0
        self._total_failed = 0
        self._temporary_failures = 0
        self._permanent_failures = 0
        self._reconnects = 0
        self._circuit_opens = 0
        self._bytes_sent = 0

        self._latencies_ms: Deque[float] = deque(maxlen=latency_window_size)
        self._delivery_timestamps: Deque[float] = deque()

        self._last_attempt_at: Optional[float] = None
        self._last_success_at: Optional[float] = None
        self._last_failure_at: Optional[float] = None

    def record_attempt(self) -> None:
        """Record a delivery attempt."""
        with self._lock:
            self._total_attempted += 1
            self._last_attempt_at = time.time()

    def record_delivery(self, latency_seconds: float, bytes_sent: int = 0) -> None:
        """Record a successful delivery."""
        now = time.time()
        latency_ms = max(0.0, latency_seconds * 1000.0)

        with self._lock:
            self._total_delivered += 1
            self._bytes_sent += max(0, bytes_sent)
            self._last_success_at = now
            self._latencies_ms.append(latency_ms)
            self._delivery_timestamps.append(now)
            self._prune_delivery_timestamps_locked(now)

    def record_failure(
        self,
        permanent: bool = False,
        latency_seconds: Optional[float] = None,
    ) -> None:
        """Record a failed delivery."""
        with self._lock:
            self._total_failed += 1
            if permanent:
                self._permanent_failures += 1
            else:
                self._temporary_failures += 1

            self._last_failure_at = time.time()

            if latency_seconds is not None:
                self._latencies_ms.append(max(0.0, latency_seconds * 1000.0))

    def record_reconnect(self) -> None:
        """Record an SMTP reconnect."""
        with self._lock:
            self._reconnects += 1

    def record_circuit_open(self) -> None:
        """Record that the SMTP circuit breaker opened."""
        with self._lock:
            self._circuit_opens += 1

    def snapshot(self) -> SMTPStatisticsSnapshot:
        """Return an immutable snapshot of the current statistics."""
        with self._lock:
            now = time.time()
            self._prune_delivery_timestamps_locked(now)

            total_completed = self._total_delivered + self._total_failed
            delivery_rate = (
                self._total_delivered / total_completed if total_completed else 0.0
            )
            failure_rate = self._total_failed / total_completed if total_completed else 0.0
            throughput_per_minute = (
                len(self._delivery_timestamps) / self.throughput_window_seconds * 60.0
            )

            latencies = list(self._latencies_ms)
            average_latency_ms = (
                sum(latencies) / len(latencies) if len(latencies) > 0 else None
            )
            min_latency_ms = min(latencies) if len(latencies) > 0 else None
            max_latency_ms = max(latencies) if len(latencies) > 0 else None

            return SMTPStatisticsSnapshot(
                started_at=self._started_at,
                uptime_seconds=max(0.0, now - self._started_at),
                total_attempted=self._total_attempted,
                total_delivered=self._total_delivered,
                total_failed=self._total_failed,
                temporary_failures=self._temporary_failures,
                permanent_failures=self._permanent_failures,
                reconnects=self._reconnects,
                circuit_opens=self._circuit_opens,
                bytes_sent=self._bytes_sent,
                delivery_rate=delivery_rate,
                failure_rate=failure_rate,
                throughput_per_minute=throughput_per_minute,
                average_latency_ms=average_latency_ms,
                min_latency_ms=min_latency_ms,
                max_latency_ms=max_latency_ms,
                p50_latency_ms=self._percentile(latencies, 50),
                p95_latency_ms=self._percentile(latencies, 95),
                p99_latency_ms=self._percentile(latencies, 99),
                last_attempt_at=self._last_attempt_at,
                last_success_at=self._last_success_at,
                last_failure_at=self._last_failure_at,
            )

    def reset(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self._started_at = time.time()

            self._total_attempted = 0
            self._total_delivered = 0
            self._total_failed = 0
            self._temporary_failures = 0
            self._permanent_failures = 0
            self._reconnects = 0
            self._circuit_opens = 0
            self._bytes_sent = 0

            self._latencies_ms.clear()
            self._delivery_timestamps.clear()

            self._last_attempt_at = None
            self._last_success_at = None
            self._last_failure_at = None

    def _prune_delivery_timestamps_locked(self, now: float) -> None:
        cutoff = now - self.throughput_window_seconds
        while self._delivery_timestamps and self._delivery_timestamps[0] < cutoff:
            self._delivery_timestamps.popleft()

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> Optional[float]:
        if not values:
            return None

        if percentile <= 0:
            return min(values)

        if percentile >= 100:
            return max(values)

        sorted_values = sorted(values)
        index = (len(sorted_values) - 1) * (percentile / 100.0)
        lower_index = int(index)
        upper_index = min(lower_index + 1, len(sorted_values) - 1)
        weight = index - lower_index

        return (
            sorted_values[lower_index] * (1.0 - weight)
            + sorted_values[upper_index] * weight
        )
