from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from app.models import DatabaseTradePlanSummaryQuery, TradePlanFill, TradePlanLifecycleRecord


class DatabaseAgentError(RuntimeError):
    pass


class DatabaseAgentClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 10.0):
        self.base_url = (base_url or os.getenv("DATABASE_AGENT_URL") or "http://localhost:8001").rstrip("/")
        api_key = api_key if api_key is not None else os.getenv("DATABASE_AGENT_API_KEY")
        self.headers = {"X-API-KEY": api_key} if api_key else {}
        self.timeout = timeout

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                response = client.get(url, params={k: v for k, v in (params or {}).items() if v is not None})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise DatabaseAgentError(f"Database_Agent request failed for {path}: {exc}") from exc
        if payload.get("status") != "success":
            raise DatabaseAgentError(f"Database_Agent returned non-success response for {path}: {payload}")
        return payload

    def list_trade_plans(self, query: DatabaseTradePlanSummaryQuery) -> List[TradePlanLifecycleRecord]:
        params = {
            "account_id": query.account_id,
            "symbol": query.symbol,
            "status": query.status,
            "strategy": query.strategy,
            "strategy_bucket": query.strategy_bucket,
            "risk_approval_id": query.risk_approval_id,
            "order_id": query.order_id,
            "limit": query.limit,
            "offset": query.offset,
            "sort": query.sort,
            "order": query.order,
        }
        payload = self._get("/trade-plans", params=params)
        return [TradePlanLifecycleRecord.model_validate(row) for row in (payload.get("data") or [])]

    def list_fills(self, account_id: str | int, symbol: Optional[str] = None, limit: int = 500) -> List[TradePlanFill]:
        params = {"symbol": symbol, "limit": limit}
        payload = self._get(f"/accounts/{account_id}/fills", params=params)
        fills: List[TradePlanFill] = []
        for row in payload.get("data") or []:
            metadata = row.get("metadata") or {}
            fills.append(
                TradePlanFill(
                    trade_plan_id=row.get("trade_plan_id") or metadata.get("trade_plan_id"),
                    order_id=row.get("order_id"),
                    trade_id=row.get("trade_id"),
                    symbol=row.get("symbol"),
                    side=row.get("side") or "buy",
                    quantity=row.get("quantity") or row.get("filled_quantity") or 0,
                    fill_price=row.get("fill_price") or row.get("price") or row.get("average_fill_price") or 0,
                    fees=row.get("fees") or 0,
                    realized_pnl=row.get("realized_pnl"),
                    filled_at=row.get("filled_at"),
                    metadata=metadata,
                )
            )
        return fills
