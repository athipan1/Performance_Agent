from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from app.models import (
    PERFORMANCE_AGENT_TYPE,
    PERFORMANCE_AGENT_VERSION,
    SCHEMA_VERSION,
)


PUBLIC_PATHS = {
    "/",
    "/health",
    "/ready",
    "/version",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def auth_enabled() -> bool:
    return _env_flag("PERFORMANCE_AGENT_AUTH_ENABLED", True)


def database_required() -> bool:
    return _env_flag("PERFORMANCE_AGENT_DATABASE_REQUIRED", True)


def configured_api_key() -> str | None:
    value = os.getenv("PERFORMANCE_AGENT_API_KEY")
    return value if value else None


def database_configuration_ready() -> bool:
    if not database_required():
        return True
    return bool(
        os.getenv("DATABASE_AGENT_URL")
        and os.getenv("DATABASE_AGENT_API_KEY")
    )


def request_correlation_id(request: Request) -> str:
    existing = getattr(request.state, "correlation_id", None)
    if existing:
        return str(existing)
    supplied = request.headers.get("X-Correlation-ID")
    correlation_id = supplied or str(uuid4())
    request.state.correlation_id = correlation_id
    return correlation_id


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def valid_api_key(provided: str | None) -> bool:
    expected = configured_api_key()
    if expected is None or provided is None:
        return False
    return hmac.compare_digest(provided, expected)


def contract_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    details: Any = None,
) -> JSONResponse:
    payload = {
        "status": "error",
        "agent_type": PERFORMANCE_AGENT_TYPE,
        "version": PERFORMANCE_AGENT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "data": None,
        "metadata": {},
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "confidence_score": None,
    }
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={"X-Correlation-ID": correlation_id},
    )
