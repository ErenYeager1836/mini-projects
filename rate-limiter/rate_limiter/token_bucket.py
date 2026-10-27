"""
Token Bucket algorithm implementation for rate limiting with burst support.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

from rate_limiter.base import BaseRateLimiter, RateLimitResult


class _BucketState:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, tokens: float, last_refill: float):
        self.tokens = tokens
        self.last_refill = last_refill


class TokenBucketLimiter(BaseRateLimiter):
    """
    Token Bucket rate limiter.
    
    Tokens refill continuously at `refill_rate` (tokens per second) up to a maximum
    `capacity`. Requests consume tokens. Accommodates short bursts up to `capacity`.
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        time_fn: Optional[Callable[[], float]] = None
    ):
        super().__init__(time_fn=time_fn)
        if capacity <= 0:
            raise ValueError("Capacity must be strictly positive (> 0).")
        if refill_rate <= 0:
            raise ValueError("Refill rate must be strictly positive (> 0 tokens/sec).")

        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._buckets: Dict[str, _BucketState] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str = "default", cost: float = 1.0) -> RateLimitResult:
        if cost <= 0:
            raise ValueError("Cost must be greater than zero.")

        now = self._time_fn()

        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(tokens=self.capacity, last_refill=now)
                self._buckets[key] = state
            else:
                # Calculate tokens accumulated since last check
                elapsed = max(0.0, now - state.last_refill)
                state.tokens = min(self.capacity, state.tokens + (elapsed * self.refill_rate))
                state.last_refill = now

            if state.tokens >= cost:
                state.tokens -= cost
                reset_after = (self.capacity - state.tokens) / self.refill_rate
                return RateLimitResult(
                    allowed=True,
                    limit=self.capacity,
                    remaining=state.tokens,
                    reset_after=max(0.0, reset_after),
                    retry_after=None
                )
            else:
                deficit = cost - state.tokens
                retry_after = deficit / self.refill_rate
                reset_after = (self.capacity - state.tokens) / self.refill_rate
                return RateLimitResult(
                    allowed=False,
                    limit=self.capacity,
                    remaining=state.tokens,
                    reset_after=max(0.0, reset_after),
                    retry_after=max(0.0, retry_after)
                )

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is not None:
                self._buckets.pop(key, None)
            else:
                self._buckets.clear()
