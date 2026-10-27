"""
Sliding Window Log algorithm implementation for smooth, boundary-accurate rate limiting.
"""

from __future__ import annotations

from collections import deque
import threading
from typing import Callable, Deque, Dict, Optional

from rate_limiter.base import BaseRateLimiter, RateLimitResult


class SlidingWindowLimiter(BaseRateLimiter):
    """
    Sliding Window Log rate limiter.

    Tracks explicit timestamp logs within a rolling window [now - window_seconds, now].
    Completely eliminates the 2x burst vulnerability inherent to Fixed Window algorithms.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        time_fn: Optional[Callable[[], float]] = None
    ):
        super().__init__(time_fn=time_fn)
        if max_requests <= 0:
            raise ValueError("max_requests must be strictly positive (> 0).")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be strictly positive (> 0).")

        self.max_requests = int(max_requests)
        self.window_seconds = float(window_seconds)
        self._windows: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str = "default", cost: float = 1.0) -> RateLimitResult:
        int_cost = int(cost)
        if int_cost <= 0:
            raise ValueError("Cost must be at least 1.")

        now = self._time_fn()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._windows.get(key)
            if timestamps is None:
                timestamps = deque()
                self._windows[key] = timestamps

            # Evict timestamps that have fallen outside the rolling window
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            current_count = len(timestamps)

            if current_count + int_cost <= self.max_requests:
                for _ in range(int_cost):
                    timestamps.append(now)

                remaining = self.max_requests - (current_count + int_cost)
                reset_after = (timestamps[0] + self.window_seconds - now) if timestamps else 0.0

                return RateLimitResult(
                    allowed=True,
                    limit=float(self.max_requests),
                    remaining=float(remaining),
                    reset_after=max(0.0, reset_after),
                    retry_after=None
                )
            else:
                remaining = max(0, self.max_requests - current_count)
                # Retry time is when the oldest timestamp within the window will expire
                retry_after = (timestamps[0] + self.window_seconds - now) if timestamps else 0.0

                return RateLimitResult(
                    allowed=False,
                    limit=float(self.max_requests),
                    remaining=float(remaining),
                    reset_after=max(0.0, retry_after),
                    retry_after=max(0.0, retry_after)
                )

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is not None:
                self._windows.pop(key, None)
            else:
                self._windows.clear()
