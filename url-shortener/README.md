# URL Shortener (FastAPI + SQLite)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite%20WAL-003B57.svg)](https://www.sqlite.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)

A high-performance, production-ready URL shortener service featuring Base62 short code generation, custom aliases, time-to-live (TTL) expiration, HTTP 307 temporary redirects, and click analytics tracking.

---

## What It Does

- **Short URL Creation**: Accepts long destination URLs and returns a 6-character Base62 code (`62^6 ≈ 56.8B` combinations).
- **Custom Vanity Aliases**: Supports user-defined custom short codes (`3-30` alphanumeric characters, `-`, `_`).
- **Configurable Expiry (TTL)**: Optional time-to-live policy in seconds; expired codes return `HTTP 410 Gone`.
- **Accurate Click Telemetry**: Tracks click count, request timestamps (UTC), User-Agent, and Referer headers without client-side caching (`HTTP 307`).
- **Input Validation & Security Guard**: Blocks dangerous schemes (`javascript:`, `file:`, `data:`) and enforces strict HTTP/HTTPS protocol validation via Pydantic.
- **Concurrent SQLite Storage**: Built on SQLite with Write-Ahead Logging (`WAL`) mode enabled for concurrent reader performance.

---

## Project Structure

```text
url-shortener/
├── url_shortener/
│   ├── __init__.py
│   ├── app.py             # FastAPI application and route handlers
│   ├── database.py        # SQLite database connection, WAL configuration, and SQL queries
│   ├── models.py          # Pydantic validation schemas
│   └── shortener.py       # Base62 cryptographically secure code generation
├── tests/
│   ├── __init__.py
│   └── test_shortener.py  # 9 comprehensive unit and integration tests
├── DESIGN.md              # Architectural design note and trade-offs
├── pyproject.toml         # Packaging configuration and pytest setup
└── README.md
```

---

## Installation & Setup

### 1. Prerequisites
- Python 3.10 or higher
- `pip` package manager

### 2. Install Dependencies
From the repository root or project directory:
```bash
pip install fastapi uvicorn httpx pytest
```

---

## Running the Server

Start the local development server with auto-reload:
```bash
uvicorn url_shortener.app:app --host 127.0.0.1 --port 8000 --reload
```

Interactive API documentation (Swagger UI) is automatically available at:
`http://127.0.0.1:8000/docs`

---

## API Usage & Endpoints

### 1. Shorten a URL (Auto-Generated Code)
```bash
curl -X POST http://127.0.0.1:8000/api/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com/ErenYeager1836"}'
```
**Response (`201 Created`):**
```json
{
  "short_code": "k8X9bQ",
  "short_url": "http://127.0.0.1:8000/k8X9bQ",
  "target_url": "https://www.github.com/ErenYeager1836",
  "created_at": "2026-10-27T03:45:00.123456+00:00",
  "expires_at": null
}
```

### 2. Shorten with Custom Alias and TTL Expiry
```bash
curl -X POST http://127.0.0.1:8000/api/shorten \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://fastapi.tiangolo.com",
    "custom_code": "fastapi-docs",
    "ttl_seconds": 86400
  }'
```
**Response (`201 Created`):**
```json
{
  "short_code": "fastapi-docs",
  "short_url": "http://127.0.0.1:8000/fastapi-docs",
  "target_url": "https://fastapi.tiangolo.com",
  "created_at": "2026-10-27T03:45:00.123456+00:00",
  "expires_at": "2026-10-28T03:45:00.123456+00:00"
}
```

### 3. Redirection
Accessing the short code performs an immediate `HTTP 307 Temporary Redirect`:
```bash
curl -i http://127.0.0.1:8000/fastapi-docs
```
**Response:**
```http
HTTP/1.1 307 Temporary Redirect
location: https://fastapi.tiangolo.com
```

### 4. Click Analytics
```bash
curl http://127.0.0.1:8000/api/analytics/fastapi-docs
```
**Response (`200 OK`):**
```json
{
  "short_code": "fastapi-docs",
  "target_url": "https://fastapi.tiangolo.com",
  "total_clicks": 1,
  "created_at": "2026-10-27T03:45:00.123456+00:00",
  "expires_at": "2026-10-28T03:45:00.123456+00:00",
  "is_expired": false,
  "recent_clicks": [
    {
      "clicked_at": "2026-10-27T03:46:12.654321+00:00",
      "user_agent": "curl/8.4.0",
      "referer": null
    }
  ]
}
```

---

## Running the Automated Tests

Execute the complete test suite with `pytest`:
```bash
pytest url-shortener/tests -v
```

Output:
```text
url-shortener/tests/test_shortener.py::test_health_check PASSED          [ 11%]
url-shortener/tests/test_shortener.py::test_shorten_url_auto_generated_code PASSED [ 22%]
url-shortener/tests/test_shortener.py::test_shorten_url_with_custom_code PASSED [ 33%]
url-shortener/tests/test_shortener.py::test_shorten_duplicate_custom_code_returns_409 PASSED [ 44%]
url-shortener/tests/test_shortener.py::test_redirect_and_click_tracking PASSED [ 55%]
url-shortener/tests/test_shortener.py::test_redirect_nonexistent_returns_404 PASSED [ 66%]
url-shortener/tests/test_shortener.py::test_redirect_expired_url_returns_410 PASSED [ 77%]
url-shortener/tests/test_shortener.py::test_input_validation_invalid_schemes PASSED [ 88%]
url-shortener/tests/test_shortener.py::test_input_validation_invalid_custom_code PASSED [100%]

======================== 9 passed in 0.79s =========================
```

---

## Limitations

- **Single Node Storage**: SQLite is embedded within a single server instance. While WAL mode enables fast concurrent reads, concurrent writes are serialized.
- **Passive Expiry**: Expired records are flagged and blocked upon retrieval, but are not deleted from disk unless a background purge job is scheduled.
- **Local Telemetry**: GeoIP lookup requires external city/country databases (e.g. MaxMind GeoLite2).

---

## Roadmap

- [ ] **Redis Caching Tier**: Cache active URL mappings in Redis for sub-millisecond retrieval.
- [ ] **QR Code Generation**: Return Base64 or PNG QR codes for mobile users via `/api/qr/{code}`.
- [ ] **GeoIP & Device Telemetry**: Parse User-Agent strings into browser/OS families and resolve client IPs to countries.
- [ ] **Distributed Key Generation**: Implement a centralized key generator (Snowflake/K-Sortable) for horizontal multi-region clusters.
