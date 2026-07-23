from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from app.models import SessionRiskMetrics, SessionRiskMetricsRequest, TradePlanFill


@dataclass(frozen=True)
class AggregatedTrade:
    key: str
    symbol: str
    realized_pnl: float
    closed_at: datetime


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fill_pnl(fill: TradePlanFill) -> Optional[float]:
    if fill.realized_pnl is None:
        return None
    return float(fill.realized_pnl)


def _trade_key(fill: TradePlanFill, index: int) -> tuple[str, bool]:
    if fill.trade_plan_id:
        return f"trade_plan:{fill.trade_plan_id}", True
    if fill.trade_id is not None:
        return f"trade:{fill.trade_id}", True
    if fill.order_id is not None:
        return f"order:{fill.order_id}", True
    return f"unidentified_fill:{index}", False


def _aggregate_trades(
    fills: Iterable[TradePlanFill],
    now: datetime,
) -> tuple[list[AggregatedTrade], list[str]]:
    grouped: dict[str, dict[str, object]] = {}
    missing_pnl = 0
    missing_time = 0
    future_time = 0
    unidentified = 0

    for index, fill in enumerate(fills):
        pnl = _fill_pnl(fill)
        if pnl is None:
            missing_pnl += 1
            continue

        filled_at = _as_utc(fill.filled_at)
        if filled_at is None:
            missing_time += 1
            continue
        if filled_at > now:
            future_time += 1
            continue

        key, identified = _trade_key(fill, index)
        if not identified:
            unidentified += 1

        row = grouped.setdefault(
            key,
            {
                "symbol": fill.symbol.upper(),
                "realized_pnl": 0.0,
                "closed_at": filled_at,
            },
        )
        row["realized_pnl"] = float(row["realized_pnl"]) + pnl
        if filled_at > row["closed_at"]:
            row["closed_at"] = filled_at

    trades = [
        AggregatedTrade(
            key=key,
            symbol=str(row["symbol"]),
            realized_pnl=round(float(row["realized_pnl"]), 8),
            closed_at=row["closed_at"],
        )
        for key, row in grouped.items()
    ]

    warnings: list[str] = []
    if missing_pnl:
        warnings.append(
            f"{missing_pnl} fill(s) without realized_pnl were excluded"
        )
    if missing_time:
        warnings.append(
            f"{missing_time} fill(s) without filled_at were excluded"
        )
    if future_time:
        warnings.append(
            f"{future_time} fill(s) with future filled_at were excluded"
        )
    if unidentified:
        warnings.append(
            f"{unidentified} fill(s) lacked a trade identifier and were "
            "counted individually"
        )
    return trades, warnings


def _loss_pct(pnl: float, equity: float) -> float:
    if equity <= 0:
        return 0.0
    return abs(min(0.0, pnl)) / equity


def _matches_symbol(trade: AggregatedTrade, symbol: Optional[str]) -> bool:
    if not symbol:
        return True
    return trade.symbol == symbol.upper()


def _consecutive_losses(trades: Iterable[AggregatedTrade]) -> int:
    ordered = sorted(trades, key=lambda trade: trade.closed_at, reverse=True)
    count = 0
    for trade in ordered:
        if trade.realized_pnl < 0:
            count += 1
            continue
        if trade.realized_pnl > 0:
            break
    return count


def _minutes_since_last_loss(
    trades: Iterable[AggregatedTrade],
    now: datetime,
) -> Optional[float]:
    loss_times = [
        trade.closed_at for trade in trades if trade.realized_pnl < 0
    ]
    if not loss_times:
        return None
    last_loss = max(loss_times)
    return round((now - last_loss).total_seconds() / 60.0, 2)


def _minutes_since_last_symbol_trade(
    trades: Iterable[AggregatedTrade],
    now: datetime,
    symbol: Optional[str],
) -> Optional[float]:
    if not symbol:
        return None
    symbol_times = [
        trade.closed_at
        for trade in trades
        if _matches_symbol(trade, symbol)
    ]
    if not symbol_times:
        return None
    last_symbol_trade = max(symbol_times)
    return round((now - last_symbol_trade).total_seconds() / 60.0, 2)


def build_session_risk_metrics(
    request: SessionRiskMetricsRequest,
) -> SessionRiskMetrics:
    now = _as_utc(request.generated_at) or datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = start_of_day - timedelta(days=start_of_day.weekday())

    fills = list(request.fills)
    trades, warnings = _aggregate_trades(fills, now)
    daily_trades = [
        trade for trade in trades if start_of_day <= trade.closed_at <= now
    ]
    weekly_trades = [
        trade for trade in trades if start_of_week <= trade.closed_at <= now
    ]
    symbol_daily_trades = [
        trade
        for trade in daily_trades
        if _matches_symbol(trade, request.symbol)
    ]

    daily_realized_pnl = round(
        sum(trade.realized_pnl for trade in daily_trades),
        2,
    )
    weekly_realized_pnl = round(
        sum(trade.realized_pnl for trade in weekly_trades),
        2,
    )
    if not fills:
        warnings.append("No fills were provided; session metrics default to zero")

    return SessionRiskMetrics(
        account_id=request.account_id,
        symbol=request.symbol.upper() if request.symbol else None,
        daily_realized_pnl=daily_realized_pnl,
        weekly_realized_pnl=weekly_realized_pnl,
        daily_loss_pct=round(
            _loss_pct(daily_realized_pnl, request.equity),
            6,
        ),
        weekly_loss_pct=round(
            _loss_pct(weekly_realized_pnl, request.equity),
            6,
        ),
        consecutive_losses=_consecutive_losses(trades),
        trades_today=len(daily_trades),
        symbol_trades_today=len(symbol_daily_trades),
        minutes_since_last_loss=_minutes_since_last_loss(trades, now),
        minutes_since_last_symbol_trade=_minutes_since_last_symbol_trade(
            trades,
            now,
            request.symbol,
        ),
        emergency_halt=bool(request.emergency_halt),
        generated_at=now,
        warnings=warnings,
    )
