from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

PERFORMANCE_AGENT_TYPE = "performance-agent"
PERFORMANCE_AGENT_VERSION = "0.1.0"
PERFORMANCE_SERVICE_VERSION = "0.3.0"
SCHEMA_VERSION = "1.0"

router = APIRouter()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def contract_response(
    *,
    status: str,
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
        "correlation_id": None,
        "data": data,
        "metadata": metadata or {},
        "error": error,
        "confidence_score": confidence_score,
    }


@router.get("/version")
def version() -> Dict[str, Any]:
    return contract_response(
        status="success",
        data={
            "agent_type": PERFORMANCE_AGENT_TYPE,
            "version": PERFORMANCE_AGENT_VERSION,
            "service_version": PERFORMANCE_SERVICE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "api_contract": "multi-agent-trading-api-contract",
        },
        metadata={
            "required_operational_endpoints": ["/health", "/ready", "/version"],
        },
    )


@router.get("/ready")
def ready() -> Dict[str, Any]:
    return contract_response(
        status="success",
        data={
            "ready": True,
            "report_endpoint": "/performance/report",
            "strategy_endpoint": "/performance/strategy",
            "symbol_endpoint": "/performance/symbol",
            "session_risk_endpoint": "/performance/session-risk",
            "trade_plan_summary_endpoint": "/performance/trade-plans/summary",
            "database_summary_endpoint": "/performance/trade-plans/database-summary",
        },
        metadata={
            "contract_source": "performance-agent-runtime-contract",
        },
        confidence_score=1.0,
    )
