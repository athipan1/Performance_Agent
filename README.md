# Performance Agent

Performance Agent analyzes closed trades and equity curves for the multi-agent trading system.

It does **not** place orders. It returns performance metrics for `Manager_Agent`, `Learning_Agent`, and reporting dashboards.

## Responsibilities

- Calculate realized P/L per trade
- Calculate win rate
- Calculate gross profit and gross loss
- Calculate profit factor
- Calculate expectancy
- Calculate return percentage
- Calculate max drawdown from equity curve
- Group performance by strategy
- Group performance by symbol

## API

### Health

```bash
curl http://localhost:8013/health
```

### Performance Report

```bash
curl -X POST http://localhost:8013/performance/report \
  -H 'Content-Type: application/json' \
  -d '{
    "initial_equity": 10000,
    "period": "30d",
    "trades": [
      {"symbol": "AAPL", "strategy": "core_dividend", "entry_price": 100, "exit_price": 110, "quantity": 10},
      {"symbol": "MSFT", "strategy": "value_rebound", "entry_price": 100, "exit_price": 95, "quantity": 10}
    ],
    "equity_curve": [
      {"timestamp": "2026-01-01T00:00:00Z", "equity": 10000},
      {"timestamp": "2026-01-02T00:00:00Z", "equity": 10100}
    ]
  }'
```

Example response fields:

```json
{
  "trade_count": 2,
  "win_rate": 0.5,
  "net_profit": 50,
  "profit_factor": 2.0,
  "expectancy": 25,
  "best_strategy": "core_dividend",
  "worst_strategy": "value_rebound"
}
```

## Endpoints

```text
GET  /health
POST /performance/report
POST /performance/strategy
POST /performance/symbol
```

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8013
```

## Tests

```bash
ruff check app tests
pytest -q
```

## Docker

```bash
docker build -t performance-agent .
docker run --rm -p 8013:8013 performance-agent
```

## Integration rule

`Performance_Agent` is advisory/reporting only. It should never call `Execution_Agent` directly.

Recommended flow:

```text
Database_Agent
  -> Manager_Agent
  -> Performance_Agent
  -> Learning_Agent
```
