"""
Unit tests for the Sliding Window Counter (Cloudflare Hybrid) limiter.
"""

from concurrent.futures import ThreadPoolExecutor
import pytest

from rate_limiter import SlidingWindowCounterLimiter, rate_limit, RateLimitExceeded


class MockClock:
    def __init__(self, start: float = 1000.0):
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float):
        self.current += seconds


def test_sliding_counter_basic_allow_and_reject():
    clock = MockClock(100.0)
    limiter = SlidingWindowCounterLimiter(max_requests=5, window_seconds=10.0, time_fn=clock)

    for i in range(5):
        res = limiter.acquire("api")
        assert res.allowed
        assert res.remaining == 4 - i

    # 6th request rejected
    res = limiter.acquire("api")
    assert not res.allowed
    assert res.remaining == 0
    assert res.retry_after is not None


def test_sliding_counter_weighted_decay():
    clock = MockClock(100.0)
    limiter = SlidingWindowCounterLimiter(max_requests=10, window_seconds=10.0, time_fn=clock)

    # Fill window 1: 10 requests at t=100.0
    for _ in range(10):
        assert limiter.acquire("api").allowed

    assert not limiter.acquire("api").allowed

    # Advance halfway through window 2: t=115.0 (elapsed in current window = 5.0, weight = 0.5)
    clock.advance(15.0)

    # Previous count = 10 * 0.5 = 5 estimated. We should be able to make 5 new requests!
    for _ in range(5):
        assert limiter.acquire("api").allowed

    # 6th request exceeds 10 total estimated
    assert not limiter.acquire("api").allowed


def test_sliding_counter_decorator_integration():
    clock = MockClock(100.0)
    limiter = SlidingWindowCounterLimiter(max_requests=2, window_seconds=5.0, time_fn=clock)

    @rate_limit(limiter, key_func=lambda user_id: user_id)
    def fetch_data(user_id: str):
        return f"data_for_{user_id}"

    assert fetch_data("u1") == "data_for_u1"
    assert fetch_data("u1") == "data_for_u1"

    with pytest.raises(RateLimitExceeded):
        fetch_data("u1")

    # Another user is independent
    assert fetch_data("u2") == "data_for_u2"


def test_sliding_counter_concurrency():
    limiter = SlidingWindowCounterLimiter(max_requests=100, window_seconds=1.0)

    def worker():
        allowed = 0
        for _ in range(25):
            if limiter.acquire("concurrent").allowed:
                allowed += 1
        return allowed

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: worker(), range(8)))

    # Total requests attempted = 200, exactly 100 must be allowed
    assert sum(results) == 100
