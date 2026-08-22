from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.shadow_performance import (
    MINIMUM_SHADOW_OBSERVATIONS_FOR_PROMOTION,
    ShadowPerformanceRequest,
    ShadowTradeOutcome,
    build_shadow_performance,
)


def _outcome(index: int, net: float, strategy="trend_following", regime="bull"):
    return ShadowTradeOutcome(
        shadow_trade_id=f"shadow-{index}",
        symbol="NVDA",
        strategy=strategy,
        regime=regime,
        mfe_pct=max(net, 0.02),
        mae_pct=-0.01,
        gross_return_pct=net + 0.001,
        estimated_cost_pct=0.001,
        net_return_pct=net,
        holding_period_seconds=3600,
    )


def test_small_sample_reports_metrics_but_not_paper_review_ready():
    summary = build_shadow_performance(
        ShadowPerformanceRequest(
            outcomes=[
                _outcome(1, 0.03),
                _outcome(2, -0.01),
                _outcome(3, 0.02),
            ]
        )
    )

    assert summary.observation_count == 3
    assert summary.minimum_observations_for_paper_review == 100
    assert summary.net_expectancy_pct > 0
    assert summary.average_mfe_pct is not None
    assert summary.average_mae_pct == -0.01
    assert summary.profit_factor == 5.0
    assert summary.expectancy_eligible_for_promotion is False
    assert summary.promotion_net_expectancy_pct is None
    assert summary.paper_review_ready is False
    assert "shadow_expectancy_withheld_from_promotion" in summary.warnings
    assert summary.advisory_only is True
    assert summary.broker_order_authorized is False


def test_100_closed_outcomes_make_expectancy_eligible_for_review():
    outcomes = [
        _outcome(index, 0.012 if index % 4 else -0.004)
        for index in range(1, 101)
    ]
    summary = build_shadow_performance(
        ShadowPerformanceRequest(
            outcomes=outcomes,
            minimum_observations_for_paper_review=100,
        )
    )

    assert summary.observation_count == 100
    assert summary.expectancy_eligible_for_promotion is True
    assert summary.promotion_net_expectancy_pct is not None
    assert summary.promotion_net_expectancy_pct > 0
    assert summary.paper_review_ready is True


def test_shadow_threshold_cannot_be_lowered_below_100():
    try:
        ShadowPerformanceRequest(
            outcomes=[],
            minimum_observations_for_paper_review=99,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("shadow threshold accepted fewer than 100 observations")

    assert MINIMUM_SHADOW_OBSERVATIONS_FOR_PROMOTION == 100


def test_shadow_http_endpoint_keeps_small_sample_non_broker_and_not_ready():
    client = TestClient(app)
    response = client.post(
        "/performance/shadow",
        json={
            "minimum_observations_for_paper_review": 100,
            "outcomes": [_outcome(1, 0.02).model_dump(mode="json")],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["paper_review_ready"] is False
    assert body["data"]["expectancy_eligible_for_promotion"] is False
    assert body["data"]["promotion_net_expectancy_pct"] is None
    assert body["data"]["broker_order_authorized"] is False
    assert body["metadata"]["broker_fill_evidence"] is False
    assert body["metadata"]["advisory_only"] is True
