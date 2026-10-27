"""
In-process thread-safe background task queue with workers, scheduled delayed execution,
and exponential backoff retry policies.
"""

from __future__ import annotations

import heapq
import queue
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from task_queue.dlq import DeadLetterQueue
from task_queue.job import Job, JobStatus, QueueStats


class TaskQueue:
    """
    Manages an in-process pool of worker threads, job scheduling, and automatic retries.
    """

    def __init__(self, num_workers: int = 4):
        if num_workers <= 0:
            raise ValueError("num_workers must be at least 1.")

        self.num_workers = num_workers
        self._ready_queue: queue.Queue[Job] = queue.Queue()
        self._delayed_heap: List[tuple[float, int, Job]] = []
        self._delayed_lock = threading.Lock()
        self._heap_counter = 0

        # Dead Letter Queue for permanently failed/exhausted jobs
        self.dlq = DeadLetterQueue()

        # Registry for telemetry and status lookups
        self._registry: Dict[str, Job] = {}
        self._registry_lock = threading.Lock()

        self._running = False
        self._workers: List[threading.Thread] = []
        self._scheduler_thread: Optional[threading.Thread] = None
        self._active_workers_count = 0
        self._active_workers_lock = threading.Lock()

    def start(self) -> TaskQueue:
        """Starts worker threads and the delayed-job scheduler."""
        if self._running:
            return self

        self._running = True

        # Start delayed job dispatcher thread
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="task-queue-scheduler",
            daemon=True
        )
        self._scheduler_thread.start()

        # Start worker threads
        for i in range(self.num_workers):
            w = threading.Thread(
                target=self._worker_loop,
                name=f"task-queue-worker-{i+1}",
                daemon=True
            )
            w.start()
            self._workers.append(w)

        return self

    def stop(self, wait: bool = True, timeout: Optional[float] = 5.0) -> None:
        """
        Signals workers to stop.
        If wait=True, waits up to timeout seconds for running tasks to finish.
        """
        self._running = False

        if wait:
            # Drain workers
            for w in self._workers:
                if w.is_alive():
                    w.join(timeout=timeout)

            if self._scheduler_thread and self._scheduler_thread.is_alive():
                self._scheduler_thread.join(timeout=1.0)

        self._workers.clear()

    def enqueue(
        self,
        func: Callable[..., Any],
        *args: Any,
        name: str = "",
        max_retries: int = 3,
        initial_delay: float = 0.5,
        backoff_base: float = 2.0,
        delay_seconds: float = 0.0,
        **kwargs: Any
    ) -> Job:
        """
        Enqueues a function for background execution.
        """
        now = time.time()
        job = Job(
            func=func,
            args=args,
            kwargs=kwargs,
            name=name,
            max_retries=max_retries,
            initial_delay=initial_delay,
            backoff_base=backoff_base,
            scheduled_at=now + delay_seconds,
            created_at=now,
            status=JobStatus.PENDING
        )

        with self._registry_lock:
            self._registry[job.id] = job

        if delay_seconds > 0:
            with self._delayed_lock:
                self._heap_counter += 1
                heapq.heappush(self._delayed_heap, (job.scheduled_at, self._heap_counter, job))
        else:
            self._ready_queue.put(job)

        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Looks up a job by its unique ID."""
        with self._registry_lock:
            return self._registry.get(job_id)

    def get_all_jobs(self) -> List[Job]:
        """Returns snapshot of all tracked jobs ordered by creation timestamp."""
        with self._registry_lock:
            return sorted(self._registry.values(), key=lambda j: j.created_at)

    def stats(self) -> QueueStats:
        """Computes aggregate queue statistics."""
        with self._registry_lock:
            jobs = list(self._registry.values())

        with self._active_workers_lock:
            active_workers = self._active_workers_count

        s = QueueStats(
            total=len(jobs),
            active_workers=active_workers,
            queue_depth=self._ready_queue.qsize(),
            dead_letter=self.dlq.size()
        )
        for j in jobs:
            if j.status == JobStatus.PENDING:
                s.pending += 1
            elif j.status == JobStatus.RUNNING:
                s.running += 1
            elif j.status == JobStatus.SUCCESS:
                s.success += 1
            elif j.status == JobStatus.FAILED:
                s.failed += 1
            elif j.status == JobStatus.RETRYING:
                s.retrying += 1
            elif j.status == JobStatus.CANCELLED:
                s.cancelled += 1
        return s

    def wait_for_completion(self, poll_interval: float = 0.05, timeout: Optional[float] = None) -> bool:
        """
        Blocks until all enqueued and retrying jobs have reached a terminal state
        (SUCCESS, FAILED, or CANCELLED).
        """
        start = time.time()
        while True:
            st = self.stats()
            # If nothing is pending, running, or retrying, all jobs are finished
            if (st.pending + st.running + st.retrying) == 0 and self._ready_queue.empty():
                return True

            if timeout is not None and (time.time() - start) >= timeout:
                return False

            time.sleep(poll_interval)

    def _scheduler_loop(self) -> None:
        """Background thread checking the delayed heap and moving mature jobs to ready queue."""
        while self._running:
            now = time.time()
            to_ready: List[Job] = []

            with self._delayed_lock:
                while self._delayed_heap and self._delayed_heap[0][0] <= now:
                    _, _, job = heapq.heappop(self._delayed_heap)
                    to_ready.append(job)

            for job in to_ready:
                job.status = JobStatus.PENDING
                self._ready_queue.put(job)

            time.sleep(0.05)

    def _worker_loop(self) -> None:
        """Worker thread loop polling ready queue and executing jobs."""
        while self._running:
            try:
                job = self._ready_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if not self._running:
                # Re-queue or discard if stopping
                break

            with self._active_workers_lock:
                self._active_workers_count += 1

            self._execute_job(job)

            with self._active_workers_lock:
                self._active_workers_count = max(0, self._active_workers_count - 1)

            self._ready_queue.task_done()

    def _execute_job(self, job: Job) -> None:
        """Executes a single job with exception interception and backoff retries."""
        job.status = JobStatus.RUNNING
        job.started_at = time.time()

        try:
            result = job.func(*job.args, **job.kwargs)
            job.result = result
            job.status = JobStatus.SUCCESS
            job.error = None
            job.completed_at = time.time()
        except Exception as exc:
            job.error = str(exc)
            job.traceback = traceback.format_exc()

            # Check if retry quota remains
            if job.retry_count < job.max_retries:
                delay = job.compute_next_retry_delay()
                job.retry_count += 1
                job.scheduled_at = time.time() + delay
                job.status = JobStatus.RETRYING

                with self._delayed_lock:
                    self._heap_counter += 1
                    heapq.heappush(self._delayed_heap, (job.scheduled_at, self._heap_counter, job))
            else:
                job.status = JobStatus.FAILED
                job.completed_at = time.time()
                self.dlq.add(job)

    def re_enqueue(self, job: Job) -> None:
        """Re-enqueues an existing job (e.g. from the Dead Letter Queue)."""
        job.status = JobStatus.PENDING
        job.scheduled_at = time.time()
        with self._registry_lock:
            self._registry[job.id] = job
        self._ready_queue.put(job)

    def replay_dead_letter(self, job_id: str) -> Optional[Job]:
        """Replays a quarantined job from the Dead Letter Queue back into active execution."""
        return self.dlq.replay(job_id, self)
