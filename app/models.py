from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generic, Iterable, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator


T = TypeVar("T")

PERFORMANCE_AGENT_TYPE = "performance-agent"
PERFORMANCE_AGENT_VERSION = "0.4.0"
PERFORMANCE_SERVICE_VERSION = "0.4.0"
PERFORMANCE_OUTCOME_VERSION = "performance-outcome-v1"
LEARNING_OUTCOME_VERSION = "learning-outcome-v1"
SCHEMA_VERSION = "1.0"

StrategyBucket = Literal[
    "core_dividend",
    "value_rebound",
    "news_momentum",
]

EVIDENCE_STATUS_ALLOWLIST: Dict[str, set[str]] = {
    "scanner": {"suggested", "complete", "valid", "available"},
    "fundamental": {"complete", "valid", "available"},
    "technical": {"complete", "valid", "available"},
    "manager": {"classified", "complete", "valid"},
}


def _iter_evidence_status_maps(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        statuses = value.get("evidence_statuses")
        if isinstance(statuses, dict):
            yield statuses
        for child in value.values():
            yield from _iter_evidence_status_maps(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_evidence_status_maps(child)


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
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_evidence_status_allowlist(self):
        roots: tuple[Any, ...] = (
            self.plan,
            self.metadata,
            self.lifecycle,
        )
        for root in roots:
            for statuses in _iter_evidence_status_maps(root):
                for source, raw_status in statuses.items():
                    normalized_source = str(source).strip().lower()
                    normalized_status = str(raw_status).strip().lower()
                    allowed = EVIDENCE_STATUS_ALLOWLIST.get(
                        normalized_source
                    )
                    if allowed is None:
                        raise ValueError(
                            "unsupported evidence status source: "
                            f"{normalized_source or 'missing'}"
                        )
                    if normalized_status not in allowed:
                        raise ValueError(
                            "unsupported evidence status: "
                            f"{normalized_source}={normalized_status or 'missing'}"
                        )
        return self


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


class DatabaseLearningOutcomeQuery(BaseModel):
    account_id: str | int
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


class EvidenceContribution(BaseModel):
    version: str
    supported_bucket: Optional[StrategyBucket] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_status: str
    reasons: List[str] = Field(default_factory=list)


class LearningOutcomeRecord(BaseModel):
    outcome_version: Literal["learning-outcome-v1"] = LEARNING_OUTCOME_VERSION
    outcome_id: str
    trade_plan_id: str
    account_id: str | int
    symbol: str
    strategy_bucket: StrategyBucket
    manager_bucket: StrategyBucket
    execution_bucket: StrategyBucket
    database_bucket: StrategyBucket
    manager_classifier_version: str
    evidence_versions: Dict[str, str]
    evidence_contributions: Dict[str, EvidenceContribution]
    classification_inputs: Dict[str, Any] = Field(default_factory=dict)
    bucket_confidence: float = Field(ge=0.0, le=1.0)
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    realized_pnl: float
    return_pct: float
    holding_period_days: float = Field(ge=0.0)
    exit_reason: str
    risk_approved: bool
    execution_status: str
    outcome_status: Literal["closed"] = "closed"
    pnl_status: Literal["realized"] = "realized"


class LearningOutcomeBuildRequest(BaseModel):
    trade_plans: List[TradePlanLifecycleRecord] = Field(default_factory=list)
    fills: List[TradePlanFill] = Field(default_factory=list)


class LearningOutcomeBatch(BaseModel):
    performance_contract_version: str = PERFORMANCE_OUTCOME_VERSION
    learning_contract_version: str = LEARNING_OUTCOME_VERSION
    reviewed_trade_plans: int = 0
    generated_outcomes: int = 0
    rejected_trade_plans: int = 0
    outcomes: List[LearningOutcomeRecord] = Field(default_factory=list)
    rejected_records: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    requires_human_review: bool = True
    auto_apply: bool = False


class SessionRiskMetricsRequest(BaseModel):
    equity: float = Field(gt=0)
    account_id: Optional[str | int] = None
    symbol: Optional[str] = None
    fills: List[TradePlanFill] = Field(default_factory=list)
    generated_at: Optional[datetime] = None
    emergency_halt: bool = False


class SessionRiskMetrics(BaseModel):
    account_id: Optional[str | int] = None
    symbol: Optional[str] = None
    daily_realized_pnl: float = 0.0
    weekly_realized_pnl: float = 0.0
    daily_loss_pct: float = 0.0
    weekly_loss_pct: float = 0.0
    consecutive_losses: int = 0
    trades_today: int = 0
    symbol_trades_today: int = 0
    minutes_since_last_loss: Optional[float] = None
    minutes_since_last_symbol_trade: Optional[float] = None
    emergency_halt: bool = False
    source: str = "performance_agent"
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    warnings: List[str] = Field(default_factory=list)


class HealthData(BaseModel):
    status: str = "healthy"
    service: str = "performance-agent"
    performance_contract_version: str = PERFORMANCE_OUTCOME_VERSION
    learning_contract_version: str = LEARNING_OUTCOME_VERSION


class StandardAgentResponse(BaseModel, Generic[T]):
    status: Literal["success", "error"]
    agent_type: str = PERFORMANCE_AGENT_TYPE
    version: str = PERFORMANCE_AGENT_VERSION
    schema_version: str = SCHEMA_VERSION
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    correlation_id: Optional[str] = None
    data: Optional[T] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
    confidence_score: Optional[float] = None
