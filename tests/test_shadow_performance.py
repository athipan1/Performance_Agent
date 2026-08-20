from fastapi.testclient import TestClient

from app.main import app
from app.shadow_performance import (
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


def test_shadow_summary_reports_net_expectancy_mfe_mae_and_profit_factor():
    payload = ShadowPerformanceRequest(
        outcomes=[
            _outcome(1, 0.03),
            _outcome(2, -0.01),
            _outcome(3, 0.02),
        ],
        minimum_observations_for_paper_review=3,
    )

    summary = build_shadow_performance(payload)

    assert summary.observation_count == 3
    assert summary.net_expectancy_pct > 0
    assert summary.average_mfe_pct is not None
    assert summary.average_mae_pct == -0.01
    assert summary.profit_factor == 5.0
    assert summary.max_drawdown_pct is not None
    assert summary.paper_review_ready is True
    assert summary.advisory_only is True
    assert summary.broker_order_authorized is False


def test_shadow_summary_withholds_paper_review_when_sample_is_too_small():
    summary = build_shadow_performance(
        ShadowPerformanceRequest(
            outcomes=[_outcome(1, 0.03)],
            minimum_observations_for_paper_review=50,
        )
    )

    assert summary.paper_review_ready is False
    assert "shadow_observations_below_paper_review_threshold" in summary.warnings


def test_shadow_http_endpoint_marks_evidence_as_non_broker():
    client = TestClient(app)
    response = client.post(
        "/performance/shadow",
        json={
            "minimum_observations_for_paper_review": 1,
            "outcomes": [_outcome(1, 0.02).model_dump(mode="json")],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["paper_review_ready"] is True
    assert body["data"]["broker_order_authorized"] is False
    assert body["metadata"]["broker_fill_evidence"] is False
    assert body["metadata"]["advisory_only"] is True
