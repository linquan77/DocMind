from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_service_status_and_trace_id():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Docmind API"
    assert body["trace_id"] == response.headers["X-Trace-ID"]


def test_health_preserves_incoming_trace_id():
    response = client.get("/health", headers={"X-Trace-ID": "trace-test-001"})

    assert response.status_code == 200
    assert response.headers["X-Trace-ID"] == "trace-test-001"
    assert response.json()["trace_id"] == "trace-test-001"
