from app.forward_evidence import build_forward_evidence


def test_forward_evidence_requires_sample_quality_drawdown_and_costs():
    result = build_forward_evidence(
        {
            "observation_count": 100,
            "net_expectancy_pct": 0.004,
            "profit_factor": 1.25,
            "max_drawdown_pct": 0.06,
            "average_cost_pct": 0.0004,
        }
    )
    assert result["forward_review_ready"] is True
    assert result["failed_gates"] == []
    assert result["broker_order_authorized"] is False


def test_forward_evidence_fails_closed_below_100_observations():
    result = build_forward_evidence(
        {
            "observation_count": 99,
            "net_expectancy_pct": 0.01,
            "profit_factor": 1.5,
            "max_drawdown_pct": 0.04,
            "average_cost_pct": 0.0002,
        }
    )
    assert result["forward_review_ready"] is False
    assert "minimum_observations" in result["failed_gates"]


def test_forward_evidence_blocks_weak_profit_factor_and_drawdown():
    result = build_forward_evidence(
        {
            "observation_count": 150,
            "net_expectancy_pct": 0.01,
            "profit_factor": 0.9,
            "max_drawdown_pct": 0.15,
            "average_cost_pct": 0.0002,
        }
    )
    assert result["forward_review_ready"] is False
    assert "profit_factor" in result["failed_gates"]
    assert "max_drawdown" in result["failed_gates"]
