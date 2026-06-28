import httpx

from app.database_client import DatabaseAgentClient
from app.models import DatabaseTradePlanSummaryQuery


def test_database_client_lists_trade_plans(monkeypatch):
    captured = {}
    original_client = httpx.Client

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "trade_plan_id": "plan-1",
                        "account_id": "1",
                        "symbol": "AAPL",
                        "side": "buy",
                        "status": "filled",
                        "strategy_bucket": "value_rebound",
                        "plan": {"entry_price": 100},
                    }
                ],
            },
        )

    class FakeClient:
        def __init__(self, timeout=None, headers=None):
            self.inner = original_client(transport=httpx.MockTransport(handler), base_url="http://db")

        def __enter__(self):
            return self.inner

        def __exit__(self, exc_type, exc, tb):
            self.inner.close()
            return False

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = DatabaseAgentClient(base_url="http://db", api_key="key")
    plans = client.list_trade_plans(
        DatabaseTradePlanSummaryQuery(
            initial_equity=10_000,
            account_id="1",
            symbol="AAPL",
            status="filled",
            strategy_bucket="value_rebound",
        )
    )

    assert plans[0].trade_plan_id == "plan-1"
    assert "account_id=1" in captured["url"]
    assert "symbol=AAPL" in captured["url"]


def test_database_client_maps_fills(monkeypatch):
    original_client = httpx.Client

    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "order_id": 42,
                        "trade_id": "trade-42",
                        "symbol": "AAPL",
                        "side": "buy",
                        "quantity": 3,
                        "fill_price": 110,
                        "fees": 1,
                        "realized_pnl": 30,
                        "metadata": {"trade_plan_id": "plan-42"},
                    }
                ],
            },
        )

    class FakeClient:
        def __init__(self, timeout=None, headers=None):
            self.inner = original_client(transport=httpx.MockTransport(handler), base_url="http://db")

        def __enter__(self):
            return self.inner

        def __exit__(self, exc_type, exc, tb):
            self.inner.close()
            return False

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = DatabaseAgentClient(base_url="http://db", api_key="key")
    fills = client.list_fills(account_id="1", symbol="AAPL")

    assert fills[0].trade_plan_id == "plan-42"
    assert fills[0].order_id == 42
    assert fills[0].realized_pnl == 30
