from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Query

from app.database_client import DatabaseAgentClient
from app.models import (
    DatabaseTradePlanSummaryQuery,
    HealthData,
    PerformanceMetrics,
    PerformanceReportRequest,
    StandardAgentResponse,
    TradePlanPerformanceRequest,
    TradePlanPerformanceSummary,
)
from app.service import build_performance_report, build_trade_plan_performance_summary


app = FastAPI(
    title="Performance Agent",
    description="Performance analytics service for the multi-agent trading system.",
    version="0.3.0",
)


@app.get("/health", response_model=StandardAgentResponse[HealthData])
def health() -> StandardAgentResponse[HealthData]:
    return StandardAgentResponse(status="success", data=HealthData())


@app.post("/performance/report", response_model=StandardAgentResponse[PerformanceMetrics])
def performance_report(request: PerformanceReportRequest) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(request)
    return StandardAgentResponse(status="success", data=data)


@app.post("/performance/strategy", response_model=StandardAgentResponse[PerformanceMetrics])
def performance_strategy(request: PerformanceReportRequest) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(request)
    return StandardAgentResponse(status="success", data=data)


@app.post("/performance/symbol", response_model=StandardAgentResponse[PerformanceMetrics])
def performance_symbol(request: PerformanceReportRequest) -> StandardAgentResponse[PerformanceMetrics]:
    data = build_performance_report(request)
    return StandardAgentResponse(status="success", data=data)


@app.post("/performance/trade-plans/summary", response_model=StandardAgentResponse[TradePlanPerformanceSummary])
def trade_plan_performance_summary(request: TradePlanPerformanceRequest) -> StandardAgentResponse[TradePlanPerformanceSummary]:
    data = build_trade_plan_performance_summary(request)
    return StandardAgentResponse(status="success", data=data)


@app.get("/performance/trade-plans/database-summary", response_model=StandardAgentResponse[TradePlanPerformanceSummary])
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
    sort: str = Query(default="updated_at", pattern="^(created_at|updated_at)$"),
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
            fills = client.list_fills(account_id=account_id, symbol=symbol, limit=500)
        else:
            warnings.append("Fills were not fetched because account_id was not provided")
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


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Performance Agent is running"}
