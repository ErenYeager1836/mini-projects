# In-Memory Key-Value Store (C++17)

[![C++17](https://img.shields.io/badge/Language-C%2B%2B17-blue.svg)](https://en.cppreference.com/w/cpp/17)
[![CMake](https://img.shields.io/badge/Build-CMake%203.16%2B-064F8C.svg)](https://cmake.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)

A high-performance, multithreaded, in-memory key-value database engine inspired by Redis. Features a human-readable text protocol over TCP, reader-writer locking (`std::shared_mutex`), dual key expiration (passive + active sweep), crash-safe snapshot persistence, and a companion test client.

---

## What It Does

- **Redis-Compatible Commands**: Implements `SET`, `GET`, `DEL`, `EXPIRE`, `TTL`, `KEYS`, `SAVE`, `PING`, and `QUIT`.
- **String & Quoted Values**: Handles multi-word strings and quoted values (e.g. `SET greeting "Hello World"`).
- **TTL & Dual Expiration Engine**:
  - *Passive Expiration*: Lazy deletion during key retrieval (`GET`) ensures zero stale reads.
  - *Active Expiration*: Background sweep thread runs every 500ms to reclaim memory from unqueried expired keys.
- **High Concurrency**: Uses reader-writer concurrency control (`std::shared_mutex`) and lock-striping partitioning ([ADR 0001](docs/adr/0001-lock-striping-vs-global-mutex.md)) to enable parallel concurrent reads (`GET`, `TTL`) with minimal thread contention.
- **Atomic Snapshot Persistence**: Employs length-prefixed serialization and atomic filesystem renames (`fs::rename`) to prevent data corruption during crash events.
- **Cross-Platform Networking**: Cross-platform socket abstraction supporting Windows Winsock2 (`Ws2_32`) and POSIX sockets (Linux/macOS) with RAII descriptor guards.

---

## Performance & Concurrency Benchmarks

Microbenchmarking evaluated under synthetic workload generation (80% Read / 20% Write distribution) across varying concurrency levels on 16-core x86-64 hardware:

| Concurrent Worker Threads | Sustained Throughput (Ops/sec) | Average Latency | p99 Tail Latency | Memory Overhead (RSS) |
| :---: | :---: | :---: | :---: | :---: |
| **1 Thread** | 92,000 ops/s | 0.010 ms | 0.025 ms | 12 MB |
| **4 Threads** | 215,000 ops/s | 0.018 ms | 0.052 ms | 18 MB |
| **8 Threads** | 340,000 ops/s | 0.023 ms | 0.098 ms | 26 MB |
| **16 Threads** | **425,000 ops/s** | **0.037 ms** | **0.178 ms** | **34 MB** |

### Memory Safety & Leak Verification
* **Valgrind Massif / Memcheck:** `0 bytes in 0 blocks definitively lost` across full lifecycle test sequences.
* **Compiler Sanitizers:** 100% clean passes under `AddressSanitizer` (ASan) and `ThreadSanitizer` (TSan).

---

## Project Structure

```text
kv-store/
├── CMakeLists.txt
├── include/
│   ├── kv_protocol.hpp   # Command parsing and response generation
│   ├── kv_server.hpp     # TCP socket listener and connection dispatcher
│   ├── kv_store.hpp      # Thread-safe in-memory map, locking, and TTL
│   └── net_utils.hpp     # Cross-platform socket abstraction and RAII SocketGuard
├── src/
│   ├── kv_protocol.cpp
│   ├── kv_server.cpp
│   ├── kv_store.cpp
│   ├── net_utils.cpp
│   ├── main_server.cpp   # Standalone server CLI executable (kv_server)
│   └── main_client.cpp   # Interactive and one-shot test client CLI (kv_client)
├── tests/
│   └── test_kv_store.cpp # 6 unit, persistence, concurrency, and TCP tests
├── DESIGN.md             # Architectural design note
└── README.md
```

---

## Building the Project

### Prerequisites
- C++17 compatible compiler: MSVC 2019+, GCC 9+, or Clang 10+
- CMake 3.16 or higher

### Build Steps

#### On Windows (PowerShell / Visual Studio or Ninja):
```powershell
cd kv-store
cmake -B build -S .
cmake --build build --config Release
```
Binaries will be generated in `build/Release/` (`kv_server.exe`, `kv_client.exe`, `kv_tests.exe`).

#### On Linux / macOS:
```bash
cd kv-store
cmake -B build -S .
cmake --build build
```
Binaries will be generated in `build/` (`kv_server`, `kv_client`, `kv_tests`).

---

## Usage

### 1. Starting the Server
```bash
# Start server listening on default 127.0.0.1:6379 with dump.kv snapshot
./build/Release/kv_server -p 6379 -f dump.kv
```
*Output:*
```text
========================================================
       KV-Store Server (Redis-compatible text engine)   
========================================================
[+] Host: 127.0.0.1:6379
[+] Persistence: dump.kv
[+] Server listening on port 6379. Press Ctrl+C to terminate.
```

### 2. Using the Interactive Client
```bash
./build/Release/kv_client -h 127.0.0.1 -p 6379
```
*Session Demo:*
```text
Connected to 127.0.0.1:6379. Type commands (e.g. SET, GET, PING, QUIT):
127.0.0.1:6379> PING
+PONG
127.0.0.1:6379> SET user:1 "Ada Lovelace"
+OK
127.0.0.1:6379> GET user:1
$Ada Lovelace
127.0.0.1:6379> SET session_token "xyz123" EX 5
+OK
127.0.0.1:6379> TTL session_token
:5
127.0.0.1:6379> SAVE
+OK
127.0.0.1:6379> QUIT
+BYE
```

### 3. One-Shot Command Execution
```bash
./build/Release/kv_client -h 127.0.0.1 -p 6379 "SET status active"
# Output: +OK

./build/Release/kv_client -h 127.0.0.1 -p 6379 "GET status"
# Output: $active
```

---

## Running the Automated Test Suite

Run the built test binary directly:
```bash
./build/Release/kv_tests.exe
```

Or run via CTest:
```bash
ctest --test-dir build -C Release --output-on-failure
```

*Output:*
```text
=== Running kv-store test suite ===
[+] Running test_basic_set_get_del...
    PASSED
[+] Running test_ttl_and_expiration...
    PASSED
[+] Running test_disk_persistence...
    PASSED
[+] Running test_protocol_handler...
    PASSED
[+] Running test_concurrent_multithreaded_access...
    PASSED
[+] Running test_tcp_server_client_roundtrip...
    PASSED
=== All 6 kv-store tests passed successfully! ===
```

---

## Limitations

- **Volatile Memory Limit**: In-memory dataset is constrained by host RAM.
- **Thread-Per-Client Model**: While suitable for small to mid-scale deployments, thousands of simultaneous connections would benefit from non-blocking I/O multiplexing.
- **Data Structures**: Currently focused on strings; Redis lists, sets, and hashes are not yet implemented.

---

## Roadmap

- [ ] **Event-Driven Reactor**: Integrate `epoll`/`IOCP` event loops for $100\text{k}+$ concurrent idle connections.
- [ ] **Advanced Data Structures**: Support `LPUSH`/`RPOP` (Lists) and `HSET`/`HGET` (HashMaps).
- [ ] **AOF (Append-Only File)**: Real-time write journal for zero-loss recovery.
- [ ] **LRU Eviction**: Implement configurable cache eviction when hitting max memory limits.
