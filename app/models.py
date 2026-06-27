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
