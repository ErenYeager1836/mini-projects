"""
Core interfaces, data classes, and exceptions for rate-limiter library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
from typing import Callable, Optional


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome and telemetry of a rate limit evaluation."""
    allowed: bool
    limit: float
    remaining: float
    reset_after: float
    retry_after: Optional[float] = None


class RateLimitExceeded(Exception):
    """Exception raised when a rate-limited operation exceeds permissible throughput."""

    def __init__(self, key: str, result: RateLimitResult):
        self.key = key
        self.result = result
        retry_msg = f", retry after {result.retry_after:.2f}s" if result.retry_after else ""
        super().__init__(f"Rate limit exceeded for key '{key}' (limit={result.limit}{retry_msg})")


class BaseRateLimiter(ABC):
    """Abstract base class for all rate limiting algorithms."""

    def __init__(self, time_fn: Optional[Callable[[], float]] = None):
        # time_fn allows injecting deterministic clocks during unit testing
        self._time_fn = time_fn if time_fn is not None else time.time

    @abstractmethod
    def acquire(self, key: str = "default", cost: float = 1.0) -> RateLimitResult:
        """
        Attempts to acquire tokens/allowance for the given key.
        Returns a RateLimitResult indicating whether the request is allowed.
        """
        pass

    @abstractmethod
    def reset(self, key: Optional[str] = None) -> None:
        """Resets the state of a specific key or all keys."""
        pass
