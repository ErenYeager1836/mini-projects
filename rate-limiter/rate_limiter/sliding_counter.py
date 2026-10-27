"""
Sliding Window Counter (Cloudflare-style Hybrid Approximator) algorithm.

Combines Fixed Window Counters with a sliding time weight to achieve O(1) memory
and O(1) compute overhead while preventing boundary burst exploits.
"""

from __future__ import annotations

import math
import threading
from typing import Callable, Dict, Optional

from rate_limiter.base import BaseRateLimiter, RateLimitResult


class _CounterState:
    __slots__ = ("prev_count", "curr_count", "window_start")

    def __init__(self, window_start: float):
        self.prev_count: float = 0.0
        self.curr_count: float = 0.0
        self.window_start: float = window_start


class SlidingWindowCounterLimiter(BaseRateLimiter):
    """
    Sliding Window Counter (Hybrid) rate limiter.

    Memory complexity: O(1) per key (does not store individual request timestamps).
    Time complexity: O(1) per request acquire.

    Approximation formula:
      weight = (window_seconds - elapsed_in_current_window) / window_seconds
      estimated_requests = current_window_count + previous_window_count * weight
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

        self.max_requests = float(max_requests)
        self.window_seconds = float(window_seconds)
        self._states: Dict[str, _CounterState] = {}
        self._lock = threading.Lock()

    def _get_window_start(self, timestamp: float) -> float:
        return math.floor(timestamp / self.window_seconds) * self.window_seconds

    def acquire(self, key: str = "default", cost: float = 1.0) -> RateLimitResult:
        if cost <= 0:
            raise ValueError("Cost must be strictly positive (> 0).")

        now = self._time_fn()
        current_window_start = self._get_window_start(now)
        elapsed = now - current_window_start

        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _CounterState(current_window_start)
                self._states[key] = state
            else:
                diff_windows = int(math.floor((now - state.window_start) / self.window_seconds))
                if diff_windows == 1:
                    # Shift current window to previous window
                    state.prev_count = state.curr_count
                    state.curr_count = 0.0
                    state.window_start = current_window_start
                elif diff_windows > 1:
                    # More than one full window has elapsed: reset both
                    state.prev_count = 0.0
                    state.curr_count = 0.0
                    state.window_start = current_window_start

            # Calculate weighted sliding count
            weight = max(0.0, min(1.0, 1.0 - (elapsed / self.window_seconds)))
            estimated = state.curr_count + (state.prev_count * weight)

            if estimated + cost <= self.max_requests:
                state.curr_count += cost
                remaining = max(0.0, self.max_requests - (estimated + cost))
                reset_after = max(0.0, self.window_seconds - elapsed)

                return RateLimitResult(
                    allowed=True,
                    limit=self.max_requests,
                    remaining=remaining,
                    reset_after=reset_after,
                    retry_after=None
                )
            else:
                remaining = max(0.0, self.max_requests - estimated)
                # Compute estimated time until enough capacity opens up
                needed_reduction = (estimated + cost) - self.max_requests
                if state.prev_count > 0:
                    time_to_decay = (needed_reduction / state.prev_count) * self.window_seconds
                    retry_after = min(self.window_seconds - elapsed, max(0.01, time_to_decay))
                else:
                    retry_after = max(0.01, self.window_seconds - elapsed)

                return RateLimitResult(
                    allowed=False,
                    limit=self.max_requests,
                    remaining=remaining,
                    reset_after=max(0.0, self.window_seconds - elapsed),
                    retry_after=retry_after
                )

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is not None:
                self._states.pop(key, None)
            else:
                self._states.clear()
