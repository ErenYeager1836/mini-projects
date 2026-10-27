"""
Unit tests for Dead Letter Queue (DLQ) quarantine, inspection, and replay mechanisms.
"""

import time
import pytest

from task_queue import Job, JobStatus, TaskQueue


def test_dlq_quarantine_after_max_retries_exhausted():
    tq = TaskQueue(num_workers=2).start()
    try:
        def poison_pill_job():
            raise RuntimeError("Irrecoverable database connection failure")

        # Enqueue with 1 retry and tiny backoff for fast test execution
        job = tq.enqueue(poison_pill_job, max_retries=1, initial_delay=0.01)
        assert tq.wait_for_completion(timeout=3.0)

        assert job.status == JobStatus.FAILED
        assert job.retry_count == 1
        assert "Irrecoverable database" in job.error

        # Verify job is isolated in DLQ
        assert tq.dlq.size() == 1
        entry = tq.dlq.get(job.id)
        assert entry is not None
        assert entry.id == job.id
        assert "poison_pill_job" in entry.name
        assert "Irrecoverable database" in entry.error
        assert entry.traceback is not None

        # Verify queue stats reflect DLQ count
        st = tq.stats()
        assert st.failed == 1
        assert st.dead_letter == 1
    finally:
        tq.stop(wait=True)


def test_dlq_replay_mechanism():
    tq = TaskQueue(num_workers=2).start()
    attempts = 0
    try:
        def flakey_job():
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise ValueError("Transient error")
            return "recovered_data"

        # Initially set max_retries=1 so it fails and ends in DLQ (attempts=1 + retry 1 = attempts=2)
        job = tq.enqueue(flakey_job, max_retries=1, initial_delay=0.01)
        assert tq.wait_for_completion(timeout=3.0)
        assert job.status == JobStatus.FAILED
        assert tq.dlq.size() == 1

        # Replay the job from DLQ (now attempts will reach 3, which succeeds!)
        replayed = tq.replay_dead_letter(job.id)
        assert replayed is not None
        assert tq.dlq.size() == 0  # Removed from DLQ upon replay

        assert tq.wait_for_completion(timeout=3.0)
        assert replayed.status == JobStatus.SUCCESS
        assert replayed.result == "recovered_data"
    finally:
        tq.stop(wait=True)
