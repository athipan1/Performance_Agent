from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError

from app.database_client import DatabaseAgentClient, DatabaseAgentError
from app.execution_cost import (
    ExecutionCostAttributionRequest,
    ExecutionCostAttributionSummary,
    build_execution_cost_attribution,
)
from app.models import (
    DatabaseLearningOutcomeQuery,
    DatabaseTradePlanSummaryQuery,
    HealthData,
    LearningOutcomeBatch,
    LearningOutcomeBuildRequest,
    PERFORMANCE_OUTCOME_VERSION,
    PERFORMANCE_SERVICE_VERSION,
    PerformanceMetrics,
    PerformanceReportRequest,
    SessionRiskMetrics,
    SessionRiskMetricsRequest,
    StandardAgentResponse,
    TradePlanPerformanceRequest,
    TradePlanPerformanceSummary,
)
from app.outcome_builder import build_learning_outcomes
from app.security import (
    auth_enabled,
    configured_api_key,
    contract_error_response,
    is_public_path,
    request_correlation_id,
    valid_api_key,
)
from app.service import (
    build_performance_report,
    build_trade_plan_performance_summary,
)
from app.session_risk import build_session_risk_metrics
from app.system_contract import router as system_contract_router


app = FastAPI(
    title="Performance Agent",
    description=(
        "Performance analytics and strict learning-outcome generation for "
        "the multi-agent trading system."
    ),
    version=PERFORMANCE_SERVICE_VERSION,
)
app.include_router(system_contract_router)


@app.middleware("http")
async def security_and_correlation_middleware(request: Request, call_next):
    correlation_id = request_correlation_id(request)
    if not is_public_path(request.url.path) and auth_enabled():
        if configured_api_key() is None:
            return contract_error_response(
                status_code=503,
                code="performance_api_key_not_configured",
                message="Performance_Agent API authentication is not configured",
                correlation_id=correlation_id,
            )
        if not valid_api_key(request.headers.get("X-API-KEY")):
            return contract_error_response(
                status_code=401,
                code="invalid_api_key",
                message="A valid X-API-KEY header is required",
                correlation_id=correlation_id,
            )

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.exception_handler(DatabaseAgentError)
async def database_agent_error_handler(
    request: Request,
    exc: DatabaseAgentError,
):
    return contract_error_response(
        status_code=502,
        code="database_agent_error",
        message="Database_Agent request failed",
        correlation_id=request_correlation_id(request),
        details=str(exc),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
):
    return contract_error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        correlation_id=request_correlation_id(request),
        details=exc.errors(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    return contract_error_response(
        status_code=500,
        code="internal_error",
        message="Performance_Agent encountered an unexpected error",
        correlation_id=request_correlation_id(request),
        details=type(exc).__name__,
    )


def _success_response(
    request: Request,
    data: Any,
    *,
    metadata: Optional[dict[str, Any]] = None,
    confidence_score: Optional[float] = None,
):
    return StandardAgentResponse(
        status="success",
        data=data,
        correlation_id=request_correlation_id(request),
        metadata=metadata or {},
        confidence_score=confidence_score,
    )


@app.get("/health", response_model=StandardAgentResponse[HealthData])
def health(request: Request) -> StandardAgentResponse[HealthData]:
    return _success_response(request, HealthData())


@app.post(
    "/performance/report",
    response_model=StandardAgentResponse[PerformanceMetrics],
)
def performance_report(
    request: Request,
    payload: PerformanceReportRequest,
) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(payload)
    return _success_response(request, data)


@app.post(
    "/performance/strategy",
    response_model=StandardAgentResponse[PerformanceMetrics],
)
def performance_strategy(
    request: Request,
    payload: PerformanceReportRequest,
) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(payload)
    return _success_response(request, data)


@app.post(
    "/performance/symbol",
    response_model=StandardAgentResponse[PerformanceMetrics],
)
def performance_symbol(
    request: Request,
    payload: PerformanceReportRequest,
) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(payload)
    return _success_response(request, data)


@app.post(
    "/performance/session-risk",
    response_model=StandardAgentResponse[SessionRiskMetrics],
)
def performance_session_risk(
    request: Request,
    payload: SessionRiskMetricsRequest,
) -> StandardAgentResponse[SessionRiskMetrics]:
    data = build_session_risk_metrics(payload)
    return _success_response(request, data)


@app.post(
    "/performance/execution-costs",
    response_model=StandardAgentResponse[ExecutionCostAttributionSummary],
)
def performance_execution_costs(
    request: Request,
    payload: ExecutionCostAttributionRequest,
) -> StandardAgentResponse[ExecutionCostAttributionSummary]:
    """Attribute decision-to-fill slippage and publish a Paper-derived cost floor.

    Positive cost means adverse execution, while negative cost means price
    improvement. The suggested Backtest floor remains unavailable until the
    requested minimum observation count is satisfied.
    """

    data = build_execution_cost_attribution(payload)
    confidence = min(
        1.0,
        data.observation_count / payload.minimum_observations_for_stress_floor,
    )
    return _success_response(
        request,
        data,
        metadata={
            "source": "execution-fill-observations",
            "schema_version": data.schema_version,
            "stress_floor_ready": data.stress_floor_ready,
            "advisory_only": True,
        },
        confidence_score=round(confidence, 4),
    )


@app.post(
    "/performance/trade-plans/summary",
    response_model=StandardAgentResponse[TradePlanPerformanceSummary],
)
def trade_plan_performance_summary(
    request: Request,
    payload: TradePlanPerformanceRequest,
) -> StandardAgentResponse[TradePlanPerformanceSummary]:
    data = build_trade_plan_performance_summary(payload)
    return _success_response(request, data)


@app.post(
    "/performance/learning-outcomes",
    response_model=StandardAgentResponse[LearningOutcomeBatch],
)
def performance_learning_outcomes(
    request: Request,
    payload: LearningOutcomeBuildRequest,
) -> StandardAgentResponse[LearningOutcomeBatch]:
    data = build_learning_outcomes(payload)
    confidence_score = (
        0.0
        if data.reviewed_trade_plans == 0
        else round(
            data.generated_outcomes / data.reviewed_trade_plans,
            4,
        )
    )
    return _success_response(
        request,
        data,
        metadata={
            "source": "request-payload",
            "performance_contract_version": PERFORMANCE_OUTCOME_VERSION,
            "learning_contract_version": data.learning_contract_version,
            "requires_human_review": True,
            "auto_apply": False,
        },
        confidence_score=confidence_score,
    )


@app.get(
    "/performance/trade-plans/database-summary",
    response_model=StandardAgentResponse[TradePlanPerformanceSummary],
)
def database_trade_plan_performance_summary(
    request: Request,
    initial_equity: float = Query(gt=0),
    period: str = "all",
    account_id: Optional[str] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    strategy: Optional[str] = None,
    strategy_bucket: Optional[str] = None,
    risk_approval_id: Optional[str] = None,
    order_id: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(
        default="updated_at",
        pattern="^(created_at|updated_at)$",
    ),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    include_fills: bool = True,
) -> StandardAgentResponse[TradePlanPerformanceSummary]:
    query = DatabaseTradePlanSummaryQuery(
        initial_equity=initial_equity,
        period=period,
        account_id=account_id,
        symbol=symbol,
        status=status,
        strategy=strategy,
        strategy_bucket=strategy_bucket,
        risk_approval_id=risk_approval_id,
        order_id=order_id,
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
        include_fills=include_fills,
    )
    client = DatabaseAgentClient()
    trade_plans = client.list_trade_plans(query)
    fills = []
    warnings = []
    if include_fills:
        if account_id is not None:
            fills = client.list_fills(
                account_id=account_id,
                symbol=symbol,
                limit=500,
            )
        else:
            warnings.append(
                "Fills were not fetched because account_id was not provided"
            )
    summary = build_trade_plan_performance_summary(
        TradePlanPerformanceRequest(
            initial_equity=query.initial_equity,
            period=query.period,
            trade_plans=trade_plans,
            fills=fills,
        )
    )
    summary.warnings.extend(warnings)
    return _success_response(
        request,
        summary,
        metadata={
            "source": "database-agent",
            "trade_plan_count_fetched": len(trade_plans),
            "fill_count_fetched": len(fills),
            "include_fills": include_fills,
        },
    )


@app.get(
    "/performance/learning-outcomes/database",
    response_model=StandardAgentResponse[LearningOutcomeBatch],
)
def database_learning_outcomes(
    request: Request,
    account_id: str,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    strategy: Optional[str] = None,
    strategy_bucket: Optional[str] = None,
    risk_approval_id: Optional[str] = None,
    order_id: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(
        default="updated_at",
        pattern="^(created_at|updated_at)$",
    ),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> StandardAgentResponse[LearningOutcomeBatch]:
    query = DatabaseLearningOutcomeQuery(
        account_id=account_id,
        symbol=symbol,
        status=status,
        strategy=strategy,
        strategy_bucket=strategy_bucket,
        risk_approval_id=risk_approval_id,
        order_id=order_id,
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
    )
    client = DatabaseAgentClient()
    trade_plans = client.list_trade_plans(query)
    fills = client.list_fills(
        account_id=account_id,
        symbol=symbol,
        limit=500,
    )
    data = build_learning_outcomes(
        LearningOutcomeBuildRequest(
            trade_plans=trade_plans,
            fills=fills,
        )
    )
    confidence_score = (
        0.0
        if data.reviewed_trade_plans == 0
        else round(
            data.generated_outcomes / data.reviewed_trade_plans,
            4,
        )
    )
    return _success_response(
        request,
        data,
        metadata={
            "source": "database-agent",
            "trade_plan_count_fetched": len(trade_plans),
            "fill_count_fetched": len(fills),
            "performance_contract_version": PERFORMANCE_OUTCOME_VERSION,
            "learning_contract_version": data.learning_contract_version,
            "requires_human_review": True,
            "auto_apply": False,
        },
        confidence_score=confidence_score,
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Performance Agent is running"}
