from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from app.models import (
    EquityPoint,
    PerformanceMetrics,
    PerformanceReportRequest,
    TradePlanFill,
    TradePlanLifecycleRecord,
    TradePlanPerformanceRequest,
    TradePlanPerformanceSummary,
    TradeResult,
    TradeSide,
)


CLOSED_PLAN_STATUSES = {"filled", "closed", "cancelled", "rejected"}
WIN_LOSS_STATUSES = {"filled", "closed"}


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


def _fill_plan_key(fill: TradePlanFill) -> Optional[str]:
    if fill.trade_plan_id:
        return str(fill.trade_plan_id)
    if fill.trade_id:
        return str(fill.trade_id)
    return None


def _planned_entry_price(plan: TradePlanLifecycleRecord) -> Optional[float]:
    raw_plan = plan.plan or {}
    for key in ("entry_price", "limit_price"):
        value = raw_plan.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _planned_quantity(plan: TradePlanLifecycleRecord) -> Optional[float]:
    raw_plan = plan.plan or {}
    for key in ("final_quantity", "quantity"):
        value = raw_plan.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _side_multiplier(side: str) -> int:
    return -1 if str(side).lower() in {"sell", "short"} else 1


def _plan_realized_pnl(plan: TradePlanLifecycleRecord, fills: List[TradePlanFill]) -> tuple[float, str]:
    explicit_pnls = [fill.realized_pnl for fill in fills if fill.realized_pnl is not None]
    if explicit_pnls:
        return sum(float(value) for value in explicit_pnls), "fills.realized_pnl"

    entry = _planned_entry_price(plan)
    if entry is None:
        return 0.0, "missing_entry_price"
    if not fills:
        return 0.0, "no_fills"

    side_multiplier = _side_multiplier(plan.side)
    pnl = 0.0
    for fill in fills:
        pnl += (float(fill.fill_price) - entry) * float(fill.quantity) * side_multiplier
        pnl -= float(fill.fees or 0.0)
    return pnl, "computed_from_entry_and_fills"


def _summarize_plan(plan: TradePlanLifecycleRecord, fills: List[TradePlanFill]) -> Dict[str, Any]:
    pnl, pnl_source = _plan_realized_pnl(plan, fills)
    quantity = sum(float(fill.quantity) for fill in fills) or _planned_quantity(plan) or 0.0
    return {
        "trade_plan_id": plan.trade_plan_id,
        "symbol": plan.symbol.upper(),
        "status": plan.status,
        "strategy": plan.strategy,
        "strategy_bucket": plan.strategy_bucket,
        "risk_approval_id": plan.risk_approval_id,
        "order_id": plan.order_id,
        "fill_count": len(fills),
        "quantity": _safe_round(quantity, 6),
        "net_pnl": _safe_round(pnl, 2),
        "pnl_source": pnl_source,
        "is_closed": plan.status.lower() in CLOSED_PLAN_STATUSES,
        "is_win_loss_counted": plan.status.lower() in WIN_LOSS_STATUSES,
    }


def _group_plan_results(results: Iterable[Dict[str, Any]], key_name: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result.get(key_name) or "unknown")].append(result)

    output: Dict[str, Dict[str, Any]] = {}
    for key, rows in grouped.items():
        pnls = [float(row.get("net_pnl") or 0.0) for row in rows]
        winners = [pnl for pnl in pnls if pnl > 0]
        losers = [pnl for pnl in pnls if pnl < 0]
        gross_profit = sum(winners)
        gross_loss = sum(losers)
        counted = [row for row in rows if row.get("is_win_loss_counted")]
        output[key] = {
            "trade_plan_count": len(rows),
            "closed_plan_count": sum(1 for row in rows if row.get("is_closed")),
            "win_rate": 0.0 if not counted else sum(1 for row in counted if float(row.get("net_pnl") or 0.0) > 0) / len(counted),
            "gross_profit": _safe_round(gross_profit, 2),
            "gross_loss": _safe_round(gross_loss, 2),
            "net_pnl": _safe_round(sum(pnls), 2),
            "expectancy": _safe_round(0.0 if not counted else sum(float(row.get("net_pnl") or 0.0) for row in counted) / len(counted), 2),
            "profit_factor": _safe_round(_profit_factor(gross_profit, gross_loss)),
        }
    return output


def build_trade_plan_performance_summary(request: TradePlanPerformanceRequest) -> TradePlanPerformanceSummary:
    fills_by_plan: Dict[str, List[TradePlanFill]] = defaultdict(list)
    unmatched_fills = 0
    for fill in request.fills:
        key = _fill_plan_key(fill)
        if key:
            fills_by_plan[key].append(fill)
        else:
            unmatched_fills += 1

    plan_results = [_summarize_plan(plan, fills_by_plan.get(plan.trade_plan_id, [])) for plan in request.trade_plans]
    counted_results = [row for row in plan_results if row.get("is_win_loss_counted")]
    closed_plan_count = sum(1 for row in plan_results if row.get("is_closed"))
    open_plan_count = len(plan_results) - closed_plan_count
    pnls = [float(row.get("net_pnl") or 0.0) for row in counted_results]
    winners = [pnl for pnl in pnls if pnl > 0]
    losers = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(winners)
    gross_loss = sum(losers)
    net_pnl = sum(pnls)
    by_strategy_bucket = _group_plan_results(plan_results, "strategy_bucket")
    by_symbol = _group_plan_results(plan_results, "symbol")
    warnings: List[str] = []

    if not request.trade_plans:
        warnings.append("No TradePlan records were provided")
    if unmatched_fills:
        warnings.append(f"{unmatched_fills} fill(s) could not be matched to a TradePlan")
    if any(row["pnl_source"] == "missing_entry_price" for row in plan_results):
        warnings.append("Some TradePlans are missing entry_price/limit_price; pnl defaults to 0")

    return TradePlanPerformanceSummary(
        period=request.period,
        trade_plan_count=len(plan_results),
        closed_plan_count=closed_plan_count,
        open_plan_count=open_plan_count,
        winning_plans=len(winners),
        losing_plans=len(losers),
        win_rate=_safe_round(0.0 if not counted_results else len(winners) / len(counted_results)),
        gross_profit=_safe_round(gross_profit, 2),
        gross_loss=_safe_round(gross_loss, 2),
        net_pnl=_safe_round(net_pnl, 2),
        return_pct=_safe_round(net_pnl / request.initial_equity),
        expectancy=_safe_round(0.0 if not counted_results else net_pnl / len(counted_results), 2),
        profit_factor=_safe_round(_profit_factor(gross_profit, gross_loss)),
        average_win=_safe_round(0.0 if not winners else sum(winners) / len(winners), 2),
        average_loss=_safe_round(0.0 if not losers else sum(losers) / len(losers), 2),
        best_strategy_bucket=_best_key(by_strategy_bucket),
        worst_strategy_bucket=_worst_key(by_strategy_bucket),
        by_strategy_bucket=by_strategy_bucket,
        by_symbol=by_symbol,
        plan_results=plan_results,
        warnings=warnings,
    )
