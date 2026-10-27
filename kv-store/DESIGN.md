# Design Note: In-Memory Key-Value Store (C++17)

## 1. System Architecture

The **KV-Store** is a multithreaded, in-memory key-value database engine inspired by Redis. It features a text-based TCP protocol, reader-writer locking, dual expiration mechanisms (passive and active), and snapshot persistence to disk.

```text
[ Client 1 (CLI) ]       [ Client 2 (App) ]       [ Background Sweep Thread ]
         │                        │                             │
         └───────────┬────────────┘                             │
                     ▼                                          │
       [ KVServer (TCP Listener) ]                              │
                     │                                          │
                     ▼                                          │
         [ ProtocolHandler Parser ]                             │
                     │                                          │
                     ▼                                          ▼
     ┌───────────────────────────────────────────────────────────────┐
     │  KVStore: std::unordered_map<string, Entry>                   │
     │  Synchronization: std::shared_mutex (RW Lock)                │
     │  - Read: std::shared_lock (Concurrent GET/TTL/KEYS)           │
     │  - Write: std::unique_lock (Exclusive SET/DEL/EXPIRE/SAVE)   │
     └───────────────────────────────┬───────────────────────────────┘
                                     │
                                     ▼ (SAVE / LOAD)
                         [ Atomic Snapshot File ]
                         (dump.kv.tmp -> dump.kv)
```

---

## 2. Protocol Specification

The engine communicates over standard TCP using a text-based protocol compatible with `nc`, `telnet`, or the custom `kv_client` binary:

| Command | Arguments | Success Response | Error Response | Description |
| :--- | :--- | :--- | :--- | :--- |
| **`PING`** | `[message]` | `+PONG\r\n` or `+<msg>\r\n` | - | Liveness health check |
| **`SET`** | `<key> <val> [EX <secs>]` | `+OK\r\n` | `-ERR ...\r\n` | Sets key to value with optional TTL |
| **`GET`** | `<key>` | `$<value>\r\n` | `NIL\r\n` | Retrieves value or NIL if absent/expired |
| **`DEL`** | `<key>` | `:1\r\n` | `:0\r\n` | Deletes key; returns count of removed keys |
| **`EXPIRE`** | `<key> <seconds>` | `:1\r\n` | `:0\r\n` | Sets TTL in seconds on existing key |
| **`TTL`** | `<key>` | `:<seconds>\r\n` | `:-1\r\n` (no TTL), `:-2\r\n` (absent) | Returns remaining seconds until expiration |
| **`KEYS`** | - | `*<count>\r\n$<len>\r\n<key>\r\n...` | `*0\r\n` | Lists all non-expired keys |
| **`SAVE`** | - | `+OK\r\n` | `-ERR ...\r\n` | Synchronously flushes in-memory snapshot to disk |
| **`QUIT`** | - | `+BYE\r\n` | - | Closes the client TCP connection |

---

## 3. Key Technical Decisions & Trade-Offs

### A. Reader-Writer Lock (`std::shared_mutex`)
- In caching and key-value workloads, read operations (`GET`, `TTL`) typically outnumber writes (`SET`, `DEL`) by 10:1 or more.
- Using a standard `std::mutex` serializes all lookups, causing CPU contention.
- `std::shared_mutex` allows multiple reader threads to inspect the map simultaneously via `std::shared_lock`, only acquiring an exclusive `std::unique_lock` during mutations.

### B. Dual Key Expiration Architecture
1. **Passive Expiration (Lazy)**:
   - Evaluated during `get()` and `ttl()`.
   - If an entry's `expires_at` is earlier than `std::chrono::steady_clock::now()`, the key is immediately erased from the map and `NIL` is returned.
   - Prevents serving stale data without requiring synchronous scans.
2. **Active Expiration (Background Sweep)**:
   - A dedicated daemon thread runs every 500ms calling `cleanup_expired()`.
   - Iterates through the table and purges keys that have expired but have not been queried, preventing memory leaks from abandoned keys.

### C. Atomic Snapshot Persistence
- Snapshot writing creates a temporary sibling file (`<target>.tmp`) using length-prefixed encoding:
  ```text
  KVSTORE_V1
  <entry_count>
  <key_len> <val_len> <ttl_secs>
  <key>
  <value>
  ```
- Once the dump completes, `std::filesystem::rename` replaces the existing snapshot file atomically.
- This guarantees that a sudden crash or power loss during `SAVE` leaves the previous valid snapshot intact.

---

## 4. Production Roadmap & High-Scale Enhancements

1. **Event-Driven I/O (epoll / IOCP / kqueue)**: Replace thread-per-client with non-blocking event multiplexing to handle 50,000+ idle concurrent connections.
2. **Memory Eviction Policies**: Implement LRU (Least Recently Used) or LFU (Least Frequently Used) eviction when maximum memory limits (`maxmemory`) are reached.
3. **Append-Only File (AOF)**: Add a real-time write-ahead append log with fsync policies (`always`, `everysec`) for zero data loss durability.
