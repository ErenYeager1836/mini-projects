"""
Job definition, lifecycle statuses, and telemetry dataclasses for task-queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Callable, Dict, Optional
import uuid


class JobStatus(str, Enum):
    """Lifecycle states of an enqueued job."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"


@dataclass
class Job:
    """Represents a unit of work enqueued for background execution."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    func: Callable[..., Any] = field(default=None)
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    name: str = ""

    # Status & Telemetry
    status: JobStatus = JobStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    traceback: Optional[str] = None

    # Retry & Backoff Configuration
    max_retries: int = 3
    retry_count: int = 0
    initial_delay: float = 0.5
    backoff_base: float = 2.0
    scheduled_at: float = field(default_factory=time.time)

    # Timestamps
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def __post_init__(self):
        if not self.name and self.func is not None:
            self.name = getattr(self.func, "__qualname__", getattr(self.func, "__name__", "anonymous_job"))

    @property
    def duration(self) -> Optional[float]:
        """Total execution duration in seconds, if completed."""
        if self.started_at is not None and self.completed_at is not None:
            return max(0.0, self.completed_at - self.started_at)
        return None

    def compute_next_retry_delay(self) -> float:
        """Computes exponential backoff delay: initial_delay * (backoff_base ** retry_count)."""
        return self.initial_delay * (self.backoff_base ** self.retry_count)


@dataclass
class QueueStats:
    """Aggregated real-time metrics across all tracked jobs."""
    total: int = 0
    pending: int = 0
    running: int = 0
    success: int = 0
    failed: int = 0
    retrying: int = 0
    cancelled: int = 0
    active_workers: int = 0
    queue_depth: int = 0
