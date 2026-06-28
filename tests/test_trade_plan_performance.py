from fastapi.testclient import TestClient

from app.main import app
from app.models import TradePlanFill, TradePlanLifecycleRecord, TradePlanPerformanceRequest
from app.service import build_trade_plan_performance_summary

client = TestClient(app)


def plan(plan_id, symbol="AAPL", bucket="value_rebound", status="filled", entry=100, side="buy"):
    return TradePlanLifecycleRecord(
        trade_plan_id=plan_id,
        account_id="1",
        symbol=symbol,
        side=side,
        status=status,
        strategy="trend_pullback",
        strategy_bucket=bucket,
        risk_approval_id=f"risk-{plan_id}",
        order_id=int(plan_id.split("-")[-1]) if plan_id.split("-")[-1].isdigit() else None,
        plan={
            "plan_id": plan_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "quantity": 10,
        },
    )


def fill(plan_id, symbol="AAPL", price=110, qty=10, realized_pnl=None, fees=0):
    return TradePlanFill(
        trade_plan_id=plan_id,
        symbol=symbol,
        side="buy",
        quantity=qty,
        fill_price=price,
        realized_pnl=realized_pnl,
        fees=fees,
    )


def test_trade_plan_performance_summary_uses_realized_pnl_when_available():
    request = TradePlanPerformanceRequest(
        initial_equity=10_000,
        period="30d",
        trade_plans=[
            plan("plan-1", bucket="value_rebound"),
            plan("plan-2", symbol="MSFT", bucket="news_momentum"),
        ],
        fills=[
            fill("plan-1", realized_pnl=100),
            fill("plan-2", symbol="MSFT", realized_pnl=-40),
        ],
    )

    summary = build_trade_plan_performance_summary(request)

    assert summary.trade_plan_count == 2
    assert summary.closed_plan_count == 2
    assert summary.open_plan_count == 0
    assert summary.winning_plans == 1
    assert summary.losing_plans == 1
    assert summary.win_rate == 0.5
    assert summary.gross_profit == 100
    assert summary.gross_loss == -40
    assert summary.net_pnl == 60
    assert summary.return_pct == 0.006
    assert summary.expectancy == 30
    assert summary.profit_factor == 2.5
    assert summary.best_strategy_bucket == "value_rebound"
    assert summary.worst_strategy_bucket == "news_momentum"
    assert summary.by_strategy_bucket["value_rebound"]["net_pnl"] == 100
    assert summary.by_symbol["MSFT"]["net_pnl"] == -40


def test_trade_plan_performance_summary_computes_pnl_from_entry_and_fill():
    request = TradePlanPerformanceRequest(
        initial_equity=10_000,
        trade_plans=[plan("plan-1", entry=100)],
        fills=[fill("plan-1", price=108, qty=5, fees=2)],
    )

    summary = build_trade_plan_performance_summary(request)

    assert summary.net_pnl == 38
    assert summary.plan_results[0]["pnl_source"] == "computed_from_entry_and_fills"
    assert summary.plan_results[0]["quantity"] == 5


def test_trade_plan_performance_summary_matches_fills_by_order_id():
    request = TradePlanPerformanceRequest(
        initial_equity=10_000,
        trade_plans=[plan("plan-1", entry=100)],
        fills=[TradePlanFill(order_id=1, symbol="AAPL", side="buy", quantity=10, fill_price=112, fees=1)],
    )

    summary = build_trade_plan_performance_summary(request)

    assert summary.net_pnl == 119
    assert summary.plan_results[0]["fill_count"] == 1
    assert summary.plan_results[0]["pnl_source"] == "computed_from_entry_and_fills"


def test_trade_plan_performance_summary_handles_open_and_unmatched_fills():
    request = TradePlanPerformanceRequest(
        initial_equity=10_000,
        trade_plans=[plan("plan-1", status="risk_approved")],
        fills=[TradePlanFill(symbol="AAPL", quantity=1, fill_price=100)],
    )

    summary = build_trade_plan_performance_summary(request)

    assert summary.trade_plan_count == 1
    assert summary.closed_plan_count == 0
    assert summary.open_plan_count == 1
    assert summary.win_rate == 0
    assert "1 fill(s) could not be matched to a TradePlan" in summary.warnings


def test_trade_plan_performance_endpoint():
    response = client.post(
        "/performance/trade-plans/summary",
        json={
            "initial_equity": 10000,
            "period": "30d",
            "trade_plans": [
                {
                    "trade_plan_id": "plan-1",
                    "account_id": "1",
                    "symbol": "AAPL",
                    "side": "buy",
                    "status": "filled",
                    "strategy": "trend_pullback",
                    "strategy_bucket": "value_rebound",
                    "plan": {"entry_price": 100, "quantity": 10},
                }
            ],
            "fills": [
                {
                    "trade_plan_id": "plan-1",
                    "symbol": "AAPL",
                    "side": "buy",
                    "quantity": 10,
                    "fill_price": 110,
                    "fees": 0,
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["trade_plan_count"] == 1
    assert payload["data"]["net_pnl"] == 100


def test_database_trade_plan_summary_endpoint(monkeypatch):
    class FakeDatabaseClient:
        def list_trade_plans(self, query):
            assert query.account_id == "1"
            assert query.symbol == "AAPL"
            assert query.status == "filled"
            return [plan("plan-1", symbol="AAPL", status="filled", entry=100)]

        def list_fills(self, account_id, symbol=None, limit=500):
            assert account_id == "1"
            assert symbol == "AAPL"
            return [TradePlanFill(order_id=1, symbol="AAPL", side="buy", quantity=10, fill_price=111)]

    monkeypatch.setattr("app.main.DatabaseAgentClient", FakeDatabaseClient)

    response = client.get(
        "/performance/trade-plans/database-summary?initial_equity=10000&period=30d&account_id=1&symbol=AAPL&status=filled"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["trade_plan_count"] == 1
    assert payload["data"]["net_pnl"] == 110
    assert payload["metadata"]["source"] == "database-agent"
    assert payload["metadata"]["trade_plan_count_fetched"] == 1
    assert payload["metadata"]["fill_count_fetched"] == 1


def test_database_trade_plan_summary_without_account_id_skips_fills(monkeypatch):
    class FakeDatabaseClient:
        def list_trade_plans(self, query):
            return [plan("plan-1", symbol="AAPL", status="filled", entry=100)]

        def list_fills(self, account_id, symbol=None, limit=500):
            raise AssertionError("fills should not be fetched without account_id")

    monkeypatch.setattr("app.main.DatabaseAgentClient", FakeDatabaseClient)

    response = client.get("/performance/trade-plans/database-summary?initial_equity=10000&include_fills=true")

    assert response.status_code == 200
    payload = response.json()
    assert "Fills were not fetched because account_id was not provided" in payload["data"]["warnings"]
    assert payload["metadata"]["fill_count_fetched"] == 0
