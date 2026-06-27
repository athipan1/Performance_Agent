from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from app.models import EquityPoint, PerformanceMetrics, PerformanceReportRequest, TradeResult, TradeSide


def trade_pnl(trade: TradeResult) -> float:
    if trade.side == TradeSide.SHORT:
        return (trade.entry_price - trade.exit_price) * trade.quantity - trade.fees
    return (trade.exit_price - trade.entry_price) * trade.quantity - trade.fees


def _safe_round(value: Optional[float], digits: int = 6) -> Optional[float]:
    if value is None:
        return None
    return round(value, digits)


def _profit_factor(gross_profit: float, gross_loss: float) -> Optional[float]:
    if gross_loss == 0:
        if gross_profit > 0:
            return None
        return 0.0
    return gross_profit / abs(gross_loss)


def _max_drawdown_from_equity(points: List[EquityPoint]) -> float:
    if not points:
        return 0.0
    sorted_points = sorted(points, key=lambda point: point.timestamp)
    peak = sorted_points[0].equity
    max_drawdown = 0.0
    for point in sorted_points:
        peak = max(peak, point.equity)
        drawdown = (point.equity - peak) / peak
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def _group_metrics(trades: Iterable[TradeResult]) -> Dict[str, Any]:
    trade_list = list(trades)
    pnls = [trade_pnl(trade) for trade in trade_list]
    winners = [pnl for pnl in pnls if pnl > 0]
    losers = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(winners)
    gross_loss = sum(losers)
    trade_count = len(trade_list)
    return {
        "trade_count": trade_count,
        "win_rate": 0.0 if trade_count == 0 else len(winners) / trade_count,
        "net_profit": sum(pnls),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": _profit_factor(gross_profit, gross_loss),
        "expectancy": 0.0 if trade_count == 0 else sum(pnls) / trade_count,
    }


def _group_by_strategy(trades: List[TradeResult]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[TradeResult]] = defaultdict(list)
    for trade in trades:
        grouped[trade.strategy or "unknown"].append(trade)
    return {key: _group_metrics(value) for key, value in grouped.items()}


def _group_by_symbol(trades: List[TradeResult]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[TradeResult]] = defaultdict(list)
    for trade in trades:
        grouped[trade.symbol.upper()].append(trade)
    return {key: _group_metrics(value) for key, value in grouped.items()}


def _best_key(grouped: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if not grouped:
        return None
    return max(grouped, key=lambda key: grouped[key]["net_profit"])


def _worst_key(grouped: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if not grouped:
        return None
    return min(grouped, key=lambda key: grouped[key]["net_profit"])


def build_performance_report(request: PerformanceReportRequest) -> PerformanceMetrics:
    pnls = [trade_pnl(trade) for trade in request.trades]
    winners = [pnl for pnl in pnls if pnl > 0]
    losers = [pnl for pnl in pnls if pnl < 0]
    trade_count = len(request.trades)
    gross_profit = sum(winners)
    gross_loss = sum(losers)
    net_profit = sum(pnls)
    by_strategy = _group_by_strategy(request.trades)
    by_symbol = _group_by_symbol(request.trades)
    warnings: List[str] = []

    if trade_count == 0:
        warnings.append("No closed trades were provided")
    if not request.equity_curve:
        warnings.append("No equity curve was provided; max_drawdown defaults to 0")

    return PerformanceMetrics(
        period=request.period,
        trade_count=trade_count,
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=_safe_round(0.0 if trade_count == 0 else len(winners) / trade_count),
        gross_profit=_safe_round(gross_profit, 2),
        gross_loss=_safe_round(gross_loss, 2),
        net_profit=_safe_round(net_profit, 2),
        return_pct=_safe_round(net_profit / request.initial_equity),
        average_win=_safe_round(0.0 if not winners else sum(winners) / len(winners), 2),
        average_loss=_safe_round(0.0 if not losers else sum(losers) / len(losers), 2),
        expectancy=_safe_round(0.0 if trade_count == 0 else net_profit / trade_count, 2),
        profit_factor=_safe_round(_profit_factor(gross_profit, gross_loss)),
        max_drawdown=_safe_round(_max_drawdown_from_equity(request.equity_curve)),
        best_strategy=_best_key(by_strategy),
        worst_strategy=_worst_key(by_strategy),
        by_strategy=by_strategy,
        by_symbol=by_symbol,
        warnings=warnings,
    )
