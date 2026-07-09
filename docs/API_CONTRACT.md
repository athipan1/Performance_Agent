# Performance_Agent API Contract

This document defines the API contract for `Performance_Agent`.

`Performance_Agent` provides analytics, strict realized-outcome generation, and audit-ready payloads for `Manager_Agent`, `Learning_Agent`, and reporting dashboards. It never places orders or mutates production policy.

## Versions

```text
agent_version        = 0.4.0
service_version      = 0.4.0
schema_version       = 1.0
performance_contract = performance-outcome-v1
learning_contract    = learning-outcome-v1
```

## Standard Headers

```http
Content-Type: application/json
X-Correlation-ID: <uuid>
X-API-KEY: <performance-agent-api-key>
```

## Standard Response Envelope

```json
{
  "status": "success",
  "agent_type": "performance-agent",
  "version": "0.4.0",
  "schema_version": "1.0",
  "timestamp": "2026-07-09T00:00:00Z",
  "correlation_id": null,
  "data": {},
  "metadata": {},
  "error": null,
  "confidence_score": null
}
```

## Operational Endpoints

```http
GET /health
GET /ready
GET /version
```

## Analytics Endpoints

```http
POST /performance/report
POST /performance/strategy
POST /performance/symbol
POST /performance/session-risk
POST /performance/trade-plans/summary
GET  /performance/trade-plans/database-summary
```

## Learning Outcome Endpoints

```http
POST /performance/learning-outcomes
GET  /performance/learning-outcomes/database
```

The POST endpoint accepts TradePlan and fill records directly. The database endpoint retrieves TradePlans and fills from `Database_Agent`; `account_id` is required so fills can be matched reliably.

## Learnable outcome policy

A `learning-outcome-v1` record is generated only when all of the following are true:

1. Execution status is `filled`, `closed`, `completed`, or `exited`.
2. At least one matched fill contains explicit `realized_pnl`.
3. Entry and exit prices are available.
4. Manager, Execution, and Database buckets are present, controlled, and identical.
5. Risk approval exists.
6. Manager evidence gate passed.
7. Manager classification status is `classified`.
8. Classifier version is `manager-strategy-bucket-v3`.
9. All supported evidence versions are present:
   - `scanner-bucket-hints-v2`
   - `fundamental-evidence-v1`
   - `technical-evidence-v1`
   - `manager-analysis-evidence-v1`
10. Evidence status is learnable and classification inputs are present.

Records that fail any rule are returned under `rejected_records` with explicit reasons. Performance_Agent never silently normalizes a missing or conflicting bucket.

## Performance summary versus learning outcome

Performance lifecycle summaries may count terminal states such as cancelled or rejected for operational reporting. These records are **not** automatically learnable.

Learning outcomes use a separate strict path and require explicit realized PnL. No synthetic realized outcome is generated from entry and current price alone.

## Generated fields

Each accepted outcome includes:

- deterministic outcome ID
- TradePlan ID and account ID
- Manager, Execution, and Database bucket values
- Manager classifier version
- evidence versions and source contributions
- normalized classification inputs
- bucket confidence
- entry price, exit price, realized PnL, and return percentage
- holding period and exit reason
- Risk approval and Execution status
- `outcome_status=closed`
- `pnl_status=realized`

## Safety Rules

- `requires_human_review=true`
- `auto_apply=false`
- no order submission
- no policy writes
- no bucket inference from Database values when Manager or Execution attribution is missing
- duplicate TradePlan IDs are rejected
- unmatched fills are reported as warnings
