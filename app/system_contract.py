from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models import (
    LEARNING_OUTCOME_VERSION,
    PERFORMANCE_AGENT_TYPE,
    PERFORMANCE_AGENT_VERSION,
    PERFORMANCE_OUTCOME_VERSION,
    PERFORMANCE_SERVICE_VERSION,
    SCHEMA_VERSION,
)
from app.security import (
    auth_enabled,
    configured_api_key,
    database_configuration_ready,
    database_required,
    request_correlation_id,
)


router = APIRouter()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def contract_response(
    *,
    status: str,
    correlation_id: str,
    data: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
    error: Dict[str, Any] | None = None,
    confidence_score: float | None = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "agent_type": PERFORMANCE_AGENT_TYPE,
        "version": PERFORMANCE_AGENT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "timestamp": utc_timestamp(),
        "correlation_id": correlation_id,
        "data": data,
        "metadata": metadata or {},
        "error": error,
        "confidence_score": confidence_score,
    }


@router.get("/version")
def version(request: Request) -> Dict[str, Any]:
    correlation_id = request_correlation_id(request)
    return contract_response(
        status="success",
        correlation_id=correlation_id,
        data={
            "agent_type": PERFORMANCE_AGENT_TYPE,
            "version": PERFORMANCE_AGENT_VERSION,
            "service_version": PERFORMANCE_SERVICE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "api_contract": "multi-agent-trading-api-contract",
            "performance_contract_version": PERFORMANCE_OUTCOME_VERSION,
            "learning_contract_version": LEARNING_OUTCOME_VERSION,
        },
        metadata={
            "required_operational_endpoints": [
                "/health",
                "/ready",
                "/version",
            ],
            "outcome_policy": "closed-realized-only",
        },
    )


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    correlation_id = request_correlation_id(request)
    api_key_ready = not auth_enabled() or configured_api_key() is not None
    database_ready = database_configuration_ready()
    is_ready = api_key_ready and database_ready
    failed_checks = []
    if not api_key_ready:
        failed_checks.append("performance_api_key")
    if not database_ready:
        failed_checks.append("database_agent_configuration")

    payload = contract_response(
        status="success" if is_ready else "error",
        correlation_id=correlation_id,
        data={
            "ready": is_ready,
            "checks": {
                "api_authentication": api_key_ready,
                "database_agent_configuration": database_ready,
                "database_agent_required": database_required(),
            },
            "report_endpoint": "/performance/report",
            "strategy_endpoint": "/performance/strategy",
            "symbol_endpoint": "/performance/symbol",
            "session_risk_endpoint": "/performance/session-risk",
            "trade_plan_summary_endpoint": (
                "/performance/trade-plans/summary"
            ),
            "database_summary_endpoint": (
                "/performance/trade-plans/database-summary"
            ),
            "learning_outcomes_endpoint": (
                "/performance/learning-outcomes"
            ),
            "database_learning_outcomes_endpoint": (
                "/performance/learning-outcomes/database"
            ),
            "performance_contract_version": PERFORMANCE_OUTCOME_VERSION,
            "learning_contract_version": LEARNING_OUTCOME_VERSION,
            "requires_human_review": True,
            "auto_apply": False,
        },
        metadata={
            "contract_source": "performance-agent-runtime-contract",
            "failed_checks": failed_checks,
        },
        error=(
            None
            if is_ready
            else {
                "code": "service_not_ready",
                "message": "Required service configuration is incomplete",
                "details": failed_checks,
            }
        ),
        confidence_score=1.0 if is_ready else 0.0,
    )
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content=payload,
        headers={"X-Correlation-ID": correlation_id},
    )
