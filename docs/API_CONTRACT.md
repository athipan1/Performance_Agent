# Performance_Agent API Contract

This document defines the baseline API contract for `Performance_Agent`.

`Performance_Agent` provides analytics for reports, strategy summaries, symbol summaries, session metrics, and trade-plan summaries.

## Standard Headers

```http
Content-Type: application/json
X-Correlation-ID: <uuid>
X-API-KEY: <performance-agent-api-key>
```

## Standard Response Envelope

Operational contract endpoints return this envelope:

```json
{
  "status": "success",
  "agent_type": "performance-agent",
  "version": "0.1.0",
  "schema_version": "1.0",
  "timestamp": "2026-07-04T00:00:00Z",
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
GET /performance/trade-plans/database-summary
```

## Notes

1. This service provides analytics output for other agents.
2. Runtime readiness is reported through `/ready`.
3. Version and schema metadata are reported through `/version`.
4. Existing analytics endpoints keep their current response models.
