from fastapi.testclient import TestClient

from app.main import app
from app.security import configured_database_agent_url


def test_runtime_database_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("RUNTIME_DATABASE_AGENT_URL", "https://runtime.example")
    monkeypatch.setenv("DATABASE_AGENT_URL", "http://database-agent:8001")
    assert configured_database_agent_url() == "https://runtime.example"


def test_ready_accepts_runtime_database_url(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_AUTH_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_AGENT_API_KEY", "performance-key")
    monkeypatch.setenv("PERFORMANCE_AGENT_DATABASE_REQUIRED", "true")
    monkeypatch.setenv("RUNTIME_DATABASE_AGENT_URL", "https://database.example")
    monkeypatch.delenv("DATABASE_AGENT_URL", raising=False)
    monkeypatch.setenv("DATABASE_AGENT_API_KEY", "database-key")

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["ready"] is True
    assert payload["data"]["checks"]["database_agent_url"] is True
    assert payload["metadata"]["database_url_source"] == "RUNTIME_DATABASE_AGENT_URL"


def test_ready_reports_missing_database_key(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_AUTH_ENABLED", "false")
    monkeypatch.setenv("PERFORMANCE_AGENT_DATABASE_REQUIRED", "true")
    monkeypatch.setenv("RUNTIME_DATABASE_AGENT_URL", "https://database.example")
    monkeypatch.delenv("DATABASE_AGENT_API_KEY", raising=False)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["data"]["checks"]["database_agent_url"] is True
    assert payload["data"]["checks"]["database_agent_api_key"] is False
    assert payload["metadata"]["failed_checks"] == ["database_agent_api_key"]
