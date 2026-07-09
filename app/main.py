from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Query, Request

from app.database_client import DatabaseAgentClient
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


@app.get("/health", response_model=StandardAgentResponse[HealthData])
def health() -> StandardAgentResponse[HealthData]:
    return StandardAgentResponse(status="success", data=HealthData())


@app.post(
    "/performance/report",
    response_model=StandardAgentResponse[PerformanceMetrics],
)
def performance_report(
    request: PerformanceReportRequest,
) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(request)
    return StandardAgentResponse(status="success", data=data)


@app.post(
    "/performance/strategy",
    response_model=StandardAgentResponse[PerformanceMetrics],
)
def performance_strategy(
    request: PerformanceReportRequest,
) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(request)
    return StandardAgentResponse(status="success", data=data)


@app.post(
    "/performance/symbol",
    response_model=StandardAgentResponse[PerformanceMetrics],
)
def performance_symbol(
    request: PerformanceReportRequest,
) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(request)
    return StandardAgentResponse(status="success", data=data)


@app.post(
    "/performance/session-risk",
    response_model=StandardAgentResponse[SessionRiskMetrics],
)
def performance_session_risk(
    request: SessionRiskMetricsRequest,
) -> StandardAgentResponse[SessionRiskMetrics]:
    data = build_session_risk_metrics(request)
    return StandardAgentResponse(status="success", data=data)


@app.post(
    "/performance/trade-plans/summary",
    response_model=StandardAgentResponse[TradePlanPerformanceSummary],
)
def trade_plan_performance_summary(
    request: TradePlanPerformanceRequest,
) -> StandardAgentResponse[TradePlanPerformanceSummary]:
    data = build_trade_plan_performance_summary(request)
    return StandardAgentResponse(status="success", data=data)


@app.post(
    "/performance/learning-outcomes",
    response_model=StandardAgentResponse[LearningOutcomeBatch],
)
def performance_learning_outcomes(
    request: LearningOutcomeBuildRequest,
    req: Request,
) -> StandardAgentResponse[LearningOutcomeBatch]:
    """Generate Learning_Agent-ready records from supplied plans and fills."""
    data = build_learning_outcomes(request)
    return StandardAgentResponse(
        status="success",
        data=data,
        correlation_id=req.headers.get("X-Correlation-ID"),
        metadata={
            "source": "request-payload",
            "performance_contract_version": PERFORMANCE_OUTCOME_VERSION,
            "learning_contract_version": data.learning_contract_version,
            "requires_human_review": True,
            "auto_apply": False,
        },
        confidence_score=(
            0.0
            if data.reviewed_trade_plans == 0
            else round(
                data.generated_outcomes / data.reviewed_trade_plans,
                4,
            )
        ),
    )


@app.get(
    "/performance/trade-plans/database-summary",
    response_model=StandardAgentResponse[TradePlanPerformanceSummary],
)
def database_trade_plan_performance_summary(
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
    return StandardAgentResponse(
        status="success",
        data=summary,
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
    req: Request,
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
    """Fetch Database_Agent records and produce strict learning outcomes."""
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
    return StandardAgentResponse(
        status="success",
        data=data,
        correlation_id=req.headers.get("X-Correlation-ID"),
        metadata={
            "source": "database-agent",
            "trade_plan_count_fetched": len(trade_plans),
            "fill_count_fetched": len(fills),
            "performance_contract_version": PERFORMANCE_OUTCOME_VERSION,
            "learning_contract_version": data.learning_contract_version,
            "requires_human_review": True,
            "auto_apply": False,
        },
        confidence_score=(
            0.0
            if data.reviewed_trade_plans == 0
            else round(
                data.generated_outcomes / data.reviewed_trade_plans,
                4,
            )
        ),
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Performance Agent is running"}
