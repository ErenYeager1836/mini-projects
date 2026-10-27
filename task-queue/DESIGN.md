# Design Note: In-Process Asynchronous Task Queue

## 1. System Architecture

The **Task Queue** is an in-process, thread-based background task execution framework. It features prioritized delayed execution, worker thread pooling, exponential backoff retries, and comprehensive state telemetry.

```text
[ Client Application ] ────( enqueue )────┐
                                           │
                                           ▼
                                [ Delayed Min-Heap ] ──( scheduled_at <= now )──┐
                                           │                                    │
                                           ▼                                    ▼
                                  [ Ready FIFO Queue ] <────────────────────────┘
                                           │
                   ┌───────────────────────┼───────────────────────┐
                   ▼                       ▼                       ▼
            [ Worker Thread 1 ]     [ Worker Thread 2 ]     [ Worker Thread N ]
                   │                       │                       │
                   └───────────────────────┼───────────────────────┘
                                           │
                           (On Success) ───┴─── (On Exception)
                                │                       │
                                ▼                       ▼
                        [ Status: SUCCESS ]     [ Retry Count < Max? ]
                                                ├── YES ──> [ Status: RETRYING ]
                                                │           Compute delay: initial * (base ^ count)
                                                │           Push to Delayed Min-Heap
                                                │
                                                └── NO  ──> [ Status: FAILED ]
                                                            Record Traceback (Dead-Letter)
```

---

## 2. Key Technical Decisions & Trade-Offs

### A. Dual Queue Architecture (Ready FIFO + Delayed Min-Heap)
- **Ready Queue (`queue.Queue`)**: Provides blocking, thread-safe FIFO consumption for worker threads.
- **Delayed Queue (`heapq` Min-Heap)**: Stores tasks scheduled for future execution (either from explicit delays or backoff retries) ordered by `scheduled_at` timestamp.
- **Scheduler Daemon**: A lightweight dispatcher inspects the root of the heap ($O(1)$) and transfers mature tasks to the ready queue ($O(\log K)$) when their timestamp arrives.

### B. Exponential Backoff Retries
- Immediate retries exacerbate transient failures (e.g. database locks, downstream rate limits).
- Exponential backoff gives failing dependencies time to recover:
  $$\text{delay} = \text{initial\_delay} \times (\text{backoff\_base}^{\text{retry\_count}})$$
  - *Example ($0.5\text{s}$ initial, $2.0\text{x}$ base)*:
    - Retry 1: $0.5 \times 2^0 = 0.5\text{s}$
    - Retry 2: $0.5 \times 2^1 = 1.0\text{s}$
    - Retry 3: $0.5 \times 2^2 = 2.0\text{s}$
- Once `retry_count >= max_retries`, the task enters `FAILED` state (acting as an in-process Dead-Letter Queue).

### C. Worker Concurrency & Poison Pills
- **Thread Model**: Python threads (`threading.Thread`) are ideal for I/O-bound tasks (database queries, network API requests, disk operations) where the Global Interpreter Lock (GIL) is released.
- **Poison Pill Mitigation**: Without a retry limit, bad payloads would crash workers endlessly. The `max_retries` safeguard captures full stack traces in `job.traceback` and terminates retries.

### D. Graceful Shutdown Protocol
- `stop(wait=True, timeout=5.0)`:
  1. Sets `running = False`.
  2. Workers complete currently running tasks without pulling new ones from the queue.
  3. Joins worker threads cleanly, preventing orphaned background threads during process exit.

---

## 3. Comparison: In-Process Queue vs. Distributed Brokers

| Feature | In-Process Task Queue (This Tool) | Distributed (Celery / Redis / RabbitMQ) |
| :--- | :--- | :--- |
| **Infrastructure Overhead** | **Zero** (no external broker or Redis instance) | Requires Redis, RabbitMQ, or SQS broker |
| **Latency** | **Microseconds** (in-memory pointer pass) | Milliseconds (network serialization + socket I/O) |
| **Crash Durability** | Non-durable across process crash/kill | Durable (persisted on disk in broker) |
| **Scaling Horizon** | Single machine (vertical scaling) | Multi-node cluster (horizontal scaling) |
| **Complexity** | Minimal, easy to debug and test | High configuration and operational overhead |
