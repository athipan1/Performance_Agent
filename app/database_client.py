from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
from pydantic import ValidationError

from app.models import (
    DatabaseLearningOutcomeQuery,
    DatabaseTradePlanSummaryQuery,
    TradePlanFill,
    TradePlanLifecycleRecord,
)
from app.security import (
    configured_database_agent_api_key,
    configured_database_agent_url,
)


class DatabaseAgentError(RuntimeError):
    pass


class DatabaseAgentClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ):
        resolved_url = base_url or configured_database_agent_url()
        if not resolved_url:
            resolved_url = "http://localhost:8001"
        self.base_url = resolved_url.rstrip("/")
        resolved_key = (
            api_key
            if api_key is not None
            else configured_database_agent_api_key()
        )
        self.headers = {"X-API-KEY": resolved_key} if resolved_key else {}
        self.timeout = timeout

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(
                timeout=self.timeout,
                headers=self.headers,
            ) as client:
                response = client.get(
                    url,
                    params={
                        key: value
                        for key, value in (params or {}).items()
                        if value is not None
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise DatabaseAgentError(
                f"Database_Agent request failed for {path}: {exc}"
            ) from exc
        if payload.get("status") != "success":
            raise DatabaseAgentError(
                "Database_Agent returned non-success response for "
                f"{path}: {payload}"
            )
        return payload

    def list_trade_plans(
        self,
        query: DatabaseTradePlanSummaryQuery | DatabaseLearningOutcomeQuery,
    ) -> List[TradePlanLifecycleRecord]:
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
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            raise DatabaseAgentError(
                "Database_Agent /trade-plans data must be a list"
            )
        plans: List[TradePlanLifecycleRecord] = []
        for index, row in enumerate(rows):
            try:
                plans.append(TradePlanLifecycleRecord.model_validate(row))
            except ValidationError as exc:
                raise DatabaseAgentError(
                    "Database_Agent returned an invalid TradePlan at "
                    f"index {index}: {exc}"
                ) from exc
        return plans

    @staticmethod
    def _map_fill(row: Dict[str, Any]) -> TradePlanFill:
        metadata = row.get("metadata") or {}
        try:
            return TradePlanFill(
                trade_plan_id=(
                    row.get("trade_plan_id")
                    or metadata.get("trade_plan_id")
                ),
                order_id=row.get("order_id"),
                trade_id=row.get("trade_id"),
                symbol=row.get("symbol"),
                side=row.get("side") or "buy",
                quantity=(
                    row.get("quantity")
                    or row.get("filled_quantity")
                    or 0
                ),
                fill_price=(
                    row.get("fill_price")
                    or row.get("price")
                    or row.get("average_fill_price")
                    or 0
                ),
                fees=row.get("fees") or 0,
                realized_pnl=row.get("realized_pnl"),
                filled_at=row.get("filled_at"),
                metadata=metadata,
            )
        except ValidationError as exc:
            raise DatabaseAgentError(
                f"Database_Agent returned an invalid fill: {exc}"
            ) from exc

    @staticmethod
    def _fill_identity(fill: TradePlanFill) -> tuple[Any, ...]:
        metadata = fill.metadata or {}
        external_fill_id = (
            metadata.get("fill_id")
            or metadata.get("broker_fill_id")
            or metadata.get("execution_id")
        )
        if external_fill_id:
            return ("external_fill_id", str(external_fill_id))
        return (
            "composite",
            str(fill.trade_plan_id or ""),
            str(fill.order_id or ""),
            str(fill.trade_id or ""),
            fill.symbol.upper(),
            fill.side.lower(),
            round(float(fill.quantity), 12),
            round(float(fill.fill_price), 12),
            round(float(fill.fees or 0.0), 12),
            (
                None
                if fill.realized_pnl is None
                else round(float(fill.realized_pnl), 12)
            ),
            fill.filled_at.isoformat() if fill.filled_at else None,
        )

    def list_fills(
        self,
        account_id: str | int,
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> List[TradePlanFill]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        page_size = min(limit, 500)
        offset = 0
        fills: List[TradePlanFill] = []
        seen_fill_ids: set[tuple[Any, ...]] = set()
        seen_page_signatures: set[str] = set()

        while len(fills) < limit:
            payload = self._get(
                f"/accounts/{account_id}/fills",
                params={
                    "symbol": symbol,
                    "limit": min(page_size, limit - len(fills)),
                    "offset": offset,
                },
            )
            rows = payload.get("data") or []
            if not isinstance(rows, list):
                raise DatabaseAgentError(
                    "Database_Agent fills data must be a list"
                )
            if not rows:
                break

            signature = json.dumps(rows, sort_keys=True, default=str)
            if signature in seen_page_signatures:
                raise DatabaseAgentError(
                    "Database_Agent fill pagination did not advance"
                )
            seen_page_signatures.add(signature)

            for row in rows:
                fill = self._map_fill(row)
                identity = self._fill_identity(fill)
                if identity in seen_fill_ids:
                    continue
                seen_fill_ids.add(identity)
                fills.append(fill)
                if len(fills) >= limit:
                    break

            offset += len(rows)
            if len(rows) < page_size:
                break

        return fills
