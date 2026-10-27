"""
Dead Letter Queue (DLQ) for quarantined, exhausted task-queue jobs.

Enables administrative inspection, traceback auditing, and replay of failed jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from task_queue.job import Job
    from task_queue.queue import TaskQueue


@dataclass
class DeadLetterEntry:
    """Record wrapper for a job committed to the Dead Letter Queue."""
    job: Job
    quarantined_at: float = field(default_factory=time.time)
    reason: str = ""

    @property
    def id(self) -> str:
        return self.job.id

    @property
    def name(self) -> str:
        return self.job.name

    @property
    def error(self) -> Optional[str]:
        return self.job.error

    @property
    def traceback(self) -> Optional[str]:
        return self.job.traceback


class DeadLetterQueue:
    """
    Thread-safe repository isolating permanently failed or poison-pill jobs.
    """

    def __init__(self):
        self._entries: Dict[str, DeadLetterEntry] = {}
        self._lock = threading.Lock()

    def add(self, job: Job, reason: str = "") -> DeadLetterEntry:
        """Quarantines an exhausted job into the DLQ."""
        with self._lock:
            entry = DeadLetterEntry(
                job=job,
                quarantined_at=time.time(),
                reason=reason or (job.error or "Max retries exhausted")
            )
            self._entries[job.id] = entry
            return entry

    def get(self, job_id: str) -> Optional[DeadLetterEntry]:
        """Retrieves a quarantined job by its ID."""
        with self._lock:
            return self._entries.get(job_id)

    def list_entries(self) -> List[DeadLetterEntry]:
        """Returns a snapshot list of all quarantined dead letter entries."""
        with self._lock:
            return list(self._entries.values())

    def size(self) -> int:
        """Current number of quarantined jobs."""
        with self._lock:
            return len(self._entries)

    def remove(self, job_id: str) -> bool:
        """Removes an entry from the dead letter queue."""
        with self._lock:
            return self._entries.pop(job_id, None) is not None

    def clear(self) -> None:
        """Purges all entries from the dead letter queue."""
        with self._lock:
            self._entries.clear()

    def replay(self, job_id: str, target_queue: TaskQueue) -> Optional[Job]:
        """
        Re-submits a quarantined job back into the target queue with reset retry counts.
        Removes the job from the DLQ upon successful re-enqueue.
        """
        with self._lock:
            entry = self._entries.pop(job_id, None)
            if entry is None:
                return None

        job = entry.job
        # Reset execution state for replay
        job.retry_count = 0
        job.error = None
        job.traceback = None
        job.started_at = None
        job.completed_at = None

        target_queue.re_enqueue(job)
        return job
