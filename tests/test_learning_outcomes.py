from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    LearningOutcomeBuildRequest,
    TradePlanFill,
    TradePlanLifecycleRecord,
)
from app.outcome_builder import build_learning_outcomes


client = TestClient(app)


VERSIONS = {
    "scanner": "scanner-bucket-hints-v2",
    "fundamental": "fundamental-evidence-v1",
    "technical": "technical-evidence-v1",
}


def _plan_payload(
    *,
    bucket="value_rebound",
    execution_bucket=None,
    status="closed",
    evidence_versions=None,
):
    execution_bucket = execution_bucket or bucket
    versions = evidence_versions or dict(VERSIONS)
    return {
        "entry_price": 100,
        "quantity": 10,
        "strategy_bucket": bucket,
        "strategy_bucket_classification": {
            "bucket": bucket,
            "confidence": 0.84,
            "status": "classified",
            "classifier_version": "manager-strategy-bucket-v3",
            "evidence_gate_passed": True,
            "reasons": [
                "low_pe_ratio:12",
                "valuation_score:0.90",
            ],
        },
        "evidence_summary": {
            "contract": "manager-analysis-evidence-v1",
            "gate_passed": True,
            "evidence_versions": versions,
            "evidence_statuses": {
                "scanner": "suggested",
                "fundamental": "complete",
                "technical": "complete",
            },
            "classification_inputs": {
                "scanner": {
                    "primary_hint": bucket,
                    "primary_confidence": 0.82,
                },
                "fundamental": {
                    "quality_score": 0.72,
                    "valuation_score": 0.90,
                    "pe_ratio": 12,
                },
                "technical": {
                    "technical_score": 0.60,
                    "momentum_score": 0.55,
                },
            },
        },
        "execution": {
            "execution_strategy_bucket": execution_bucket,
            "execution_status": status,
        },
    }


def _plan(
    plan_id="plan-1",
    *,
    bucket="value_rebound",
    execution_bucket=None,
    status="closed",
    evidence_versions=None,
):
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closed = opened + timedelta(days=10)
    return TradePlanLifecycleRecord(
        trade_plan_id=plan_id,
        account_id="paper-1",
        symbol="CINF",
        side="buy",
        status=status,
        strategy="value_rebound",
        strategy_bucket=bucket,
        risk_approval_id=f"risk-{plan_id}",
        order_id=1,
        plan=_plan_payload(
            bucket=bucket,
            execution_bucket=execution_bucket,
            status=status,
            evidence_versions=evidence_versions,
        ),
        metadata={
            "execution_strategy_bucket": execution_bucket or bucket,
            "execution_status": status,
            "exit_reason": "profit_target",
        },
        created_at=opened,
        updated_at=closed,
        closed_at=closed,
    )


def _fill(
    plan_id="plan-1",
    *,
    realized_pnl=100.0,
    price=110.0,
):
    return TradePlanFill(
        trade_plan_id=plan_id,
        order_id=1,
        symbol="CINF",
        side="sell",
        quantity=10,
        fill_price=price,
        fees=1,
        realized_pnl=realized_pnl,
        filled_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
    )


def test_build_learning_outcome_matches_learning_contract():
    batch = build_learning_outcomes(
        LearningOutcomeBuildRequest(
            trade_plans=[_plan()],
            fills=[_fill()],
        )
    )

    assert batch.performance_contract_version == "performance-outcome-v1"
    assert batch.learning_contract_version == "learning-outcome-v1"
    assert batch.generated_outcomes == 1
    assert batch.rejected_trade_plans == 0

    outcome = batch.outcomes[0]
    assert outcome.outcome_id == "performance:plan-1:realized"
    assert outcome.strategy_bucket == "value_rebound"
    assert outcome.manager_bucket == "value_rebound"
    assert outcome.execution_bucket == "value_rebound"
    assert outcome.database_bucket == "value_rebound"
    assert outcome.manager_classifier_version == (
        "manager-strategy-bucket-v3"
    )
    assert outcome.evidence_versions == {
        **VERSIONS,
        "manager": "manager-analysis-evidence-v1",
    }
    assert outcome.entry_price == 100
    assert outcome.exit_price == 110
    assert outcome.realized_pnl == 100
    assert outcome.return_pct == 0.1
    assert outcome.holding_period_days == 10
    assert outcome.exit_reason == "profit_target"
    assert outcome.risk_approved is True
    assert outcome.outcome_status == "closed"
    assert outcome.pnl_status == "realized"
    assert outcome.evidence_contributions["scanner"].supported_bucket == (
        "value_rebound"
    )
    assert outcome.evidence_contributions["fundamental"].supported_bucket == (
        "value_rebound"
    )
    assert outcome.evidence_contributions["technical"].supported_bucket is None
    assert outcome.evidence_contributions["manager"].supported_bucket == (
        "value_rebound"
    )
    assert batch.requires_human_review is True
    assert batch.auto_apply is False


def test_bucket_mismatch_is_rejected_not_silently_normalized():
    batch = build_learning_outcomes(
        LearningOutcomeBuildRequest(
            trade_plans=[
                _plan(
                    bucket="value_rebound",
                    execution_bucket="news_momentum",
                )
            ],
            fills=[_fill()],
        )
    )

    assert batch.generated_outcomes == 0
    issues = batch.rejected_records[0]["issues"]
    assert any(
        issue.startswith("strategy_bucket_mismatch")
        for issue in issues
    )


def test_missing_realized_pnl_is_rejected():
    batch = build_learning_outcomes(
        LearningOutcomeBuildRequest(
            trade_plans=[_plan()],
            fills=[_fill(realized_pnl=None)],
        )
    )

    assert batch.generated_outcomes == 0
    assert "realized_pnl_missing" in batch.rejected_records[0]["issues"]
    assert "exit_price_missing" in batch.rejected_records[0]["issues"]


def test_cancelled_trade_plan_is_not_learnable_even_with_pnl():
    batch = build_learning_outcomes(
        LearningOutcomeBuildRequest(
            trade_plans=[_plan(status="cancelled")],
            fills=[_fill()],
        )
    )

    assert batch.generated_outcomes == 0
    assert "execution_not_complete:cancelled" in (
        batch.rejected_records[0]["issues"]
    )


def test_unsupported_evidence_version_is_rejected():
    versions = dict(VERSIONS)
    versions["technical"] = "technical-evidence-v999"
    batch = build_learning_outcomes(
        LearningOutcomeBuildRequest(
            trade_plans=[_plan(evidence_versions=versions)],
            fills=[_fill()],
        )
    )

    assert batch.generated_outcomes == 0
    assert (
        "unsupported_technical_evidence_version:technical-evidence-v999"
        in batch.rejected_records[0]["issues"]
    )


def test_duplicate_trade_plan_is_rejected_once():
    plan = _plan()
    duplicate = deepcopy(plan)
    batch = build_learning_outcomes(
        LearningOutcomeBuildRequest(
            trade_plans=[plan, duplicate],
            fills=[_fill()],
        )
    )

    assert batch.generated_outcomes == 1
    assert batch.rejected_trade_plans == 1
    assert batch.rejected_records[0]["issues"] == [
        "duplicate_trade_plan_id"
    ]


def test_learning_outcomes_endpoint_preserves_correlation_id():
    response = client.post(
        "/performance/learning-outcomes",
        json={
            "trade_plans": [_plan().model_dump(mode="json")],
            "fills": [_fill().model_dump(mode="json")],
        },
        headers={"X-Correlation-ID": "performance-outcome-test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["version"] == "0.4.0"
    assert payload["correlation_id"] == "performance-outcome-test"
    assert payload["data"]["generated_outcomes"] == 1
    assert payload["metadata"]["performance_contract_version"] == (
        "performance-outcome-v1"
    )
    assert payload["metadata"]["requires_human_review"] is True
    assert payload["metadata"]["auto_apply"] is False


def test_database_learning_outcomes_endpoint(monkeypatch):
    class FakeDatabaseClient:
        def list_trade_plans(self, query):
            assert query.account_id == "paper-1"
            assert query.symbol == "CINF"
            return [_plan()]

        def list_fills(self, account_id, symbol=None, limit=500):
            assert account_id == "paper-1"
            assert symbol == "CINF"
            return [_fill()]

    monkeypatch.setattr("app.main.DatabaseAgentClient", FakeDatabaseClient)

    response = client.get(
        "/performance/learning-outcomes/database"
        "?account_id=paper-1&symbol=CINF",
        headers={"X-Correlation-ID": "database-outcome-test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["correlation_id"] == "database-outcome-test"
    assert payload["data"]["generated_outcomes"] == 1
    assert payload["data"]["outcomes"][0]["symbol"] == "CINF"
    assert payload["metadata"]["source"] == "database-agent"
    assert payload["metadata"]["trade_plan_count_fetched"] == 1
    assert payload["metadata"]["fill_count_fetched"] == 1
