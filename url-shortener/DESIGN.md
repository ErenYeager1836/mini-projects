# Design Note: URL Shortener Architecture

## 1. System Overview

The **URL Shortener** provides a high-throughput, low-latency service for mapping long target URLs into compact Base62 identifiers, servicing HTTP 307 temporary redirects, tracking click telemetry, and enforcing time-to-live (TTL) expiration policies.

```text
[ Client ]
    │
    ├─ POST /api/shorten ────────> [ Input Validation ] ──> [ Base62 Generator ] ──> [ SQLite: urls ]
    │
    ├─ GET /{short_code} ────────> [ Expiry Check ] ──────> [ Log Telemetry ] ────> 307 Redirect (Location Header)
    │                                                                                   │
    └─ GET /api/analytics/{code} ─> [ Aggregate Query ] ──> [ JSON Telemetry ] <────────┘
```

---

## 2. Key Technical Decisions & Trade-Offs

### A. Base62 Short Code vs. Sequential Integer vs. UUID
- **Sequential IDs (Auto-Increment)**: Leaks business metrics (e.g. total volume of links created) and allows attackers to crawl/scrape every URL sequentially.
- **UUIDv4**: Too long (36 characters), defeating the primary purpose of a "short" URL.
- **Random Base62 (Chosen)**:
  - Alphabet: `[0-9a-zA-Z]` (62 symbols).
  - Length: 6 characters yields $62^6 = 56,800,235,584$ (~56.8 billion) permutations.
  - Generates compact, non-sequential codes with cryptographically secure randomness (`secrets.choice`).
  - Employs a bounded retry loop (5 attempts) to handle the negligible collision probability before falling back.

### B. Storage Engine & Indexing
- **Database**: SQLite with Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and `PRAGMA foreign_keys = ON;`.
  - WAL mode separates read and write operations, enabling concurrent readers while a write transaction is committed.
- **Indexes**:
  - `UNIQUE INDEX idx_urls_short_code ON urls(short_code)`: Ensures $O(1)$ lookup time for redirection and enforces uniqueness at the database engine level.
  - `INDEX idx_clicks_url_id ON clicks(url_id)`: Accelerates analytics queries and foreign key lookups without full table scans.

### C. Redirection Status Code: HTTP 307 vs. HTTP 301
- **HTTP 301 (Permanent Redirect)**: Browsers aggressively cache 301 responses locally. If an analytics tracker or expiry check is needed, the browser bypasses the server on subsequent visits.
- **HTTP 307 (Temporary Redirect - Chosen)**: Instructs the browser to repeat the request to the target destination without caching the redirect indefinitely. This ensures that every single click hits the server, preserving accurate analytics and instant expiry enforcement.

### D. Expiration Strategy (Passive vs. Active)
- **Passive Checking (Chosen)**: During lookup (`GET /{short_code}`), the stored `expires_at` timestamp is compared against `datetime.now(timezone.utc)`. If expired, the server returns `HTTP 410 Gone`. This eliminates the need for background cron jobs or active daemon threads for smaller deployments.
- **Active Cleanup (Production Scale)**: For multi-million record deployments, a periodic purge query (`DELETE FROM urls WHERE expires_at < NOW()`) cleans up abandoned records to reclaim storage space.

### E. Security & Input Sanitization
- **Scheme Whitelisting**: Restricts inputs strictly to `http://` and `https://`. Prevents Cross-Site Scripting (XSS) or local file disclosure through malicious schemes such as `javascript:`, `data:`, or `file:`.
- **Character Filtering**: Custom aliases are strictly constrained by regex `^[a-zA-Z0-9_-]{3,30}$` to prevent path traversal or URL manipulation attacks.

---

## 3. Scaling to High Availability & Distributed Architecture

To scale this service to thousands of requests per second across multiple regions:
1. **Caching Layer**: Place Redis or Memcached in front of the database. Active short codes are cached with their destination URL; lookups resolve in under 1ms.
2. **Distributed ID Generation**: Replace random generation with Twitter Snowflake or a centralized Zookeeper/Etcd token range allocator (e.g. worker node 1 gets IDs $1 \times 10^6$ to $2 \times 10^6$) to prevent distributed collisions without locking.
3. **Database Migration**: Migrate SQLite to PostgreSQL or CockroachDB with horizontal read replicas.
