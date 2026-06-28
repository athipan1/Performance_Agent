from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import SessionRiskMetricsRequest, TradePlanFill
from app.session_risk import build_session_risk_metrics


client = TestClient(app)


def test_build_session_risk_metrics_for_risk_agent_context():
    now = datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc)
    request = SessionRiskMetricsRequest(
        account_id=1,
        symbol="AAPL",
        equity=100000,
        generated_at=now,
        fills=[
            TradePlanFill(symbol="AAPL", quantity=1, fill_price=100, realized_pnl=-100, filled_at="2026-06-28T09:30:00Z"),
            TradePlanFill(symbol="MSFT", quantity=1, fill_price=100, realized_pnl=-50, filled_at="2026-06-28T09:45:00Z"),
            TradePlanFill(symbol="AAPL", quantity=1, fill_price=100, realized_pnl=200, filled_at="2026-06-27T15:00:00Z"),
            TradePlanFill(symbol="AAPL", quantity=1, fill_price=100, realized_pnl=-300, filled_at="2026-06-23T12:00:00Z"),
        ],
    )

    metrics = build_session_risk_metrics(request)

    assert metrics.account_id == 1
    assert metrics.symbol == "AAPL"
    assert metrics.daily_realized_pnl == -150
    assert metrics.weekly_realized_pnl == 50
    assert metrics.daily_loss_pct == 0.0015
    assert metrics.weekly_loss_pct == 0.0
    assert metrics.consecutive_losses == 2
    assert metrics.trades_today == 2
    assert metrics.symbol_trades_today == 1
    assert metrics.minutes_since_last_loss == 15.0
    assert metrics.minutes_since_last_symbol_trade == 30.0
    assert metrics.emergency_halt is False
    assert metrics.source == "performance_agent"


def test_session_risk_metrics_endpoint():
    response = client.post(
        "/performance/session-risk",
        json={
            "account_id": 1,
            "symbol": "AAPL",
            "equity": 100000,
            "generated_at": "2026-06-28T10:00:00Z",
            "emergency_halt": True,
            "fills": [
                {"symbol": "AAPL", "quantity": 1, "fill_price": 100, "realized_pnl": -500, "filled_at": "2026-06-28T09:00:00Z"},
                {"symbol": "AAPL", "quantity": 1, "fill_price": 100, "realized_pnl": -250, "filled_at": "2026-06-28T09:30:00Z"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["daily_realized_pnl"] == -750
    assert payload["data"]["weekly_realized_pnl"] == -750
    assert payload["data"]["daily_loss_pct"] == 0.0075
    assert payload["data"]["weekly_loss_pct"] == 0.0075
    assert payload["data"]["consecutive_losses"] == 2
    assert payload["data"]["trades_today"] == 2
    assert payload["data"]["symbol_trades_today"] == 2
    assert payload["data"]["emergency_halt"] is True


def test_session_risk_metrics_empty_fills_warns_and_defaults_to_zero():
    metrics = build_session_risk_metrics(
        SessionRiskMetricsRequest(
            account_id=1,
            equity=100000,
            generated_at=datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert metrics.daily_realized_pnl == 0
    assert metrics.weekly_realized_pnl == 0
    assert metrics.consecutive_losses == 0
    assert metrics.trades_today == 0
    assert "No fills were provided; session metrics default to zero" in metrics.warnings
