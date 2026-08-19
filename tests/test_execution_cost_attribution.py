from fastapi.testclient import TestClient

from app.execution_cost import (
    ExecutionCostAttributionRequest,
    ExecutionFillObservation,
    build_execution_cost_attribution,
)
from app.main import app


def _observation(**overrides):
    values = {
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 10,
        "decision_price": 100.0,
        "submitted_price": 100.02,
        "fill_price": 100.10,
        "fees": 0.25,
        "strategy": "trend_following",
        "regime": "bull",
        "order_id": "order-1",
        "trade_plan_id": "plan-1",
        "correlation_id": "corr-1",
        "spread_bps_at_decision": 4.0,
    }
    values.update(overrides)
    return ExecutionFillObservation(**values)


def test_buy_slippage_is_positive_when_fill_is_worse():
    summary = build_execution_cost_attribution(
        ExecutionCostAttributionRequest(
            observations=[_observation()],
            minimum_observations_for_stress_floor=1,
        )
    )

    row = summary.observations[0]
    assert row.price_slippage_per_share == 0.1
    assert row.price_slippage_bps == 10.0
    assert row.slippage_cost == 1.0
    assert row.all_in_execution_cost == 1.25
    assert row.all_in_cost_bps == 12.5
    assert row.submitted_to_fill_slippage_bps > 0
    assert summary.adverse_slippage_count == 1
    assert summary.price_improvement_count == 0


def test_sell_slippage_direction_is_reversed_and_price_improvement_is_negative_cost():
    summary = build_execution_cost_attribution(
        ExecutionCostAttributionRequest(
            observations=[
                _observation(
                    side="sell",
                    decision_price=100.0,
                    submitted_price=100.05,
                    fill_price=100.20,
                    fees=0.0,
                )
            ],
            minimum_observations_for_stress_floor=1,
        )
    )

    row = summary.observations[0]
    assert row.price_slippage_per_share == -0.2
    assert row.price_slippage_bps == -20.0
    assert row.slippage_cost == -2.0
    assert summary.price_improvement_count == 1
    assert summary.adverse_slippage_count == 0
    assert summary.suggested_backtest_slippage_bps_floor == 0.0


def test_weighted_cost_and_dimensions_are_attributed_by_symbol_strategy_and_regime():
    summary = build_execution_cost_attribution(
        ExecutionCostAttributionRequest(
            observations=[
                _observation(symbol="AAPL", quantity=10, fill_price=100.10),
                _observation(
                    symbol="MSFT",
                    quantity=20,
                    decision_price=200.0,
                    submitted_price=200.0,
                    fill_price=200.20,
                    strategy="breakout",
                    regime="volatile",
                    fees=0.5,
                ),
            ],
            minimum_observations_for_stress_floor=2,
        )
    )

    assert summary.observation_count == 2
    assert set(summary.by_symbol) == {"AAPL", "MSFT"}
    assert set(summary.by_strategy) == {"trend_following", "breakout"}
    assert set(summary.by_regime) == {"bull", "volatile"}
    assert summary.total_decision_notional == 5000.0
    assert summary.total_slippage_cost == 5.0
    assert summary.total_fees == 0.75
    assert summary.total_execution_cost == 5.75
    assert summary.weighted_price_slippage_bps == 10.0
    assert summary.weighted_all_in_cost_bps == 11.5
    assert summary.stress_floor_ready is True


def test_stress_floor_is_withheld_until_enough_paper_observations_exist():
    summary = build_execution_cost_attribution(
        ExecutionCostAttributionRequest(
            observations=[_observation()],
            minimum_observations_for_stress_floor=20,
        )
    )

    assert summary.stress_floor_ready is False
    assert summary.suggested_backtest_slippage_bps_floor is None
    assert summary.suggested_backtest_all_in_cost_bps_floor is None
    assert any("Insufficient execution observations" in warning for warning in summary.warnings)


def test_p95_floor_uses_adverse_tail_not_average_only():
    observations = []
    for index in range(20):
        observations.append(
            _observation(
                order_id=f"order-{index}",
                fill_price=100.01 if index < 19 else 100.50,
                fees=0.0,
            )
        )
    summary = build_execution_cost_attribution(
        ExecutionCostAttributionRequest(
            observations=observations,
            minimum_observations_for_stress_floor=20,
        )
    )

    assert summary.stress_floor_ready is True
    assert summary.p95_price_slippage_bps is not None
    assert summary.p95_price_slippage_bps > 10.0
    assert summary.suggested_backtest_slippage_bps_floor == summary.p95_price_slippage_bps


def test_empty_batch_is_safe_and_never_publishes_cost_floor():
    summary = build_execution_cost_attribution(ExecutionCostAttributionRequest())
    assert summary.observation_count == 0
    assert summary.total_execution_cost == 0.0
    assert summary.stress_floor_ready is False
    assert summary.suggested_backtest_slippage_bps_floor is None
    assert "No execution observations were provided" in summary.warnings


def test_endpoint_preserves_correlation_and_is_advisory_only():
    client = TestClient(app)
    response = client.post(
        "/performance/execution-costs",
        headers={"X-Correlation-ID": "cost-corr-123"},
        json={
            "minimum_observations_for_stress_floor": 1,
            "observations": [
                {
                    "symbol": "aapl",
                    "side": "buy",
                    "quantity": 10,
                    "decision_price": 100,
                    "fill_price": 100.1,
                    "fees": 0.25,
                    "strategy": "Trend_Following",
                    "regime": "BULL",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["correlation_id"] == "cost-corr-123"
    assert payload["metadata"]["advisory_only"] is True
    assert payload["metadata"]["stress_floor_ready"] is True
    assert payload["data"]["schema_version"] == "execution-cost-attribution.v1"
    assert payload["data"]["observations"][0]["symbol"] == "AAPL"
    assert payload["data"]["observations"][0]["strategy"] == "trend_following"
