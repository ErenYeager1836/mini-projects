"""
Unit and integration test suite for rate-limiter library.
"""

import asyncio
import pytest

from rate_limiter import (
    BaseRateLimiter,
    RateLimitExceeded,
    RateLimitResult,
    SlidingWindowLimiter,
    TokenBucketLimiter,
    rate_limit,
)
from rate_limiter.benchmark import benchmark_limiter


class MockClock:
    """Deterministic simulated clock for deterministic time travel in tests."""
    def __init__(self, start: float = 1000.0):
        self.current_time = start

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float):
        self.current_time += seconds


def test_token_bucket_burst_and_exhaustion():
    clock = MockClock()
    limiter = TokenBucketLimiter(capacity=3, refill_rate=1.0, time_fn=clock)

    # 3 tokens available: all 3 succeed
    assert limiter.acquire("user1").allowed is True
    assert limiter.acquire("user1").allowed is True
    assert limiter.acquire("user1").allowed is True

    # 4th request must be rejected
    res = limiter.acquire("user1")
    assert res.allowed is False
    assert res.remaining == 0.0
    assert res.retry_after is not None
    assert res.retry_after > 0


def test_token_bucket_refill_over_time():
    clock = MockClock()
    # 2 tokens capacity, refills 1 token every second
    limiter = TokenBucketLimiter(capacity=2, refill_rate=1.0, time_fn=clock)

    assert limiter.acquire("user1", cost=2).allowed is True
    assert limiter.acquire("user1").allowed is False

    # Advance clock by 1.0 second: exactly 1 token should be available
    clock.advance(1.0)
    assert limiter.acquire("user1").allowed is True
    assert limiter.acquire("user1").allowed is False

    # Advance clock by 10.0 seconds: tokens should cap at capacity (2.0)
    clock.advance(10.0)
    res = limiter.acquire("user1")
    assert res.allowed is True
    assert res.remaining == 1.0  # 2 - 1 = 1


def test_token_bucket_key_isolation():
    clock = MockClock()
    limiter = TokenBucketLimiter(capacity=1, refill_rate=0.1, time_fn=clock)

    assert limiter.acquire("alice").allowed is True
    assert limiter.acquire("alice").allowed is False

    # Bob's bucket is distinct and unaffected by Alice
    assert limiter.acquire("bob").allowed is True
    assert limiter.acquire("bob").allowed is False


def test_sliding_window_burst_and_window_eviction():
    clock = MockClock()
    # 3 requests allowed per 10-second window
    limiter = SlidingWindowLimiter(max_requests=3, window_seconds=10.0, time_fn=clock)

    assert limiter.acquire("clientA").allowed is True
    assert limiter.acquire("clientA").allowed is True
    assert limiter.acquire("clientA").allowed is True
    # Exceeded
    assert limiter.acquire("clientA").allowed is False

    # Advance 4 seconds: all 3 are still in the 10-second window
    clock.advance(4.0)
    assert limiter.acquire("clientA").allowed is False

    # Advance past 10 seconds: the first 3 fall outside the window
    clock.advance(6.1)  # Total 10.1 seconds from start
    res = limiter.acquire("clientA")
    assert res.allowed is True
    assert res.remaining == 2.0


def test_sliding_window_key_isolation():
    clock = MockClock()
    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=5.0, time_fn=clock)

    assert limiter.acquire("key1", cost=2).allowed is True
    assert limiter.acquire("key1").allowed is False

    # key2 has independent quota
    assert limiter.acquire("key2").allowed is True


def test_decorator_sync_function():
    clock = MockClock()
    limiter = TokenBucketLimiter(capacity=2, refill_rate=1.0, time_fn=clock)

    call_count = 0

    @rate_limit(limiter)
    def compute(x: int) -> int:
        nonlocal call_count
        call_count += 1
        return x * 2

    assert compute(5) == 10
    assert compute(10) == 20
    assert call_count == 2

    # 3rd call exceeds capacity
    with pytest.raises(RateLimitExceeded) as exc_info:
        compute(15)
    assert exc_info.value.result.allowed is False
    assert call_count == 2  # Function was not executed


def test_decorator_custom_key_func_and_on_breach():
    clock = MockClock()
    limiter = SlidingWindowLimiter(max_requests=1, window_seconds=10.0, time_fn=clock)

    @rate_limit(
        limiter,
        key_func=lambda user_id, action: f"{user_id}:{action}",
        on_breach=lambda key, res: f"Rate limited on {key}"
    )
    def transfer(user_id: str, action: str):
        return "transfer_complete"

    assert transfer("user_101", "withdraw") == "transfer_complete"
    # Same key within window triggers on_breach handler
    assert transfer("user_101", "withdraw") == "Rate limited on user_101:withdraw"
    # Different action key succeeds
    assert transfer("user_101", "deposit") == "transfer_complete"


def test_decorator_async_coroutine():
    clock = MockClock()
    limiter = TokenBucketLimiter(capacity=1, refill_rate=1.0, time_fn=clock)

    @rate_limit(limiter)
    async def fetch_data(item_id: str) -> str:
        await asyncio.sleep(0.001)
        return f"data_{item_id}"

    async def main():
        assert await fetch_data("1") == "data_1"
        with pytest.raises(RateLimitExceeded):
            await fetch_data("1")

    asyncio.run(main())


def test_benchmark_runner_executes_cleanly():
    limiter = TokenBucketLimiter(capacity=1000, refill_rate=1000)
    stats = benchmark_limiter(limiter, num_ops=500, num_threads=2)
    assert stats["total_ops"] == 500
    assert stats["ops_per_sec"] > 0
    assert stats["avg_latency_us"] > 0
