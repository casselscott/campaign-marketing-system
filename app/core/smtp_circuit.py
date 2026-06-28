"""
Circuit breaker utilities for SMTP operations.

This module implements a thread-safe circuit breaker that can be used to protect
SMTP calls from repeatedly hitting an unhealthy upstream server.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Tuple, Type, TypeVar


logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Possible circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(RuntimeError):
    """Raised when an operation is rejected because the circuit is open."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is open; retry after {retry_after:.2f} seconds"
        )


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configuration for a circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout_seconds: float = 60.0
    success_threshold: int = 2
    excluded_exceptions: Tuple[Type[BaseException], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if self.recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be greater than 0")
        if self.success_threshold < 1:
            raise ValueError("success_threshold must be at least 1")


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    """Immutable snapshot of circuit breaker state."""

    name: str
    state: CircuitState
    failure_count: int
    success_count: int
    opened_at: Optional[float]
    last_failure_at: Optional[float]
    last_success_at: Optional[float]
    next_retry_at: Optional[float]

    def as_dict(self) -> dict[str, Any]:
        """Return the snapshot as a JSON-serializable dictionary."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "opened_at": self.opened_at,
            "last_failure_at": self.last_failure_at,
            "last_success_at": self.last_success_at,
            "next_retry_at": self.next_retry_at,
        }


class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    The circuit starts closed. After a configured number of failures it opens and
    rejects calls until the recovery timeout elapses. It then moves to half-open
    and allows trial calls. A configured number of successful trial calls closes
    the circuit again.
    """

    def __init__(
        self,
        name: str = "smtp",
        config: Optional[CircuitBreakerConfig] = None,
    ) -> None:
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: Optional[float] = None
        self._last_failure_at: Optional[float] = None
        self._last_success_at: Optional[float] = None
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state."""
        with self._lock:
            self._refresh_state_locked()
            return self._state

    def snapshot(self) -> CircuitBreakerSnapshot:
        """Return an immutable snapshot of the current circuit state."""
        with self._lock:
            self._refresh_state_locked()
            next_retry_at = None
            if self._state == CircuitState.OPEN and self._opened_at is not None:
                next_retry_at = self._opened_at + self.config.recovery_timeout_seconds

            return CircuitBreakerSnapshot(
                name=self.name,
                state=self._state,
                failure_count=self._failure_count,
                success_count=self._success_count,
                opened_at=self._opened_at,
                last_failure_at=self._last_failure_at,
                last_success_at=self._last_success_at,
                next_retry_at=next_retry_at,
            )

    def allow_request(self) -> bool:
        """Return whether a request is currently allowed."""
        with self._lock:
            self._refresh_state_locked()
            return self._state != CircuitState.OPEN

    def before_call(self) -> None:
        """Validate that a call is allowed, raising if the circuit is open."""
        with self._lock:
            self._refresh_state_locked()
            if self._state == CircuitState.OPEN:
                retry_after = self._retry_after_locked()
                raise CircuitBreakerOpen(self.name, retry_after)

    def record_success(self) -> None:
        """Record a successful operation."""
        with self._lock:
            now = time.time()
            self._last_success_at = now

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._close_locked()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0
                self._success_count = 0

    def record_failure(self, exc: Optional[BaseException] = None) -> None:
        """Record a failed operation."""
        if exc is not None and isinstance(exc, self.config.excluded_exceptions):
            logger.debug(
                "Ignoring excluded exception for circuit breaker '%s': %r",
                self.name,
                exc,
            )
            return

        with self._lock:
            self._last_failure_at = time.time()
            self._success_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._open_locked()
                return

            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.config.failure_threshold:
                    self._open_locked()

    def reset(self) -> None:
        """Reset the circuit to a healthy closed state."""
        with self._lock:
            self._close_locked()
            self._last_failure_at = None
            self._last_success_at = None

    def open(self) -> None:
        """Force the circuit open."""
        with self._lock:
            self._open_locked()

    def close(self) -> None:
        """Force the circuit closed."""
        with self._lock:
            self._close_locked()

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute a synchronous function through the circuit breaker.

        Successes and failures are recorded automatically.
        """
        self.before_call()

        try:
            result = func(*args, **kwargs)
        except BaseException as exc:
            self.record_failure(exc)
            raise

        self.record_success()
        return result

    async def async_call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute an asynchronous function through the circuit breaker.

        Successes and failures are recorded automatically.
        """
        self.before_call()

        try:
            result = await func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self.record_failure(exc)
            raise

        self.record_success()
        return result

    def _refresh_state_locked(self) -> None:
        if self._state != CircuitState.OPEN:
            return

        if self._opened_at is None:
            return

        elapsed = time.time() - self._opened_at
        if elapsed >= self.config.recovery_timeout_seconds:
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0
            logger.info("Circuit breaker '%s' moved to half-open", self.name)

    def _open_locked(self) -> None:
        if self._state != CircuitState.OPEN:
            logger.warning("Circuit breaker '%s' opened", self.name)

        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        self._success_count = 0

    def _close_locked(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.info("Circuit breaker '%s' closed", self.name)

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None

    def _retry_after_locked(self) -> float:
        if self._opened_at is None:
            return self.config.recovery_timeout_seconds

        retry_at = self._opened_at + self.config.recovery_timeout_seconds
        return max(0.0, retry_at - time.time())
