from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


SHADOW_PERFORMANCE_SCHEMA_VERSION = "shadow-performance.v1"


class ShadowTradeOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shadow_trade_id: str = Field(min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=20)
    strategy: str = "unknown"
    regime: str = "unknown"
    side: Literal["buy", "sell"] = "buy"
    mfe_pct: float
    mae_pct: float
    gross_return_pct: float
    estimated_cost_pct: float = Field(default=0.0, ge=0)
    net_return_pct: float
    holding_period_seconds: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def normalize_and_validate(self) -> "ShadowTradeOutcome":
        self.symbol = self.symbol.strip().upper()
        self.strategy = self.strategy.strip().lower() or "unknown"
        self.regime = self.regime.strip().lower() or "unknown"
        for name in (
            "mfe_pct",
            "mae_pct",
            "gross_return_pct",
            "estimated_cost_pct",
            "net_return_pct",
            "holding_period_seconds",
        ):
            value = getattr(self, name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        return self


class ShadowPerformanceRequest(BaseModel):
    outcomes: List[ShadowTradeOutcome] = Field(default_factory=list)
    minimum_observations_for_paper_review: int = Field(default=50, ge=1, le=100000)


class ShadowPerformanceSummary(BaseModel):
    schema_version: Literal["shadow-performance.v1"] = SHADOW_PERFORMANCE_SCHEMA_VERSION
    observation_count: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float] = None
    net_expectancy_pct: Optional[float] = None
    gross_expectancy_pct: Optional[float] = None
    average_cost_pct: Optional[float] = None
    profit_factor: Optional[float] = None
    average_mfe_pct: Optional[float] = None
    average_mae_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    average_holding_period_seconds: Optional[float] = None
    paper_review_ready: bool
    advisory_only: Literal[True] = True
    broker_order_authorized: Literal[False] = False
    by_strategy: Dict[str, Dict[str, float | int | None]] = Field(default_factory=dict)
    by_regime: Dict[str, Dict[str, float | int | None]] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _profit_factor(values: List[float]) -> Optional[float]:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _max_drawdown(values: List[float]) -> Optional[float]:
    if not values:
        return None
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown


def _aggregate(outcomes: List[ShadowTradeOutcome], dimension: str) -> Dict[str, Dict[str, float | int | None]]:
    grouped: dict[str, list[ShadowTradeOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[str(getattr(outcome, dimension) or "unknown")].append(outcome)
    result: Dict[str, Dict[str, float | int | None]] = {}
    for key, rows in sorted(grouped.items()):
        net = [row.net_return_pct for row in rows]
        pf = _profit_factor(net)
        result[key] = {
            "observation_count": len(rows),
            "net_expectancy_pct": round(_mean(net) or 0.0, 8),
            "profit_factor": round(pf, 6) if pf is not None and math.isfinite(pf) else pf,
            "average_mfe_pct": round(_mean([row.mfe_pct for row in rows]) or 0.0, 8),
            "average_mae_pct": round(_mean([row.mae_pct for row in rows]) or 0.0, 8),
        }
    return result


def build_shadow_performance(payload: ShadowPerformanceRequest) -> ShadowPerformanceSummary:
    outcomes = payload.outcomes
    net = [row.net_return_pct for row in outcomes]
    gross = [row.gross_return_pct for row in outcomes]
    costs = [row.estimated_cost_pct for row in outcomes]
    holding = [row.holding_period_seconds for row in outcomes if row.holding_period_seconds is not None]
    wins = sum(value > 0 for value in net)
    losses = sum(value < 0 for value in net)
    count = len(outcomes)
    pf = _profit_factor(net)
    warnings: List[str] = []
    if count < payload.minimum_observations_for_paper_review:
        warnings.append("shadow_observations_below_paper_review_threshold")
    if count and (_mean(net) or 0.0) <= 0:
        warnings.append("shadow_net_expectancy_not_positive")

    return ShadowPerformanceSummary(
        observation_count=count,
        winning_trades=wins,
        losing_trades=losses,
        win_rate=round(wins / count, 8) if count else None,
        net_expectancy_pct=round(_mean(net), 8) if net else None,
        gross_expectancy_pct=round(_mean(gross), 8) if gross else None,
        average_cost_pct=round(_mean(costs), 8) if costs else None,
        profit_factor=(round(pf, 6) if pf is not None and math.isfinite(pf) else pf),
        average_mfe_pct=round(_mean([row.mfe_pct for row in outcomes]), 8) if outcomes else None,
        average_mae_pct=round(_mean([row.mae_pct for row in outcomes]), 8) if outcomes else None,
        max_drawdown_pct=round(_max_drawdown(net), 8) if net else None,
        average_holding_period_seconds=round(_mean(holding), 4) if holding else None,
        paper_review_ready=count >= payload.minimum_observations_for_paper_review and bool(net) and (_mean(net) or 0.0) > 0,
        by_strategy=_aggregate(outcomes, "strategy"),
        by_regime=_aggregate(outcomes, "regime"),
        warnings=warnings,
    )
