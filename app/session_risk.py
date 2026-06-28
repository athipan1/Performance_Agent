from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from app.models import SessionRiskMetrics, SessionRiskMetricsRequest, TradePlanFill


def _as_utc(value: Optional[datetime], fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fill_time(fill: TradePlanFill, fallback: datetime) -> datetime:
    return _as_utc(fill.filled_at, fallback)


def _fill_pnl(fill: TradePlanFill) -> float:
    return float(fill.realized_pnl or 0.0)


def _loss_pct(pnl: float, equity: float) -> float:
    if equity <= 0:
        return 0.0
    return abs(min(0.0, pnl)) / equity


def _matches_symbol(fill: TradePlanFill, symbol: Optional[str]) -> bool:
    if not symbol:
        return True
    return fill.symbol.upper() == symbol.upper()


def _consecutive_losses(fills: Iterable[TradePlanFill], now: datetime) -> int:
    ordered = sorted(fills, key=lambda fill: _fill_time(fill, now), reverse=True)
    count = 0
    for fill in ordered:
        pnl = _fill_pnl(fill)
        if pnl < 0:
            count += 1
            continue
        if pnl > 0:
            break
    return count


def _minutes_since_last_loss(fills: Iterable[TradePlanFill], now: datetime) -> Optional[float]:
    loss_times = [_fill_time(fill, now) for fill in fills if _fill_pnl(fill) < 0]
    if not loss_times:
        return None
    last_loss = max(loss_times)
    return round(max(0.0, (now - last_loss).total_seconds() / 60.0), 2)


def _minutes_since_last_symbol_trade(fills: Iterable[TradePlanFill], now: datetime, symbol: Optional[str]) -> Optional[float]:
    if not symbol:
        return None
    symbol_times = [_fill_time(fill, now) for fill in fills if _matches_symbol(fill, symbol)]
    if not symbol_times:
        return None
    last_symbol_trade = max(symbol_times)
    return round(max(0.0, (now - last_symbol_trade).total_seconds() / 60.0), 2)


def build_session_risk_metrics(request: SessionRiskMetricsRequest) -> SessionRiskMetrics:
    now = _as_utc(request.generated_at, datetime.now(timezone.utc))
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = start_of_day - timedelta(days=start_of_day.weekday())

    fills = list(request.fills)
    dated_fills = [(fill, _fill_time(fill, now)) for fill in fills]
    daily_fills = [fill for fill, timestamp in dated_fills if timestamp >= start_of_day]
    weekly_fills = [fill for fill, timestamp in dated_fills if timestamp >= start_of_week]
    symbol_daily_fills = [fill for fill in daily_fills if _matches_symbol(fill, request.symbol)]

    daily_realized_pnl = round(sum(_fill_pnl(fill) for fill in daily_fills), 2)
    weekly_realized_pnl = round(sum(_fill_pnl(fill) for fill in weekly_fills), 2)
    warnings: list[str] = []
    if any(fill.realized_pnl is None for fill in fills):
        warnings.append("Some fills have no realized_pnl; missing values default to 0")
    if not fills:
        warnings.append("No fills were provided; session metrics default to zero")

    return SessionRiskMetrics(
        account_id=request.account_id,
        symbol=request.symbol.upper() if request.symbol else None,
        daily_realized_pnl=daily_realized_pnl,
        weekly_realized_pnl=weekly_realized_pnl,
        daily_loss_pct=round(_loss_pct(daily_realized_pnl, request.equity), 6),
        weekly_loss_pct=round(_loss_pct(weekly_realized_pnl, request.equity), 6),
        consecutive_losses=_consecutive_losses(fills, now),
        trades_today=len(daily_fills),
        symbol_trades_today=len(symbol_daily_fills),
        minutes_since_last_loss=_minutes_since_last_loss(fills, now),
        minutes_since_last_symbol_trade=_minutes_since_last_symbol_trade(fills, now, request.symbol),
        emergency_halt=bool(request.emergency_halt),
        generated_at=now,
        warnings=warnings,
    )
