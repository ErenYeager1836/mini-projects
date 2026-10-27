"""
Comprehensive unit and integration test suite for url-shortener.
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from url_shortener.app import create_app
from url_shortener.database import Database


@pytest.fixture
def client() -> TestClient:
    """Fixture providing an isolated FastAPI TestClient backed by an in-memory SQLite database."""
    test_db = Database(":memory:")
    test_app = create_app(db=test_db)
    return TestClient(test_app)


def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "url-shortener"}


def test_shorten_url_auto_generated_code(client: TestClient):
    payload = {
        "url": "https://example.com/long/deep/nested/path?id=12345"
    }
    response = client.post("/api/shorten", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "short_code" in data
    assert len(data["short_code"]) == 6
    assert data["target_url"] == payload["url"]
    assert data["expires_at"] is None


def test_shorten_url_with_custom_code(client: TestClient):
    payload = {
        "url": "https://python.org",
        "custom_code": "my_custom_alias",
        "ttl_seconds": 3600
    }
    response = client.post("/api/shorten", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["short_code"] == "my_custom_alias"
    assert data["target_url"] == "https://python.org"
    assert data["expires_at"] is not None


def test_shorten_duplicate_custom_code_returns_409(client: TestClient):
    payload = {
        "url": "https://github.com",
        "custom_code": "gh-alias"
    }
    # Initial creation
    res1 = client.post("/api/shorten", json=payload)
    assert res1.status_code == 201

    # Conflict attempt
    res2 = client.post("/api/shorten", json=payload)
    assert res2.status_code == 409
    assert "already in use" in res2.json()["detail"]


def test_redirect_and_click_tracking(client: TestClient):
    # Shorten a URL
    res = client.post("/api/shorten", json={"url": "https://developer.mozilla.org"})
    short_code = res.json()["short_code"]

    # Request redirection with custom headers
    headers = {
        "User-Agent": "PytestBot/1.0",
        "Referer": "https://search.engine.com"
    }
    # follow_redirects=False to verify 307 status code and Location header
    redirect_res = client.get(f"/{short_code}", headers=headers, follow_redirects=False)
    assert redirect_res.status_code == 307
    assert redirect_res.headers["location"] == "https://developer.mozilla.org"

    # Verify telemetry in analytics
    analytics_res = client.get(f"/api/analytics/{short_code}")
    assert analytics_res.status_code == 200
    analytics_data = analytics_res.json()
    assert analytics_data["total_clicks"] == 1
    assert len(analytics_data["recent_clicks"]) == 1
    assert analytics_data["recent_clicks"][0]["user_agent"] == "PytestBot/1.0"
    assert analytics_data["recent_clicks"][0]["referer"] == "https://search.engine.com"


def test_redirect_nonexistent_returns_404(client: TestClient):
    response = client.get("/nonexistent_code", follow_redirects=False)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_redirect_expired_url_returns_410(client: TestClient):
    # Directly insert an already-expired record
    db: Database = client.app.state.db
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    db.insert_url(
        short_code="expired_link",
        target_url="https://expired.example.com",
        created_at=past_time,
        expires_at=past_time
    )

    response = client.get("/expired_link", follow_redirects=False)
    assert response.status_code == 410
    assert "expired" in response.json()["detail"].lower()

    # Analytics should reflect expired status
    analytics_res = client.get("/api/analytics/expired_link")
    assert analytics_res.status_code == 200
    assert analytics_res.json()["is_expired"] is True


def test_input_validation_invalid_schemes(client: TestClient):
    # Reject javascript:
    res1 = client.post("/api/shorten", json={"url": "javascript:alert('xss')"})
    assert res1.status_code == 422

    # Reject file:
    res2 = client.post("/api/shorten", json={"url": "file:///etc/passwd"})
    assert res2.status_code == 422

    # Reject plain string without scheme
    res3 = client.post("/api/shorten", json={"url": "example.com"})
    assert res3.status_code == 422


def test_input_validation_invalid_custom_code(client: TestClient):
    # Code with illegal spaces/characters
    res1 = client.post("/api/shorten", json={"url": "https://example.com", "custom_code": "bad code!"})
    assert res1.status_code == 422

    # Code too short (< 3 chars)
    res2 = client.post("/api/shorten", json={"url": "https://example.com", "custom_code": "ab"})
    assert res2.status_code == 422
