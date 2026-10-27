# Task Queue (Python)

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)
[![Tests](https://img.shields.io/badge/Tests-7%20Passed-brightgreen.svg)](tests/)

An in-process, thread-safe asynchronous background task execution engine with configurable worker pools, delayed job scheduling, exponential backoff retries, and a terminal status CLI dashboard.

---

## What It Does

- **In-Process Worker Pool**: Spawns managed daemon worker threads to execute background jobs without blocking the main event loop or application thread.
- **Configurable Exponential Backoff**: Automatically catches unhandled exceptions, retrying with exponential delay (`initial_delay * backoff_base ^ attempt`) before marking jobs as `FAILED`.
- **Scheduled & Delayed Execution**: Supports scheduling tasks for future execution using a priority min-heap.
- **Dead-Letter Traceback Capture**: Records exact exception messages and full stack traces for post-mortem debugging.
- **Terminal Status Dashboard**: ASCII CLI table visualizing real-time queue depth, active worker utilization, retry progression, and execution durations.
- **Zero Dependencies**: Pure Python standard library (`threading`, `queue`, `heapq`, `dataclasses`).

---

## Project Structure

```text
task-queue/
├── task_queue/
│   ├── __init__.py
│   ├── cli.py            # Status table formatter and interactive demonstration CLI
│   ├── job.py            # Job model, JobStatus enum, and QueueStats
│   └── queue.py          # TaskQueue engine, scheduler loop, and worker threads
├── tests/
│   ├── __init__.py
│   └── test_task_queue.py # 7 unit and integration tests
├── DESIGN.md             # Architecture, backoff mathematics, and broker comparisons
├── pyproject.toml        # Packaging configuration and pytest setup
└── README.md
```

---

## Installation

```bash
cd task-queue
pip install -e .
```

---

## Usage Examples

### 1. Basic Background Task Execution
```python
import time
from task_queue import TaskQueue

def process_file(filename: str) -> str:
    time.sleep(0.1)
    return f"Processed {filename}"

# Initialize queue with 4 worker threads
q = TaskQueue(num_workers=4).start()

# Enqueue background task
job = q.enqueue(process_file, "dataset.csv", name="csv_processor")
print(f"Enqueued job {job.id} (Status: {job.status})")

# Wait for completion
q.wait_for_completion()
print(f"Result: {job.result} (Took {job.duration:.3f}s)")

q.stop()
```

### 2. Retrying Flaky External Calls with Exponential Backoff
```python
def fetch_payment_status(tx_id: str):
    # Fails 2 times before succeeding on 3rd attempt
    ...

job = q.enqueue(
    fetch_payment_status,
    "tx_9988",
    name="payment_sync",
    max_retries=3,        # Retry up to 3 times
    initial_delay=0.5,    # Initial delay: 0.5s
    backoff_base=2.0      # 0.5s -> 1.0s -> 2.0s
)
```

### 3. Delayed Scheduling
```python
# Schedule a task to execute 10 seconds into the future
q.enqueue(send_reminder_email, "user@example.com", delay_seconds=10.0)
```

---

## Status CLI Dashboard

Run the interactive demonstration to see workers processing jobs, retrying failures, and logging results in real time:
```bash
python task_queue/cli.py demo
```

*Sample Dashboard Output:*
```text
==========================================================================
                      TASK QUEUE STATUS DASHBOARD                         
==========================================================================
Active Workers: 2/3 | Ready Queue Depth: 0
Total Jobs: 5 | Pending: 0 | Running: 1 | Success: 2 | Retrying: 1 | Failed: 1
--------------------------------------------------------------------------
Job ID     | Name                   | Status     | Retries  | Duration   | Result / Error
--------------------------------------------------------------------------
a8b21c4e   | multiply(6,7)          | SUCCESS    | 0/3      | 0.05s      | 42
f91a03d1   | multiply(12,12)        | SUCCESS    | 0/3      | 0.05s      | 144
e729b402   | payment_api            | RETRYING   | 1/3      | -          | ERR: Connection reset by p...
c581a910   | corrupt_batch_job      | FAILED     | 2/2      | -          | ERR: Unrecoverable databas...
d431f904   | delayed_calc           | RUNNING    | 0/3      | -          | ...
==========================================================================
```

---

## Running Automated Tests

```bash
pytest task-queue/tests -v
```

*Output:*
```text
task-queue/tests/test_task_queue.py::test_successful_job_execution PASSED [ 14%]
task-queue/tests/test_task_queue.py::test_job_retry_eventual_success PASSED [ 28%]
task-queue/tests/test_task_queue.py::test_job_retry_exhaustion_transitions_to_failed PASSED [ 42%]
task-queue/tests/test_task_queue.py::test_multiple_workers_concurrency PASSED [ 57%]
task-queue/tests/test_task_queue.py::test_delayed_job_execution PASSED   [ 71%]
task-queue/tests/test_task_queue.py::test_queue_stats_reporting PASSED   [ 85%]
task-queue/tests/test_task_queue.py::test_cli_table_formatting PASSED    [100%]

============================== 7 passed in 2.17s ==============================
```

---

## Limitations

- **In-Memory Volatility**: Jobs reside in process memory. If the host process is forcefully killed (`SIGKILL`), unexecuted tasks are lost.
- **Single Process**: Scales vertically with threads. For CPU-bound tasks, multiprocessing or distributed brokers (Celery) are recommended to bypass the GIL.

---

## Roadmap

- [ ] **Persistent SQLite/Disk Spooling**: Spool enqueued tasks to disk to survive unexpected crashes.
- [ ] **Job Cancellation**: Support manual pre-execution job cancellation (`cancel(job_id)`).
- [ ] **Cron / Recurring Jobs**: Interval scheduling for recurring maintenance tasks.
- [ ] **Web Dashboard**: Minimal FastAPI status monitor with live WebSocket telemetry.
