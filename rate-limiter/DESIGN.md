# Design Note: Rate Limiting Algorithms & Architecture

## 1. Overview & Objective

Rate limiting protects APIs, backend databases, and downstream services from denial-of-service (DoS), resource exhaustion, credential stuffing, and noisy-neighbor tenant starvation.

This library implements two foundational, production-grade algorithms:
1. **Token Bucket**: Optimized for bursty traffic with continuous token refills.
2. **Sliding Window Log**: Optimized for strict, boundary-accurate rate enforcement without window-edge spikes.

```text
[ Incoming Request ]
         │
         ▼
 [ @rate_limit Decorator ] ──(resolve key: user_id / IP)
         │
         ├───> [ Token Bucket ]   ──> tokens >= cost ? (Allow & Deduct) : (Reject + Retry-After)
         │
         └───> [ Sliding Window ] ──> count(now - W to now) < max ? (Log timestamp & Allow) : (Reject)
```

---

## 2. Algorithm Comparison & Trade-Offs

| Algorithm | Memory per Key | Time Complexity | Burst Tolerance | Edge-Boundary Spikes? | Ideal Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Token Bucket** | **$O(1)$** (16 bytes) | **$O(1)$** | **Yes** (up to capacity) | No | High-throughput APIs, webhooks, bursty user traffic |
| **Sliding Window Log** | **$O(N)$** ($N$ timestamps) | **$O(N)$** (amortized $O(1)$) | **No** (strictly capped) | **No** (smooth rolling window) | Strict security endpoints, payment APIs, login throttling |
| **Fixed Window Counter** | $O(1)$ | $O(1)$ | No | **Yes** (up to 2x burst across window boundaries) | Simple counters where edge spikes are acceptable |
| **Leaky Bucket** | $O(1)$ or $O(N)$ queue | $O(1)$ | No (smooth output) | No | Traffic shaping to prevent downstream spikes |

---

## 3. Mathematical Foundations

### A. Token Bucket (Continuous Refill)
Instead of running a background timer to add tokens every second, tokens are calculated lazily on each request:
$$\Delta t = \text{now} - \text{last\_refill}$$
$$\text{tokens}_{\text{current}} = \min(\text{capacity}, \text{tokens}_{\text{prev}} + \Delta t \times \text{refill\_rate})$$

If $\text{tokens}_{\text{current}} \ge \text{cost}$:
$$\text{tokens}_{\text{new}} = \text{tokens}_{\text{current}} - \text{cost} \quad (\text{Allow})$$
Else:
$$\text{retry\_after} = \frac{\text{cost} - \text{tokens}_{\text{current}}}{\text{refill\_rate}} \quad (\text{Reject})$$

**Advantage**: Requires only two floats (`tokens`, `last_refill`) in memory, achieving over **600,000 ops/second** with $1.5\,\mu\text{s}$ latency.

### B. Sliding Window Log (Rolling Timestamp Queue)
Maintains a double-ended queue (`collections.deque`) of recent request timestamps:
1. Let $W$ be the window size (in seconds) and $M$ be maximum allowable requests.
2. Evict expired entries:
   $$\text{popleft while } t \le (\text{now} - W)$$
3. If $\text{len}(\text{queue}) + \text{cost} \le M$:
   $$\text{append}(\text{now}) \quad (\text{Allow})$$
4. Else:
   $$\text{retry\_after} = \text{queue}[0] + W - \text{now} \quad (\text{Reject})$$

**Advantage**: Unlike Fixed Window, an attacker cannot send $M$ requests at 00:59 and another $M$ requests at 01:00 to achieve $2M$ within a 2-second span.

---

## 4. Concurrency & Thread-Safety

- Both algorithms wrap mutations in a `threading.Lock`.
- For multi-tenant applications with thousands of active users, lock contention can be avoided by partitioning locks per key or using a striped lock table (`hash(key) % N_LOCKS`).

---

## 5. Scaling to Distributed Architecture (Redis)

To deploy across multiple worker processes or Kubernetes pods:
- **Distributed Token Bucket**: Implemented in Redis using Lua scripts (`EVALSHA`) to atomize token updates and ensure single-roundtrip execution without distributed deadlocks.
- **Distributed Sliding Window**: Implemented using Redis Sorted Sets (`ZADD`, `ZREMRANGEBYSCORE`, `ZCARD`, `EXPIRE`).
