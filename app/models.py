from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class TradeSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeResult(BaseModel):
    symbol: str
    strategy: str = "unknown"
    sector: Optional[str] = None
    side: TradeSide = TradeSide.LONG
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    fees: float = Field(default=0, ge=0)
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class EquityPoint(BaseModel):
    timestamp: datetime
    equity: float = Field(gt=0)


class PerformanceReportRequest(BaseModel):
    initial_equity: float = Field(gt=0)
    trades: List[TradeResult] = Field(default_factory=list)
    equity_curve: List[EquityPoint] = Field(default_factory=list)
    period: str = "all"


class PerformanceMetrics(BaseModel):
    period: str
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_profit: float
    return_pct: float
    average_win: float
    average_loss: float
    expectancy: float
    profit_factor: Optional[float]
    max_drawdown: float
    best_strategy: Optional[str] = None
    worst_strategy: Optional[str] = None
    by_strategy: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    by_symbol: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class TradePlanLifecycleRecord(BaseModel):
    trade_plan_id: str
    account_id: str | int
    symbol: str
    side: str = "buy"
    status: str = "created"
    strategy: str = "unknown"
    strategy_bucket: str = "unassigned"
    risk_approval_id: Optional[str] = None
    order_id: Optional[int] = None
    execution_job_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    plan: Dict[str, Any] = Field(default_factory=dict)
    lifecycle: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TradePlanFill(BaseModel):
    trade_plan_id: Optional[str] = None
    order_id: Optional[int] = None
    trade_id: Optional[str | int] = None
    symbol: str
    side: str = "buy"
    quantity: float = Field(gt=0)
    fill_price: float = Field(gt=0)
    fees: float = Field(default=0, ge=0)
    realized_pnl: Optional[float] = None
    filled_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TradePlanPerformanceRequest(BaseModel):
    initial_equity: float = Field(gt=0)
    period: str = "all"
    trade_plans: List[TradePlanLifecycleRecord] = Field(default_factory=list)
    fills: List[TradePlanFill] = Field(default_factory=list)


class DatabaseTradePlanSummaryQuery(BaseModel):
    initial_equity: float = Field(gt=0)
    period: str = "all"
    account_id: Optional[str | int] = None
    symbol: Optional[str] = None
    status: Optional[str] = None
    strategy: Optional[str] = None
    strategy_bucket: Optional[str] = None
    risk_approval_id: Optional[str] = None
    order_id: Optional[int] = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    sort: str = "updated_at"
    order: str = "desc"
    include_fills: bool = True


class TradePlanPerformanceSummary(BaseModel):
    period: str
    trade_plan_count: int
    closed_plan_count: int
    open_plan_count: int
    winning_plans: int
    losing_plans: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    return_pct: float
    expectancy: float
    profit_factor: Optional[float]
    average_win: float
    average_loss: float
    best_strategy_bucket: Optional[str] = None
    worst_strategy_bucket: Optional[str] = None
    by_strategy_bucket: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    by_symbol: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    plan_results: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class HealthData(BaseModel):
    status: str = "healthy"
    service: str = "performance-agent"


class StandardAgentResponse(BaseModel, Generic[T]):
    status: str
    agent_type: str = "performance-agent"
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Optional[T] = None
    error: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
