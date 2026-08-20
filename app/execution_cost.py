from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


EXECUTION_COST_SCHEMA_VERSION = "execution-cost-attribution.v1"


class ExecutionFillObservation(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)
    decision_price: float = Field(gt=0)
    submitted_price: Optional[float] = Field(default=None, gt=0)
    fill_price: float = Field(gt=0)
    fees: float = Field(default=0.0, ge=0)
    strategy: str = "unknown"
    regime: str = "unknown"
    order_id: Optional[str | int] = None
    trade_plan_id: Optional[str] = None
    correlation_id: Optional[str] = None
    spread_bps_at_decision: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def normalize_dimensions(self) -> "ExecutionFillObservation":
        self.symbol = self.symbol.strip().upper()
        self.strategy = self.strategy.strip().lower() or "unknown"
        self.regime = self.regime.strip().lower() or "unknown"
        if not self.symbol:
            raise ValueError("symbol must not be blank")
        for field_name in (
            "quantity",
            "decision_price",
            "fill_price",
            "fees",
            "submitted_price",
            "spread_bps_at_decision",
        ):
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{field_name} must be finite")
        return self


class ExecutionCostAttributionRequest(BaseModel):
    observations: List[ExecutionFillObservation] = Field(default_factory=list)
    minimum_observations_for_stress_floor: int = Field(default=20, ge=1, le=10000)


class ExecutionCostObservationResult(BaseModel):
    symbol: str
    side: str
    quantity: float
    decision_price: float
    submitted_price: Optional[float]
    fill_price: float
    decision_notional: float
    price_slippage_per_share: float
    price_slippage_bps: float
    submitted_to_fill_slippage_bps: Optional[float]
    slippage_cost: float
    fees: float
    all_in_execution_cost: float
    all_in_cost_bps: float
    strategy: str
    regime: str
    order_id: Optional[str] = None
    trade_plan_id: Optional[str] = None
    correlation_id: Optional[str] = None
    spread_bps_at_decision: Optional[float] = None


class ExecutionCostAttributionSummary(BaseModel):
    schema_version: Literal["execution-cost-attribution.v1"] = EXECUTION_COST_SCHEMA_VERSION
    observation_count: int
    total_decision_notional: float
    total_slippage_cost: float
    total_fees: float
    total_execution_cost: float
    weighted_price_slippage_bps: float
    weighted_all_in_cost_bps: float
    price_improvement_count: int
    adverse_slippage_count: int
    median_price_slippage_bps: Optional[float] = None
    p90_price_slippage_bps: Optional[float] = None
    p95_price_slippage_bps: Optional[float] = None
    p95_all_in_cost_bps: Optional[float] = None
    suggested_backtest_slippage_bps_floor: Optional[float] = None
    suggested_backtest_all_in_cost_bps_floor: Optional[float] = None
    stress_floor_ready: bool
    by_symbol: Dict[str, Dict[str, float | int]] = Field(default_factory=dict)
    by_strategy: Dict[str, Dict[str, float | int]] = Field(default_factory=dict)
    by_regime: Dict[str, Dict[str, float | int]] = Field(default_factory=dict)
    observations: List[ExecutionCostObservationResult] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def _adverse_price_delta(side: str, reference_price: float, fill_price: float) -> float:
    # Positive means worse execution; negative means price improvement.
    return (
        fill_price - reference_price
        if side == "buy"
        else reference_price - fill_price
    )


def _bps(delta: float, reference_price: float) -> float:
    return (delta / reference_price) * 10_000.0


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _aggregate(
    rows: List[ExecutionCostObservationResult],
    dimension: str,
) -> Dict[str, Dict[str, float | int]]:
    grouped: dict[str, list[ExecutionCostObservationResult]] = defaultdict(list)
    for row in rows:
        grouped[str(getattr(row, dimension) or "unknown")].append(row)

    output: Dict[str, Dict[str, float | int]] = {}
    for key, group in sorted(grouped.items()):
        notional = sum(row.decision_notional for row in group)
        slippage_cost = sum(row.slippage_cost for row in group)
        fees = sum(row.fees for row in group)
        all_in = sum(row.all_in_execution_cost for row in group)
        output[key] = {
            "observation_count": len(group),
            "decision_notional": round(notional, 6),
            "slippage_cost": round(slippage_cost, 6),
            "fees": round(fees, 6),
            "all_in_execution_cost": round(all_in, 6),
            "weighted_price_slippage_bps": round(
                (slippage_cost / notional) * 10_000.0 if notional else 0.0,
                6,
            ),
            "weighted_all_in_cost_bps": round(
                (all_in / notional) * 10_000.0 if notional else 0.0,
                6,
            ),
        }
    return output


def build_execution_cost_attribution(
    payload: ExecutionCostAttributionRequest,
) -> ExecutionCostAttributionSummary:
    rows: List[ExecutionCostObservationResult] = []
    warnings: List[str] = []

    for observation in payload.observations:
        price_delta = _adverse_price_delta(
            observation.side,
            observation.decision_price,
            observation.fill_price,
        )
        price_slippage_bps = _bps(price_delta, observation.decision_price)
        submitted_slippage_bps = None
        if observation.submitted_price is not None:
            submitted_delta = _adverse_price_delta(
                observation.side,
                observation.submitted_price,
                observation.fill_price,
            )
            submitted_slippage_bps = _bps(
                submitted_delta,
                observation.submitted_price,
            )

        decision_notional = observation.quantity * observation.decision_price
        slippage_cost = price_delta * observation.quantity
        all_in_cost = slippage_cost + observation.fees
        all_in_cost_bps = (all_in_cost / decision_notional) * 10_000.0
        rows.append(
            ExecutionCostObservationResult(
                symbol=observation.symbol,
                side=observation.side,
                quantity=observation.quantity,
                decision_price=observation.decision_price,
                submitted_price=observation.submitted_price,
                fill_price=observation.fill_price,
                decision_notional=round(decision_notional, 8),
                price_slippage_per_share=round(price_delta, 8),
                price_slippage_bps=round(price_slippage_bps, 8),
                submitted_to_fill_slippage_bps=(
                    round(submitted_slippage_bps, 8)
                    if submitted_slippage_bps is not None
                    else None
                ),
                slippage_cost=round(slippage_cost, 8),
                fees=observation.fees,
                all_in_execution_cost=round(all_in_cost, 8),
                all_in_cost_bps=round(all_in_cost_bps, 8),
                strategy=observation.strategy,
                regime=observation.regime,
                order_id=(
                    str(observation.order_id)
                    if observation.order_id is not None
                    else None
                ),
                trade_plan_id=observation.trade_plan_id,
                correlation_id=observation.correlation_id,
                spread_bps_at_decision=observation.spread_bps_at_decision,
            )
        )

    total_notional = sum(row.decision_notional for row in rows)
    total_slippage = sum(row.slippage_cost for row in rows)
    total_fees = sum(row.fees for row in rows)
    total_cost = total_slippage + total_fees
    price_bps = [row.price_slippage_bps for row in rows]
    all_in_bps = [row.all_in_cost_bps for row in rows]
    observation_count = len(rows)
    floor_ready = observation_count >= payload.minimum_observations_for_stress_floor

    if not rows:
        warnings.append("No execution observations were provided")
    if not floor_ready:
        warnings.append(
            "Insufficient execution observations to publish a backtest cost floor"
        )
    if rows and all(row.submitted_price is None for row in rows):
        warnings.append(
            "submitted_price is unavailable for all observations; "
            "decision-to-fill cost remains usable"
        )

    p95_price = _percentile(price_bps, 0.95)
    p95_all_in = _percentile(all_in_bps, 0.95)
    return ExecutionCostAttributionSummary(
        observation_count=observation_count,
        total_decision_notional=round(total_notional, 6),
        total_slippage_cost=round(total_slippage, 6),
        total_fees=round(total_fees, 6),
        total_execution_cost=round(total_cost, 6),
        weighted_price_slippage_bps=round(
            (total_slippage / total_notional) * 10_000.0 if total_notional else 0.0,
            6,
        ),
        weighted_all_in_cost_bps=round(
            (total_cost / total_notional) * 10_000.0 if total_notional else 0.0,
            6,
        ),
        price_improvement_count=sum(row.price_slippage_bps < 0 for row in rows),
        adverse_slippage_count=sum(row.price_slippage_bps > 0 for row in rows),
        median_price_slippage_bps=(
            round(_percentile(price_bps, 0.50) or 0.0, 6) if rows else None
        ),
        p90_price_slippage_bps=(
            round(_percentile(price_bps, 0.90) or 0.0, 6) if rows else None
        ),
        p95_price_slippage_bps=(
            round(p95_price, 6) if p95_price is not None else None
        ),
        p95_all_in_cost_bps=(
            round(p95_all_in, 6) if p95_all_in is not None else None
        ),
        suggested_backtest_slippage_bps_floor=(
            round(max(0.0, p95_price), 6)
            if floor_ready and p95_price is not None
            else None
        ),
        suggested_backtest_all_in_cost_bps_floor=(
            round(max(0.0, p95_all_in), 6)
            if floor_ready and p95_all_in is not None
            else None
        ),
        stress_floor_ready=floor_ready,
        by_symbol=_aggregate(rows, "symbol"),
        by_strategy=_aggregate(rows, "strategy"),
        by_regime=_aggregate(rows, "regime"),
        observations=rows,
        warnings=warnings,
    )
