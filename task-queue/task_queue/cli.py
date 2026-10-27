"""
Status CLI and interactive demonstration harness for task-queue.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

# Ensure package is on sys.path if invoked directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from task_queue.job import JobStatus, QueueStats
from task_queue.queue import TaskQueue


def format_status_table(q: TaskQueue) -> str:
    """Formats queue stats and tracked jobs into a terminal table."""
    s = q.stats()
    lines = [
        "==========================================================================",
        "                      TASK QUEUE STATUS DASHBOARD                         ",
        "==========================================================================",
        f"Active Workers: {s.active_workers}/{q.num_workers} | Ready Queue Depth: {s.queue_depth}",
        f"Total Jobs: {s.total} | Pending: {s.pending} | Running: {s.running} | Success: {s.success} | Retrying: {s.retrying} | Failed: {s.failed}",
        "--------------------------------------------------------------------------",
        f"{'Job ID':<10} | {'Name':<22} | {'Status':<10} | {'Retries':<8} | {'Duration':<10} | {'Result / Error'}",
        "--------------------------------------------------------------------------"
    ]

    for job in q.get_all_jobs():
        dur_str = f"{job.duration:.2f}s" if job.duration is not None else "-"
        retries_str = f"{job.retry_count}/{job.max_retries}"

        if job.status == JobStatus.SUCCESS:
            detail = f"{job.result}"
        elif job.status in (JobStatus.FAILED, JobStatus.RETRYING):
            detail = f"ERR: {job.error}"
        else:
            detail = "..."

        # Truncate detail for clean table display
        if len(detail) > 28:
            detail = detail[:25] + "..."

        lines.append(f"{job.id:<10} | {job.name[:22]:<22} | {job.status.value:<10} | {retries_str:<8} | {dur_str:<10} | {detail}")

    lines.append("==========================================================================")
    return "\n".join(lines)


# Sample tasks for demonstration
_attempt_tracker = {}


def flakey_network_call(url: str, fail_times: int = 1):
    """Simulates an external API call that fails fail_times before succeeding."""
    _attempt_tracker[url] = _attempt_tracker.get(url, 0) + 1
    if _attempt_tracker[url] <= fail_times:
        raise ConnectionResetError(f"Connection reset by peer: {url} (attempt {_attempt_tracker[url]})")
    return f"200 OK from {url}"


def quick_math(a: int, b: int) -> int:
    time.sleep(0.05)
    return a * b


def fatal_job():
    time.sleep(0.05)
    raise ValueError("Unrecoverable database corruption in record 99")


def run_demo():
    print("[*] Starting TaskQueue with 3 worker threads...")
    q = TaskQueue(num_workers=3).start()

    print("[*] Enqueueing sample jobs...")
    q.enqueue(quick_math, 6, 7, name="multiply(6,7)")
    q.enqueue(quick_math, 12, 12, name="multiply(12,12)")
    q.enqueue(flakey_network_call, "https://api.example.com/checkout", fail_times=2, name="payment_api", initial_delay=0.3, backoff_base=1.5)
    q.enqueue(fatal_job, name="corrupt_batch_job", max_retries=2, initial_delay=0.2)
    q.enqueue(quick_math, 100, 5, name="delayed_calc", delay_seconds=0.6)

    print("[*] Monitoring queue progress in real time:\n")
    start = time.time()
    while time.time() - start < 3.5:
        print("\033[H\033[J", end="")  # Clear terminal screen
        print(format_status_table(q))
        st = q.stats()
        if (st.pending + st.running + st.retrying) == 0:
            break
        time.sleep(0.2)

    q.wait_for_completion(timeout=5.0)
    print("\n[+] Final Completed State:")
    print(format_status_table(q))
    q.stop()


def main():
    parser = argparse.ArgumentParser(description="Task Queue Status CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("demo", help="Run interactive task queue demonstration")
    subparsers.add_parser("stats", help="Inspect current task queue status")

    args = parser.parse_args()
    if args.command == "demo" or args.command is None:
        run_demo()
    else:
        print("Please run with 'demo' to see the live queue execution.")


if __name__ == "__main__":
    main()
