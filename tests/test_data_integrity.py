import httpx
import pytest
from pydantic import ValidationError

from app.database_client import DatabaseAgentClient
from app.models import (
    TradePlanFill,
    TradePlanLifecycleRecord,
    TradePlanPerformanceRequest,
)
from app.service import build_trade_plan_performance_summary


def _fill_row(fill_id, plan_id, order_id, pnl):
    return {
        "trade_plan_id": plan_id,
        "order_id": order_id,
        "trade_id": f"trade-{fill_id}",
        "symbol": "AAPL",
        "side": "sell",
        "quantity": 1,
        "fill_price": 110,
        "realized_pnl": pnl,
        "filled_at": "2026-01-02T00:00:00Z",
        "metadata": {"fill_id": fill_id},
    }


def test_database_client_paginates_and_deduplicates_fills(monkeypatch):
    original_client = httpx.Client
    requested_offsets = []
    first = _fill_row("fill-1", "plan-1", 1, 10)
    second = _fill_row("fill-2", "plan-1", 1, 20)
    third = _fill_row("fill-3", "plan-1", 1, 30)

    def handler(request):
        offset = int(request.url.params.get("offset", "0"))
        requested_offsets.append(offset)
        rows = [first, first, second] if offset == 0 else [third]
        return httpx.Response(
            200,
            json={"status": "success", "data": rows},
        )

    class FakeClient:
        def __init__(self, timeout=None, headers=None):
            self.inner = original_client(
                transport=httpx.MockTransport(handler),
                base_url="http://db",
            )

        def __enter__(self):
            return self.inner

        def __exit__(self, exc_type, exc, tb):
            self.inner.close()
            return False

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = DatabaseAgentClient(base_url="http://db", api_key="key")

    fills = client.list_fills(account_id="paper-1", limit=3)

    assert requested_offsets == [0, 3]
    assert len(fills) == 3
    assert [fill.realized_pnl for fill in fills] == [10, 20, 30]


def _plan(plan_id, order_id):
    return TradePlanLifecycleRecord(
        trade_plan_id=plan_id,
        account_id="paper-1",
        symbol="AAPL",
        status="closed",
        strategy_bucket="value_rebound",
        order_id=order_id,
        plan={"entry_price": 100, "quantity": 1},
    )


def test_summary_excludes_duplicate_orphan_and_conflicting_fills():
    valid_one = TradePlanFill(
        trade_plan_id="plan-1",
        order_id=1,
        symbol="AAPL",
        quantity=1,
        fill_price=110,
        realized_pnl=100,
        metadata={"fill_id": "valid-one"},
    )
    duplicate = valid_one.model_copy(deep=True)
    valid_two = TradePlanFill(
        trade_plan_id="plan-2",
        order_id=2,
        symbol="AAPL",
        quantity=1,
        fill_price=95,
        realized_pnl=-50,
        metadata={"fill_id": "valid-two"},
    )
    orphan = TradePlanFill(
        trade_plan_id="unknown-plan",
        order_id=99,
        symbol="AAPL",
        quantity=1,
        fill_price=999,
        realized_pnl=999,
        metadata={"fill_id": "orphan"},
    )
    conflict = TradePlanFill(
        trade_plan_id="plan-1",
        order_id=2,
        symbol="AAPL",
        quantity=1,
        fill_price=999,
        realized_pnl=999,
        metadata={"fill_id": "conflict"},
    )

    summary = build_trade_plan_performance_summary(
        TradePlanPerformanceRequest(
            initial_equity=10000,
            trade_plans=[_plan("plan-1", 1), _plan("plan-2", 2)],
            fills=[valid_one, duplicate, valid_two, orphan, conflict],
        )
    )

    assert summary.net_pnl == 50
    assert summary.plan_results[0]["fill_count"] == 1
    assert summary.plan_results[1]["fill_count"] == 1
    assert "1 duplicate fill(s) were excluded" in summary.warnings
    assert "1 orphan fill(s) were excluded" in summary.warnings
    assert (
        "1 fill(s) matched multiple TradePlans and were excluded"
        in summary.warnings
    )


def test_unknown_evidence_status_is_rejected():
    with pytest.raises(ValidationError, match="scanner=pending"):
        TradePlanLifecycleRecord(
            trade_plan_id="plan-1",
            account_id="paper-1",
            symbol="AAPL",
            plan={
                "evidence_summary": {
                    "evidence_statuses": {
                        "scanner": "pending",
                        "fundamental": "complete",
                        "technical": "complete",
                    }
                }
            },
        )


def test_supported_evidence_statuses_are_accepted():
    plan = TradePlanLifecycleRecord(
        trade_plan_id="plan-1",
        account_id="paper-1",
        symbol="AAPL",
        plan={
            "evidence_summary": {
                "evidence_statuses": {
                    "scanner": "suggested",
                    "fundamental": "complete",
                    "technical": "complete",
                }
            }
        },
    )

    assert plan.trade_plan_id == "plan-1"
