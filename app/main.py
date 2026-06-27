from __future__ import annotations

from fastapi import FastAPI

from app.models import HealthData, PerformanceMetrics, PerformanceReportRequest, StandardAgentResponse
from app.service import build_performance_report


app = FastAPI(
    title="Performance Agent",
    description="Performance analytics service for the multi-agent trading system.",
    version="0.1.0",
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


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Performance Agent is running"}
