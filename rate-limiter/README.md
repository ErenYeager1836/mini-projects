# Rate Limiter (Python Library)

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)
[![Tests](https://img.shields.io/badge/Tests-9%20Passed-brightgreen.svg)](tests/)

A lightweight, thread-safe Python rate-limiting library implementing **Token Bucket** and **Sliding Window Log** algorithms, complete with function decorators, async coroutine support, and high-concurrency performance benchmarks (>600k ops/sec).

---

## What It Does

- **Token Bucket Limiter**: Supports configurable capacity and continuous refill rates with burst tolerance.
- **Sliding Window Log Limiter**: Eliminates boundary spikes by tracking rolling timestamp logs within strict time windows.
- **Versatile Decorator (`@rate_limit`)**:
  - Transparently wraps both synchronous functions and asynchronous `async def` coroutines.
  - Supports dynamic key resolution (e.g. rate limit by `user_id`, `client_ip`, or endpoint).
  - Configurable breach behavior: raises `RateLimitExceeded` or invokes custom fallback callback.
- **Deterministic Testability**: Exposes dependency-injected `time_fn` clocks, enabling microsecond-precision time travel tests without slow `time.sleep()`.
- **Zero Third-Party Dependencies**: Pure standard library implementation with minimal memory overhead.

---

## Project Structure

```text
rate-limiter/
├── rate_limiter/
│   ├── __init__.py
│   ├── base.py           # BaseRateLimiter abstract class, RateLimitResult, and RateLimitExceeded
│   ├── benchmark.py      # Micro-benchmark CLI measuring throughput, latency, and thread contention
│   ├── decorator.py      # @rate_limit decorator for sync and async functions
│   ├── sliding_window.py # Sliding Window Log implementation
│   └── token_bucket.py   # Token Bucket implementation
├── tests/
│   ├── __init__.py
│   └── test_rate_limiter.py # 9 unit and integration tests
├── DESIGN.md             # Algorithm comparisons and mathematical trade-offs
├── pyproject.toml        # Packaging configuration and pytest setup
└── README.md
```

---

## Installation

```bash
cd rate-limiter
pip install -e .
```
*(Or install `pytest` for running test suites)*

---

## Usage Examples

### 1. Token Bucket (Burst-Tolerant)
```python
from rate_limiter import TokenBucketLimiter

# Capacity: 10 tokens maximum burst; Refill: 2 tokens added per second
limiter = TokenBucketLimiter(capacity=10, refill_rate=2.0)

result = limiter.acquire("user_101", cost=1)
if result.allowed:
    print(f"Request allowed! Tokens remaining: {result.remaining:.1f}")
else:
    print(f"Rate limited. Please retry in {result.retry_after:.2f} seconds.")
```

### 2. Sliding Window (Strict Window Enforcement)
```python
from rate_limiter import SlidingWindowLimiter

# Maximum 5 requests per 60-second rolling window
limiter = SlidingWindowLimiter(max_requests=5, window_seconds=60.0)

res = limiter.acquire("api_client_alpha")
print(f"Allowed: {res.allowed}, Remaining quota: {res.remaining}")
```

### 3. Function Decorator
```python
from rate_limiter import TokenBucketLimiter, rate_limit, RateLimitExceeded

api_limiter = TokenBucketLimiter(capacity=5, refill_rate=1.0)

# Rate limit by user_id argument
@rate_limit(api_limiter, key_func=lambda user_id, *args: f"user:{user_id}")
def send_message(user_id: str, content: str):
    return f"Message sent to {user_id}: {content}"

try:
    for _ in range(10):
        send_message("alice", "Hello!")
except RateLimitExceeded as e:
    print(f"Blocked: {e} (retry after {e.result.retry_after:.2f}s)")
```

### 4. Custom Fallback Handler (No Exception)
```python
def on_throttled(key, result):
    return {"status": "throttled", "retry_after": result.retry_after}

@rate_limit(api_limiter, on_breach=on_throttled)
def fetch_report(client_id: str):
    return {"status": "success", "data": [1, 2, 3]}
```

---

## Performance Benchmarks

Run the built-in benchmark suite to evaluate latency and throughput under high thread contention:
```bash
python rate_limiter/benchmark.py --ops 100000 --threads 4
```

*Sample Output:*
```text
==========================================================================
                RATE LIMITER MICRO-BENCHMARK SUITE                        
==========================================================================
Total Operations: 100,000 | Concurrency: 4 threads

Algorithm            | Mode         | Throughput (ops/sec)   | Avg Latency 
---------------------------------------------------------------------------
TokenBucket          | Single       |          674,980.2 ops/s |      1.48 us
SlidingWindow        | Single       |          572,504.9 ops/s |      1.75 us
TokenBucket          | 4 Threads    |          618,871.2 ops/s |      1.62 us
SlidingWindow        | 4 Threads    |          590,475.6 ops/s |      1.69 us
==========================================================================
```

---

## Running Automated Tests

```bash
pytest rate-limiter/tests -v
```

*Output:*
```text
rate-limiter/tests/test_rate_limiter.py::test_token_bucket_burst_and_exhaustion PASSED [ 11%]
rate-limiter/tests/test_rate_limiter.py::test_token_bucket_refill_over_time PASSED [ 22%]
rate-limiter/tests/test_rate_limiter.py::test_token_bucket_key_isolation PASSED [ 33%]
rate-limiter/tests/test_rate_limiter.py::test_sliding_window_burst_and_window_eviction PASSED [ 44%]
rate-limiter/tests/test_rate_limiter.py::test_sliding_window_key_isolation PASSED [ 55%]
rate-limiter/tests/test_rate_limiter.py::test_decorator_sync_function PASSED [ 66%]
rate-limiter/tests/test_rate_limiter.py::test_decorator_custom_key_func_and_on_breach PASSED [ 77%]
rate-limiter/tests/test_rate_limiter.py::test_decorator_async_coroutine PASSED [ 88%]
rate-limiter/tests/test_rate_limiter.py::test_benchmark_runner_executes_cleanly PASSED [100%]

============================== 9 passed in 0.09s ==============================
```

---

## Limitations

- **Process-Local Memory**: Limits are tracked inside the Python process heap; states are not shared across separate multi-process workers (e.g. multiple Gunicorn worker processes) without an external store.
- **Sliding Window Memory**: Tracks individual timestamps in a double-ended queue. For extremely high rates (e.g. 100,000 requests per window per key), memory scales linearly with $N$.

---

## Roadmap

- [ ] **Redis Backend**: Redis adapter using atomic Lua scripts for horizontal, multi-pod clusters.
- [ ] **Sliding Window Counter**: Approximate counter combining current and previous window weights for $O(1)$ memory sliding windows.
- [ ] **FastAPI & Flask Middleware**: Drop-in HTTP middleware injecting `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` headers.
