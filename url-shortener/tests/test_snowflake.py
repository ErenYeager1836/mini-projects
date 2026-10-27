"""
Unit tests for Twitter Snowflake 64-bit ID generator and Base62 encoding.
"""

from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient

from url_shortener.app import create_app
from url_shortener.database import Database
from url_shortener.snowflake import (
    SnowflakeGenerator,
    encode_base62,
    decode_base62,
    default_snowflake,
)


def test_base62_encoding_decoding_roundtrip():
    """Verify lossless round-trip Base62 encoding and decoding."""
    test_values = [0, 1, 61, 62, 1000, 123456789, 2**63 - 1]
    for val in test_values:
        encoded = encode_base62(val)
        decoded = decode_base62(encoded)
        assert decoded == val
        assert isinstance(encoded, str)
        assert len(encoded) > 0


def test_snowflake_strictly_increasing():
    """Verify that consecutive snowflake IDs are strictly monotonically increasing."""
    gen = SnowflakeGenerator(worker_id=5)
    ids = [gen.generate_id() for _ in range(1000)]
    for i in range(len(ids) - 1):
        assert ids[i] < ids[i + 1]


def test_snowflake_multithreaded_uniqueness():
    """Verify thread safety and zero ID collisions across multiple concurrent threads."""
    gen = SnowflakeGenerator(worker_id=10)
    total_ids = 5000

    def generate_batch():
        return [gen.generate_id() for _ in range(500)]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(generate_batch) for _ in range(10)]
        results = []
        for f in futures:
            results.extend(f.result())

    assert len(results) == total_ids
    assert len(set(results)) == total_ids, "Collision detected in multithreaded snowflake generation!"


def test_snowflake_api_integration(tmp_path):
    """Verify that url-shortener API generates valid snowflake short codes when requested."""
    db_file = str(tmp_path / "test_snowflake.db")
    db = Database(db_file)
    app = create_app(db)
    client = TestClient(app)

    # 1. Shorten with snowflake generator
    resp = client.post(
        "/api/shorten",
        json={"url": "https://distributed-systems.org/consensus", "use_snowflake": True}
    )
    assert resp.status_code == 201
    data = resp.json()
    code = data["short_code"]
    assert len(code) >= 6

    # Verify short code can be decoded back to a valid integer snowflake
    int_id = decode_base62(code)
    assert int_id > 0

    # 2. Verify redirect works
    redir = client.get(f"/{code}", follow_redirects=False)
    assert redir.status_code == 307
    assert redir.headers["location"] == "https://distributed-systems.org/consensus"
