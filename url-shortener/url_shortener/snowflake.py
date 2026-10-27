"""
Twitter Snowflake 64-bit Distributed ID Generator and Base62 Encoding.

Bit Allocation:
- 1 bit  : Sign bit (reserved, 0)
- 41 bits: Millisecond timestamp since custom epoch (~69.7 years lifespan)
- 10 bits: Machine / Worker node ID (0 - 1023)
- 12 bits: Sequence counter (up to 4096 unique IDs per millisecond per node)
"""

from __future__ import annotations

import string
import threading
import time

BASE62_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase

# Custom epoch: 2024-01-01 00:00:00 UTC (1704067200000 ms)
CUSTOM_EPOCH_MS = 1704067200000

WORKER_ID_BITS = 10
SEQUENCE_BITS = 12

MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1   # 1023
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1     # 4095

WORKER_SHIFT = SEQUENCE_BITS
TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS


def encode_base62(num: int) -> str:
    """Converts a non-negative integer into a Base62 string."""
    if num == 0:
        return BASE62_ALPHABET[0]
    digits = []
    base = len(BASE62_ALPHABET)
    while num > 0:
        digits.append(BASE62_ALPHABET[num % base])
        num //= base
    return "".join(reversed(digits))


def decode_base62(code: str) -> int:
    """Decodes a Base62 string back into its original integer."""
    base = len(BASE62_ALPHABET)
    num = 0
    for char in code:
        idx = BASE62_ALPHABET.index(char)
        num = num * base + idx
    return num


class SnowflakeGenerator:
    """
    Thread-safe 64-bit Snowflake ID Generator.
    Guarantees k-ordered strictly unique IDs across distributed instances.
    """

    def __init__(self, worker_id: int = 1, epoch_ms: int = CUSTOM_EPOCH_MS):
        if not (0 <= worker_id <= MAX_WORKER_ID):
            raise ValueError(f"worker_id must be between 0 and {MAX_WORKER_ID}, got {worker_id}")
        self.worker_id = worker_id
        self.epoch_ms = epoch_ms
        self.last_timestamp = -1
        self.sequence = 0
        self._lock = threading.Lock()

    def _current_timestamp_ms(self) -> int:
        return int(time.time() * 1000)

    def _wait_next_millis(self, last_ts: int) -> int:
        ts = self._current_timestamp_ms()
        while ts <= last_ts:
            time.sleep(0.0001)
            ts = self._current_timestamp_ms()
        return ts

    def generate_id(self) -> int:
        """Generates a 64-bit unique integer ID."""
        with self._lock:
            ts = self._current_timestamp_ms()

            if ts < self.last_timestamp:
                # System clock drifted backwards
                drift = self.last_timestamp - ts
                if drift < 10:
                    ts = self._wait_next_millis(self.last_timestamp)
                else:
                    raise RuntimeError(f"Clock moved backwards by {drift}ms! Refusing to generate ID.")

            if ts == self.last_timestamp:
                self.sequence = (self.sequence + 1) & MAX_SEQUENCE
                if self.sequence == 0:
                    # Sequence exhausted for this millisecond: wait until next millisecond
                    ts = self._wait_next_millis(self.last_timestamp)
            else:
                self.sequence = 0

            self.last_timestamp = ts

            snowflake_id = (
                ((ts - self.epoch_ms) << TIMESTAMP_SHIFT)
                | (self.worker_id << WORKER_SHIFT)
                | self.sequence
            )
            return snowflake_id

    def generate_code(self) -> str:
        """Generates a Base62-encoded snowflake string suitable for short URLs."""
        return encode_base62(self.generate_id())


# Default global generator instance with worker_id = 1
default_snowflake = SnowflakeGenerator(worker_id=1)
