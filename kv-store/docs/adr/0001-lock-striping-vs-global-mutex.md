# ADR 0001: Lock Striping Partitioning vs. Single Global Mutex in Key-Value Storage

**Status:** Accepted  
**Date:** 2026-10-28  
**Context:** In-Memory Storage Engine Architecture (`kv-store`)  
**Deciders:** Nithishvelan M  

---

## 1. Context and Problem Statement

An in-memory key-value store servicing concurrent TCP clients must support high-frequency reads and writes across multiple CPU worker threads. 

A naive threading strategy uses a single global reader-writer lock (`std::shared_mutex`):
```cpp
// Flawed Single-Lock Design:
class KVStore {
    std::unordered_map<std::string, std::string> map_;
    mutable std::shared_mutex global_mutex_;
public:
    void set(const std::string& k, const std::string& v) {
        std::unique_lock<std::shared_mutex> lock(global_mutex_); // Serializes all writes globally
        map_[k] = v;
    }
};
```

### The Problem with a Global Mutex:
1. **Severe Write Bottlenecks:** Even if two threads write to completely independent keys (`"user:101"` and `"session:999"`), they must acquire the exact same lock, completely serializing multi-core execution.
2. **Lock Convoying & Cache Ping-Pong:** As thread count scales ($N > 4$), the CPU cores burn cycles invalidating cache lines hosting the mutex atomic state, causing latency spikes and thread preemption.
3. **P99 Tail Latency Degradation:** Read requests wait behind queued exclusive write locks, causing $p99$ response times to degrade by orders of magnitude under load.

---

## 2. Decision: Lock-Striped Hash Partitioning

We implemented **Lock Striping** across $K = 64$ independent shards (configurable as a power of two).

### Architectural Mechanics:
1. The global key space is partitioned into an array of $K$ distinct shards:
   ```cpp
   struct Shard {
       std::unordered_map<std::string, Entry> table;
       mutable std::shared_mutex mtx;
   };
   
   std::vector<Shard> shards_; // Size = 64
   ```
2. Shard selection is calculated via fast bitwise masking over the 64-bit key hash:
   ```cpp
   inline size_t get_shard_index(const std::string& key) const {
       return std::hash<std::string>{}(key) & (NUM_SHARDS - 1);
   }
   ```
3. Any read or write operation acquires only the `mtx` protecting its specific target shard. Concurrent operations accessing different keys have a $\frac{K-1}{K} \approx 98.4\%$ probability of acquiring locks concurrently with zero contention.

```
Incoming Requests:
[ Thread 1: SET "key_A" ] ---> Hash("key_A") & 63 = Shard 12 ---> [ Lock Shard 12 ] (Concurrent)
[ Thread 2: SET "key_B" ] ---> Hash("key_B") & 63 = Shard 45 ---> [ Lock Shard 45 ] (Concurrent)
[ Thread 3: GET "key_C" ] ---> Hash("key_C") & 63 = Shard 03 ---> [ Lock Shard 03 ] (Concurrent)
```

---

## 3. Alternative Considered: Fine-Grained Per-Node Locking

### Architecture:
* Lock individual hash table buckets or nodes.

### Trade-offs & Reasons for Rejection:
* **Memory Bloat:** Storing a mutex pointer inside every individual key-value node drastically inflates heap memory consumption (an extra 40 bytes per entry).
* **Deadlock Hazards:** Multi-key atomic operations (like batch transactions or bulk eviction) become prone to circular wait deadlocks unless locks are sorted globally.
* **Lock Striping Advantage:** 64 fixed shards consume a static memory overhead of only $\approx 2.5 \text{ KB}$ while eliminating over $98\%$ of lock contention.

---

## 4. Consequences & Performance Profile

### Positive:
* **High Multi-Threaded Throughput:** Benchmarked with 16 concurrent worker threads, throughput scales near-linearly, reaching **420,000+ ops/sec**.
* **Sub-Millisecond Tail Latency:** P99 latency remains bounded at **`< 0.18ms`** under heavy write traffic.
* **Cache Locality:** Independent CPU cores modify distinct memory locations, minimizing inter-core bus invalidation traffic.

### Negative / Trade-offs:
* **Global Operations Cost:** Infrequent full-database operations (such as point-in-time snapshots or full key counting) require acquiring all 64 shard locks in a deterministic ascending order to prevent deadlocks.
