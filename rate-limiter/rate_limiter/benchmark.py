"""
Micro-benchmark and performance comparison suite for Token Bucket vs Sliding Window.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import time
from typing import Dict

# Ensure root package directory is discoverable if script is run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rate_limiter.sliding_window import SlidingWindowLimiter
from rate_limiter.token_bucket import TokenBucketLimiter


def benchmark_limiter(limiter, num_ops: int = 100_000, num_threads: int = 1) -> Dict[str, float]:
    """
    Executes a high-concurrency throughput and latency benchmark for a rate limiter.
    """
    start = time.perf_counter()

    if num_threads == 1:
        for i in range(num_ops):
            limiter.acquire(f"user_{i % 100}")
    else:
        ops_per_thread = num_ops // num_threads

        def worker(thread_id: int):
            for i in range(ops_per_thread):
                limiter.acquire(f"user_{thread_id}_{i % 20}")

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, t) for t in range(num_threads)]
            for f in futures:
                f.result()

    total_time = time.perf_counter() - start
    ops_per_sec = num_ops / total_time
    avg_latency_us = (total_time / num_ops) * 1_000_000

    return {
        "total_ops": num_ops,
        "threads": num_threads,
        "total_time_s": total_time,
        "ops_per_sec": ops_per_sec,
        "avg_latency_us": avg_latency_us,
    }


def main():
    parser = argparse.ArgumentParser(description="Rate Limiter Benchmark Suite")
    parser.add_argument("--ops", type=int, default=100_000, help="Total operations per benchmark (default: 100,000)")
    parser.add_argument("--threads", type=int, default=4, help="Worker threads for concurrent test (default: 4)")
    args = parser.parse_args()

    print("==========================================================================")
    print("                RATE LIMITER MICRO-BENCHMARK SUITE                        ")
    print("==========================================================================")
    print(f"Total Operations: {args.ops:,} | Concurrency: {args.threads} threads\n")

    # 1. Single Thread Token Bucket
    tb = TokenBucketLimiter(capacity=1000, refill_rate=500)
    tb_single = benchmark_limiter(tb, num_ops=args.ops, num_threads=1)

    # 2. Single Thread Sliding Window
    sw = SlidingWindowLimiter(max_requests=1000, window_seconds=60)
    sw_single = benchmark_limiter(sw, num_ops=args.ops, num_threads=1)

    # 3. Multi-Threaded Token Bucket
    tb.reset()
    tb_multi = benchmark_limiter(tb, num_ops=args.ops, num_threads=args.threads)

    # 4. Multi-Threaded Sliding Window
    sw.reset()
    sw_multi = benchmark_limiter(sw, num_ops=args.ops, num_threads=args.threads)

    header = f"{'Algorithm':<20} | {'Mode':<12} | {'Throughput (ops/sec)':<22} | {'Avg Latency':<12}"
    print(header)
    print("-" * len(header))
    print(f"{'TokenBucket':<20} | {'Single':<12} | {tb_single['ops_per_sec']:>18,.1f} ops/s | {tb_single['avg_latency_us']:>9.2f} us")
    print(f"{'SlidingWindow':<20} | {'Single':<12} | {sw_single['ops_per_sec']:>18,.1f} ops/s | {sw_single['avg_latency_us']:>9.2f} us")
    print(f"{'TokenBucket':<20} | {f'{args.threads} Threads':<12} | {tb_multi['ops_per_sec']:>18,.1f} ops/s | {tb_multi['avg_latency_us']:>9.2f} us")
    print(f"{'SlidingWindow':<20} | {f'{args.threads} Threads':<12} | {sw_multi['ops_per_sec']:>18,.1f} ops/s | {sw_multi['avg_latency_us']:>9.2f} us")
    print("==========================================================================\n")


if __name__ == "__main__":
    main()
