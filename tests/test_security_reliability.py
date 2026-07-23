from fastapi.testclient import TestClient

from app.database_client import DatabaseAgentError
from app.main import app


client = TestClient(app, raise_server_exceptions=False)


def _report_payload():
    return {
        "initial_equity": 10000,
        "trades": [],
        "equity_curve": [],
    }


def test_protected_endpoint_requires_valid_api_key(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_AUTH_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_AGENT_API_KEY", "secret-key")
    monkeypatch.setenv("PERFORMANCE_AGENT_DATABASE_REQUIRED", "false")

    missing = client.post("/performance/report", json=_report_payload())
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_api_key"

    wrong = client.post(
        "/performance/report",
        json=_report_payload(),
        headers={"X-API-KEY": "wrong-key"},
    )
    assert wrong.status_code == 401

    valid = client.post(
        "/performance/report",
        json=_report_payload(),
        headers={
            "X-API-KEY": "secret-key",
            "X-Correlation-ID": "security-test-correlation",
        },
    )
    assert valid.status_code == 200
    assert valid.json()["correlation_id"] == "security-test-correlation"
    assert (
        valid.headers["X-Correlation-ID"]
        == "security-test-correlation"
    )


def test_missing_server_api_key_fails_closed(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_AUTH_ENABLED", "true")
    monkeypatch.delenv("PERFORMANCE_AGENT_API_KEY", raising=False)

    response = client.post("/performance/report", json=_report_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == (
        "performance_api_key_not_configured"
    )


def test_ready_reports_required_configuration(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_AUTH_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_AGENT_DATABASE_REQUIRED", "true")
    monkeypatch.delenv("PERFORMANCE_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_AGENT_URL", raising=False)
    monkeypatch.delenv("DATABASE_AGENT_API_KEY", raising=False)

    not_ready = client.get(
        "/ready",
        headers={"X-Correlation-ID": "not-ready-test"},
    )
    assert not_ready.status_code == 503
    assert not_ready.json()["data"]["ready"] is False
    assert not_ready.json()["metadata"]["failed_checks"] == [
        "performance_api_key",
        "database_agent_configuration",
    ]

    monkeypatch.setenv("PERFORMANCE_AGENT_API_KEY", "secret-key")
    monkeypatch.setenv("DATABASE_AGENT_URL", "http://database-agent:8001")
    monkeypatch.setenv("DATABASE_AGENT_API_KEY", "database-key")

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["data"]["ready"] is True
    assert ready.json()["data"]["checks"] == {
        "api_authentication": True,
        "database_agent_configuration": True,
        "database_agent_required": True,
    }


def test_validation_error_uses_standard_contract(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_AUTH_ENABLED", "false")

    response = client.post(
        "/performance/report",
        json={"initial_equity": 0},
        headers={"X-Correlation-ID": "validation-test"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "validation_error"
    assert payload["correlation_id"] == "validation-test"


def test_database_error_uses_standard_contract(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_AUTH_ENABLED", "false")

    class FailingDatabaseClient:
        def list_trade_plans(self, query):
            raise DatabaseAgentError("database unavailable")

    monkeypatch.setattr(
        "app.main.DatabaseAgentClient",
        FailingDatabaseClient,
    )
    response = client.get(
        "/performance/trade-plans/database-summary?initial_equity=10000",
        headers={"X-Correlation-ID": "database-error-test"},
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["code"] == "database_agent_error"
    assert payload["correlation_id"] == "database-error-test"
