from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import EquityPoint, PerformanceReportRequest, TradeResult
from app.service import build_performance_report, trade_pnl


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["status"] == "healthy"


def test_trade_pnl_for_long_trade():
    trade = TradeResult(symbol="AAPL", entry_price=100, exit_price=110, quantity=10, fees=1)
    assert trade_pnl(trade) == 99


def test_performance_report_metrics():
    request = PerformanceReportRequest(
        initial_equity=10_000,
        period="30d",
        trades=[
            TradeResult(symbol="AAPL", strategy="core_dividend", entry_price=100, exit_price=110, quantity=10),
            TradeResult(symbol="MSFT", strategy="value_rebound", entry_price=100, exit_price=95, quantity=10),
            TradeResult(symbol="ADBE", strategy="core_dividend", entry_price=100, exit_price=120, quantity=5),
        ],
        equity_curve=[
            EquityPoint(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), equity=10_000),
            EquityPoint(timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc), equity=10_200),
            EquityPoint(timestamp=datetime(2026, 1, 3, tzinfo=timezone.utc), equity=9_900),
            EquityPoint(timestamp=datetime(2026, 1, 4, tzinfo=timezone.utc), equity=10_150),
        ],
    )
    result = build_performance_report(request)
    assert result.trade_count == 3
    assert result.winning_trades == 2
    assert result.losing_trades == 1
    assert result.win_rate == 0.666667
    assert result.gross_profit == 200
    assert result.gross_loss == -50
    assert result.net_profit == 150
    assert result.profit_factor == 4
    assert result.expectancy == 50
    assert result.best_strategy == "core_dividend"
    assert result.worst_strategy == "value_rebound"
    assert result.max_drawdown == -0.029412


def test_no_trades_returns_warning():
    result = build_performance_report(PerformanceReportRequest(initial_equity=10_000))
    assert result.trade_count == 0
    assert result.win_rate == 0
    assert "No closed trades were provided" in result.warnings


def test_performance_report_endpoint():
    response = client.post(
        "/performance/report",
        json={
            "initial_equity": 10000,
            "period": "30d",
            "trades": [
                {"symbol": "AAPL", "strategy": "core_dividend", "entry_price": 100, "exit_price": 110, "quantity": 10},
                {"symbol": "MSFT", "strategy": "value_rebound", "entry_price": 100, "exit_price": 95, "quantity": 10},
            ],
            "equity_curve": [
                {"timestamp": "2026-01-01T00:00:00Z", "equity": 10000},
                {"timestamp": "2026-01-02T00:00:00Z", "equity": 10100},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["trade_count"] == 2
    assert payload["data"]["net_profit"] == 50
