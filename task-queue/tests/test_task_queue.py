"""
Unit and integration test suite for task-queue.
"""

import time
import pytest

from task_queue import Job, JobStatus, QueueStats, TaskQueue
from task_queue.cli import format_status_table


def sample_add(a: int, b: int) -> int:
    return a + b


def sample_multiplier(x: int, factor: int = 2) -> int:
    time.sleep(0.02)
    return x * factor


def test_successful_job_execution():
    q = TaskQueue(num_workers=2).start()
    try:
        job = q.enqueue(sample_add, 10, 20)
        assert job.status in (JobStatus.PENDING, JobStatus.RUNNING)

        completed = q.wait_for_completion(timeout=2.0)
        assert completed is True

        refreshed = q.get_job(job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.SUCCESS
        assert refreshed.result == 30
        assert refreshed.error is None
        assert refreshed.duration is not None
        assert refreshed.duration >= 0
    finally:
        q.stop()


def test_job_retry_eventual_success():
    attempts = 0

    def flaky_task():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("Temporary network blip")
        return "recovered"

    q = TaskQueue(num_workers=2).start()
    try:
        job = q.enqueue(flaky_task, max_retries=3, initial_delay=0.05, backoff_base=1.5)
        completed = q.wait_for_completion(timeout=3.0)
        assert completed is True

        assert job.status == JobStatus.SUCCESS
        assert job.result == "recovered"
        assert job.retry_count == 1
        assert attempts == 2
    finally:
        q.stop()


def test_job_retry_exhaustion_transitions_to_failed():
    attempts = 0

    def doomed_task():
        nonlocal attempts
        attempts += 1
        raise ValueError("Fatal payload unparseable")

    q = TaskQueue(num_workers=2).start()
    try:
        job = q.enqueue(doomed_task, max_retries=2, initial_delay=0.05, backoff_base=1.2)
        completed = q.wait_for_completion(timeout=3.0)
        assert completed is True

        assert job.status == JobStatus.FAILED
        assert job.retry_count == 2
        assert attempts == 3  # Initial attempt + 2 retries
        assert "Fatal payload unparseable" in (job.error or "")
        assert job.traceback is not None
    finally:
        q.stop()


def test_multiple_workers_concurrency():
    q = TaskQueue(num_workers=4).start()
    try:
        jobs = [q.enqueue(sample_multiplier, i, factor=3) for i in range(12)]
        completed = q.wait_for_completion(timeout=4.0)
        assert completed is True

        for i, j in enumerate(jobs):
            assert j.status == JobStatus.SUCCESS
            assert j.result == i * 3
    finally:
        q.stop()


def test_delayed_job_execution():
    q = TaskQueue(num_workers=2).start()
    try:
        start_time = time.time()
        job = q.enqueue(sample_add, 1, 2, delay_seconds=0.25)

        # Immediate check should show job still pending or not started
        assert job.status == JobStatus.PENDING

        completed = q.wait_for_completion(timeout=2.0)
        elapsed = time.time() - start_time

        assert completed is True
        assert elapsed >= 0.20  # Must have respected the delay
        assert job.status == JobStatus.SUCCESS
        assert job.result == 3
    finally:
        q.stop()


def test_queue_stats_reporting():
    q = TaskQueue(num_workers=2)
    s = q.stats()
    assert s.total == 0
    assert s.pending == 0

    q.enqueue(sample_add, 1, 1)
    q.enqueue(sample_add, 2, 2)
    s = q.stats()
    assert s.total == 2
    assert s.pending == 2

    q.start()
    q.wait_for_completion(timeout=2.0)
    s = q.stats()
    assert s.total == 2
    assert s.success == 2
    assert s.pending == 0
    q.stop()


def test_cli_table_formatting():
    q = TaskQueue(num_workers=2).start()
    try:
        q.enqueue(sample_add, 5, 5, name="add_five")
        q.wait_for_completion(timeout=2.0)

        table_str = format_status_table(q)
        assert "TASK QUEUE STATUS DASHBOARD" in table_str
        assert "add_five" in table_str
        assert "SUCCESS" in table_str
    finally:
        q.stop()
