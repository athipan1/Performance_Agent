from __future__ import annotations

from typing import Any, Mapping


SCHEMA_VERSION = "forward-shadow-evidence.v1"
MIN_OBSERVATIONS = 100
MIN_PROFIT_FACTOR = 1.10
MAX_DRAWDOWN_PCT = 0.10


def build_forward_evidence(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Convert Shadow performance into strict advisory promotion evidence."""
    count = int(summary.get("observation_count") or 0)
    expectancy = summary.get("net_expectancy_pct")
    profit_factor = summary.get("profit_factor")
    drawdown = summary.get("max_drawdown_pct")
    avg_cost = summary.get("average_cost_pct")
    gates = {
        "minimum_observations": count >= MIN_OBSERVATIONS,
        "positive_net_expectancy": expectancy is not None and float(expectancy) > 0,
        "profit_factor": profit_factor is not None and float(profit_factor) >= MIN_PROFIT_FACTOR,
        "max_drawdown": drawdown is not None and float(drawdown) <= MAX_DRAWDOWN_PCT,
        "cost_evidence_present": avg_cost is not None,
    }
    failed = [name for name, passed in gates.items() if not passed]
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_count": count,
        "net_expectancy_pct": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown_pct": drawdown,
        "average_cost_pct": avg_cost,
        "gates": gates,
        "failed_gates": failed,
        "forward_review_ready": not failed,
        "advisory_only": True,
        "broker_order_authorized": False,
        "risk_policy_change_authorized": False,
    }
