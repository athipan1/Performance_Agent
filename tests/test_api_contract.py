from fastapi.testclient import TestClient

from app.main import app


REQUIRED_CONTRACT_FIELDS = {
    "status",
    "agent_type",
    "version",
    "schema_version",
    "timestamp",
    "correlation_id",
    "data",
    "metadata",
    "error",
    "confidence_score",
}


def assert_contract_response(payload):
    assert REQUIRED_CONTRACT_FIELDS.issubset(payload.keys())
    assert payload["agent_type"] == "performance-agent"
    assert payload["version"] == "0.4.0"
    assert payload["schema_version"] == "1.0"


def test_version_endpoint_uses_contract_response():
    client = TestClient(app)
    response = client.get("/version")

    assert response.status_code == 200
    payload = response.json()
    assert_contract_response(payload)
    assert payload["data"]["api_contract"] == (
        "multi-agent-trading-api-contract"
    )
    assert payload["data"]["schema_version"] == "1.0"
    assert payload["data"]["service_version"] == "0.4.0"
    assert payload["data"]["performance_contract_version"] == (
        "performance-outcome-v1"
    )
    assert payload["data"]["learning_contract_version"] == (
        "learning-outcome-v1"
    )
    assert payload["metadata"]["outcome_policy"] == (
        "closed-realized-only"
    )


def test_ready_endpoint_uses_contract_response():
    client = TestClient(app)
    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert_contract_response(payload)
    assert payload["data"]["ready"] is True
    assert payload["data"]["learning_outcomes_endpoint"] == (
        "/performance/learning-outcomes"
    )
    assert payload["data"]["database_learning_outcomes_endpoint"] == (
        "/performance/learning-outcomes/database"
    )
    assert payload["data"]["requires_human_review"] is True
    assert payload["data"]["auto_apply"] is False
    assert payload["metadata"]["contract_source"] == (
        "performance-agent-runtime-contract"
    )


def test_existing_health_endpoint_still_works():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert_contract_response(payload)
    assert payload["status"] == "success"
    assert payload["data"]["status"] == "healthy"
    assert payload["data"]["performance_contract_version"] == (
        "performance-outcome-v1"
    )
    assert payload["data"]["learning_contract_version"] == (
        "learning-outcome-v1"
    )
