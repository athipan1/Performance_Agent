from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.models import (
    EvidenceContribution,
    LEARNING_OUTCOME_VERSION,
    LearningOutcomeBatch,
    LearningOutcomeBuildRequest,
    LearningOutcomeRecord,
    PERFORMANCE_OUTCOME_VERSION,
    TradePlanFill,
    TradePlanLifecycleRecord,
)


KNOWN_BUCKETS = {
    "core_dividend",
    "value_rebound",
    "news_momentum",
}
LEARNABLE_EXECUTION_STATUSES = {
    "filled",
    "closed",
    "completed",
    "exited",
}
SUPPORTED_EVIDENCE_VERSIONS = {
    "scanner": "scanner-bucket-hints-v2",
    "fundamental": "fundamental-evidence-v1",
    "technical": "technical-evidence-v1",
    "manager": "manager-analysis-evidence-v1",
}
SUPPORTED_MANAGER_CLASSIFIER_VERSION = "manager-strategy-bucket-v3"


def _mapping(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _confidence(value: Any) -> float:
    number = _float(value)
    if number is None:
        return 0.0
    if abs(number) > 1.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 4)


def _datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket(value: Any) -> Optional[str]:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in KNOWN_BUCKETS else None


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _plan_contexts(plan: TradePlanLifecycleRecord) -> List[Dict[str, Any]]:
    raw_plan = _mapping(plan.plan)
    metadata = _mapping(plan.metadata)
    contexts: List[Dict[str, Any]] = [raw_plan, metadata]

    for parent in (raw_plan, metadata):
        for key in (
            "analysis",
            "portfolio_context",
            "strategy_bucket_classification",
            "evidence_summary",
            "execution",
            "order_metadata",
            "trade_plan_metadata",
        ):
            child = _mapping(parent.get(key))
            if child:
                contexts.append(child)
        analysis = _mapping(parent.get("analysis"))
        if analysis:
            for key in (
                "portfolio_context",
                "strategy_bucket_classification",
                "evidence_summary",
            ):
                child = _mapping(analysis.get(key))
                if child:
                    contexts.append(child)

    for event in _sequence(plan.lifecycle):
        event_data = _mapping(event)
        if event_data:
            contexts.append(event_data)
            event_metadata = _mapping(event_data.get("metadata"))
            if event_metadata:
                contexts.append(event_metadata)
    return contexts


def _find_mapping(
    contexts: Sequence[Mapping[str, Any]],
    key: str,
) -> Dict[str, Any]:
    for context in contexts:
        value = _mapping(context.get(key))
        if value:
            return value
    return {}


def _find_value(
    contexts: Sequence[Mapping[str, Any]],
    *keys: str,
) -> Any:
    for context in contexts:
        for key in keys:
            value = context.get(key)
            if value is not None and value != "":
                return value
    return None


def _collect_bucket_values(
    contexts: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> List[str]:
    values: List[str] = []
    for context in contexts:
        for key in keys:
            bucket = _bucket(context.get(key))
            if bucket and bucket not in values:
                values.append(bucket)
    return values


def _manager_buckets(
    plan: TradePlanLifecycleRecord,
    contexts: Sequence[Mapping[str, Any]],
) -> List[str]:
    values = _collect_bucket_values(
        contexts,
        (
            "manager_bucket",
            "manager_strategy_bucket",
            "requested_strategy_bucket",
        ),
    )
    raw_plan = _mapping(plan.plan)
    for value in (
        _nested(raw_plan, "strategy_bucket_classification", "bucket"),
        _nested(raw_plan, "portfolio_context", "strategy_bucket"),
        raw_plan.get("strategy_bucket"),
    ):
        bucket = _bucket(value)
        if bucket and bucket not in values:
            values.append(bucket)
    return values


def _execution_buckets(
    contexts: Sequence[Mapping[str, Any]],
) -> List[str]:
    return _collect_bucket_values(
        contexts,
        (
            "execution_bucket",
            "execution_strategy_bucket",
            "persisted_strategy_bucket",
            "requested_strategy_bucket",
            "order_strategy_bucket",
        ),
    )


def _index_fills(
    fills: Iterable[TradePlanFill],
) -> Tuple[
    Dict[str, List[TradePlanFill]],
    Dict[int, List[TradePlanFill]],
    int,
]:
    by_plan: Dict[str, List[TradePlanFill]] = defaultdict(list)
    by_order: Dict[int, List[TradePlanFill]] = defaultdict(list)
    unmatched = 0
    for fill in fills:
        matched = False
        if fill.trade_plan_id:
            by_plan[str(fill.trade_plan_id)].append(fill)
            matched = True
        if fill.order_id is not None:
            by_order[int(fill.order_id)].append(fill)
            matched = True
        if not matched:
            unmatched += 1
    return by_plan, by_order, unmatched


def _fills_for_plan(
    plan: TradePlanLifecycleRecord,
    fills_by_plan: Mapping[str, List[TradePlanFill]],
    fills_by_order: Mapping[int, List[TradePlanFill]],
) -> List[TradePlanFill]:
    result = list(fills_by_plan.get(str(plan.trade_plan_id), []))
    seen = {id(fill) for fill in result}
    if plan.order_id is not None:
        for fill in fills_by_order.get(int(plan.order_id), []):
            if id(fill) not in seen:
                result.append(fill)
                seen.add(id(fill))
    return result


def _realized_fills(fills: Sequence[TradePlanFill]) -> List[TradePlanFill]:
    return [fill for fill in fills if fill.realized_pnl is not None]


def _weighted_price(fills: Sequence[TradePlanFill]) -> Optional[float]:
    quantity = sum(float(fill.quantity) for fill in fills)
    if quantity <= 0:
        return None
    total = sum(
        float(fill.fill_price) * float(fill.quantity)
        for fill in fills
    )
    return round(total / quantity, 8)


def _entry_price(
    plan: TradePlanLifecycleRecord,
    contexts: Sequence[Mapping[str, Any]],
) -> Optional[float]:
    raw_plan = _mapping(plan.plan)
    return _float(
        _first(
            raw_plan.get("entry_price"),
            raw_plan.get("average_entry_price"),
            raw_plan.get("limit_price"),
            _find_value(
                contexts,
                "entry_price",
                "average_entry_price",
                "filled_entry_price",
            ),
        )
    )


def _opened_at(
    plan: TradePlanLifecycleRecord,
    contexts: Sequence[Mapping[str, Any]],
) -> Optional[datetime]:
    candidates = [
        plan.created_at,
        _find_value(
            contexts,
            "opened_at",
            "entry_filled_at",
            "entered_at",
            "created_at",
        ),
    ]
    parsed = [value for value in (_datetime(item) for item in candidates) if value]
    return min(parsed) if parsed else None


def _closed_at(
    plan: TradePlanLifecycleRecord,
    contexts: Sequence[Mapping[str, Any]],
    realized_fills: Sequence[TradePlanFill],
) -> Optional[datetime]:
    candidates: List[Any] = [
        plan.closed_at,
        _find_value(
            contexts,
            "closed_at",
            "exited_at",
            "exit_filled_at",
            "completed_at",
        ),
    ]
    candidates.extend(fill.filled_at for fill in realized_fills)
    if plan.updated_at is not None:
        candidates.append(plan.updated_at)
    parsed = [value for value in (_datetime(item) for item in candidates) if value]
    return max(parsed) if parsed else None


def _holding_period_days(
    opened_at: Optional[datetime],
    closed_at: Optional[datetime],
) -> float:
    if opened_at is None or closed_at is None or closed_at < opened_at:
        return 0.0
    return round((closed_at - opened_at).total_seconds() / 86400.0, 6)


def _evidence_summary(
    contexts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    summary = _find_mapping(contexts, "evidence_summary")
    if summary:
        return summary
    for context in contexts:
        if context.get("contract") == "manager-analysis-evidence-v1":
            return dict(context)
    return {}


def _classification(
    contexts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    classification = _find_mapping(
        contexts,
        "strategy_bucket_classification",
    )
    if classification:
        return classification
    for context in contexts:
        if context.get("classifier_version"):
            return dict(context)
    return {}


def _evidence_versions(
    contexts: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> Dict[str, str]:
    versions: Dict[str, str] = {}
    direct = _find_mapping(contexts, "evidence_versions")
    summary_versions = _mapping(summary.get("evidence_versions"))
    for source in ("scanner", "fundamental", "technical"):
        value = _first(direct.get(source), summary_versions.get(source))
        if value:
            versions[source] = str(value)
    manager_version = _first(
        direct.get("manager"),
        summary.get("contract"),
        _find_value(contexts, "manager_evidence_version"),
    )
    if manager_version:
        versions["manager"] = str(manager_version)
    return versions


def _source_statuses(
    contexts: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    classification: Mapping[str, Any],
) -> Dict[str, str]:
    statuses = _find_mapping(contexts, "evidence_statuses")
    statuses.update(_mapping(summary.get("evidence_statuses")))
    manager_status = _first(
        statuses.get("manager"),
        classification.get("status"),
        _find_value(contexts, "bucket_classification_status"),
    )
    if manager_status:
        statuses["manager"] = str(manager_status)
    return {str(key): str(value) for key, value in statuses.items() if value}


def _classification_reasons(
    contexts: Sequence[Mapping[str, Any]],
    classification: Mapping[str, Any],
) -> List[str]:
    reasons = classification.get("reasons")
    if not isinstance(reasons, list):
        reasons = _find_value(
            contexts,
            "bucket_classification_reasons",
            "classification_reasons",
        )
    return [str(reason) for reason in _sequence(reasons)]


def _explicit_contributions(
    contexts: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    return _find_mapping(contexts, "evidence_contributions")


def _source_supported_bucket(
    source: str,
    final_bucket: str,
    classification_inputs: Mapping[str, Any],
    reasons: Sequence[str],
) -> Optional[str]:
    if source == "manager":
        return final_bucket
    if source == "scanner":
        scanner = _mapping(classification_inputs.get("scanner"))
        return _bucket(scanner.get("primary_hint"))

    reason_text = " ".join(reasons).lower()
    if source == "fundamental":
        markers = {
            "core_dividend": (
                "dividend_yield",
                "defensive_sector",
                "quality_score",
                "quality_cashflow_low_debt",
            ),
            "value_rebound": (
                "low_pe_ratio",
                "low_pb_ratio",
                "valuation_score",
                "value_evidence",
            ),
            "news_momentum": (
                "growth_score",
                "growth_technical_corroboration",
            ),
        }
        if any(marker in reason_text for marker in markers[final_bucket]):
            return final_bucket
    if source == "technical" and final_bucket == "news_momentum":
        if any(
            marker in reason_text
            for marker in (
                "technical_momentum_trend",
                "breakout_confirmation",
                "growth_technical_corroboration",
            )
        ):
            return final_bucket
    return None


def _source_confidence(
    source: str,
    bucket_confidence: float,
    classification_inputs: Mapping[str, Any],
) -> float:
    source_inputs = _mapping(classification_inputs.get(source))
    if source == "manager":
        return bucket_confidence
    if source == "scanner":
        return _confidence(source_inputs.get("primary_confidence"))
    candidate_keys = (
        (
            "quality_score",
            "valuation_score",
            "growth_score",
            "fundamental_score",
        )
        if source == "fundamental"
        else (
            "technical_score",
            "momentum_score",
            "trend_score",
            "indicator_score",
            "technical_vote_score",
        )
    )
    return max(
        (_confidence(source_inputs.get(key)) for key in candidate_keys),
        default=0.0,
    )


def _build_contributions(
    contexts: Sequence[Mapping[str, Any]],
    versions: Mapping[str, str],
    statuses: Mapping[str, str],
    final_bucket: str,
    bucket_confidence: float,
    classification_inputs: Mapping[str, Any],
    reasons: Sequence[str],
) -> Dict[str, EvidenceContribution]:
    explicit = _explicit_contributions(contexts)
    contributions: Dict[str, EvidenceContribution] = {}
    for source in ("scanner", "fundamental", "technical", "manager"):
        explicit_source = _mapping(explicit.get(source))
        supported_bucket = _bucket(explicit_source.get("supported_bucket"))
        if supported_bucket is None:
            supported_bucket = _source_supported_bucket(
                source,
                final_bucket,
                classification_inputs,
                reasons,
            )
        confidence = _confidence(explicit_source.get("confidence"))
        if confidence == 0.0:
            confidence = _source_confidence(
                source,
                bucket_confidence,
                classification_inputs,
            )
        explicit_reasons = _sequence(explicit_source.get("reasons"))
        contribution_reasons = [str(value) for value in explicit_reasons]
        if not contribution_reasons:
            contribution_reasons = [
                "preserved_or_derived_by_performance_outcome_v1"
            ]
        contributions[source] = EvidenceContribution(
            version=str(versions.get(source) or ""),
            supported_bucket=supported_bucket,
            confidence=confidence,
            evidence_status=str(statuses.get(source) or ""),
            reasons=contribution_reasons,
        )
    return contributions


def _record_issues(
    plan: TradePlanLifecycleRecord,
    plan_fills: Sequence[TradePlanFill],
    contexts: Sequence[Mapping[str, Any]],
) -> Tuple[List[str], Dict[str, Any]]:
    issues: List[str] = []
    execution_status = str(
        _first(
            _find_value(
                contexts,
                "execution_status",
                "order_status",
            ),
            plan.status,
        )
        or ""
    ).strip().lower()
    if execution_status not in LEARNABLE_EXECUTION_STATUSES:
        issues.append(f"execution_not_complete:{execution_status or 'missing'}")

    realized_fills = _realized_fills(plan_fills)
    if not realized_fills:
        issues.append("realized_pnl_missing")

    entry_price = _entry_price(plan, contexts)
    exit_price = _weighted_price(realized_fills)
    if entry_price is None or entry_price <= 0:
        issues.append("entry_price_missing")
    if exit_price is None or exit_price <= 0:
        issues.append("exit_price_missing")

    database_bucket = _bucket(plan.strategy_bucket)
    manager_buckets = _manager_buckets(plan, contexts)
    execution_buckets = _execution_buckets(contexts)
    if database_bucket is None:
        issues.append(f"invalid_database_bucket:{plan.strategy_bucket}")
    if not manager_buckets:
        issues.append("manager_bucket_missing")
    elif len(manager_buckets) > 1:
        issues.append(
            "manager_bucket_conflict:" + ",".join(manager_buckets)
        )
    if not execution_buckets:
        issues.append("execution_bucket_missing")
    elif len(execution_buckets) > 1:
        issues.append(
            "execution_bucket_conflict:" + ",".join(execution_buckets)
        )

    manager_bucket = manager_buckets[0] if len(manager_buckets) == 1 else None
    execution_bucket = (
        execution_buckets[0] if len(execution_buckets) == 1 else None
    )
    comparable = [
        value
        for value in (database_bucket, manager_bucket, execution_bucket)
        if value is not None
    ]
    if len(comparable) == 3 and len(set(comparable)) != 1:
        issues.append(
            "strategy_bucket_mismatch:"
            f"manager={manager_bucket},"
            f"execution={execution_bucket},"
            f"database={database_bucket}"
        )

    risk_approved = bool(
        _first(
            _find_value(contexts, "risk_approved"),
            plan.risk_approval_id,
        )
    )
    if not risk_approved:
        issues.append("risk_not_approved")

    summary = _evidence_summary(contexts)
    classification = _classification(contexts)
    evidence_gate_passed = _first(
        classification.get("evidence_gate_passed"),
        _find_value(contexts, "evidence_gate_passed"),
        summary.get("gate_passed"),
    )
    if evidence_gate_passed is not True:
        issues.append("manager_evidence_gate_not_passed")

    classification_status = str(
        _first(
            classification.get("status"),
            _find_value(contexts, "bucket_classification_status"),
        )
        or ""
    ).strip().lower()
    if classification_status != "classified":
        issues.append(
            f"manager_classification_not_approved:"
            f"{classification_status or 'missing'}"
        )

    classifier_version = str(
        _first(
            classification.get("classifier_version"),
            _find_value(contexts, "bucket_classifier_version"),
        )
        or ""
    )
    if classifier_version != SUPPORTED_MANAGER_CLASSIFIER_VERSION:
        issues.append(
            "unsupported_manager_classifier_version:"
            f"{classifier_version or 'missing'}"
        )

    versions = _evidence_versions(contexts, summary)
    for source, expected in SUPPORTED_EVIDENCE_VERSIONS.items():
        actual = versions.get(source)
        if actual != expected:
            issues.append(
                f"unsupported_{source}_evidence_version:"
                f"{actual or 'missing'}"
            )

    statuses = _source_statuses(contexts, summary, classification)
    for source in ("scanner", "fundamental", "technical", "manager"):
        status = str(statuses.get(source) or "").strip().lower()
        if not status:
            issues.append(f"missing_{source}_evidence_status")
        elif status in {
            "insufficient",
            "insufficient_evidence",
            "invalid",
            "conflict",
            "review",
            "unassigned",
        }:
            issues.append(f"{source}_evidence_not_learnable:{status}")

    classification_inputs = _mapping(summary.get("classification_inputs"))
    if not classification_inputs:
        classification_inputs = _find_mapping(
            contexts,
            "classification_inputs",
        )
    if not classification_inputs:
        issues.append("classification_inputs_missing")

    details = {
        "execution_status": execution_status,
        "realized_fills": realized_fills,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "database_bucket": database_bucket,
        "manager_bucket": manager_bucket,
        "execution_bucket": execution_bucket,
        "risk_approved": risk_approved,
        "summary": summary,
        "classification": classification,
        "classifier_version": classifier_version,
        "versions": versions,
        "statuses": statuses,
        "classification_inputs": classification_inputs,
    }
    return list(dict.fromkeys(issues)), details


def _build_record(
    plan: TradePlanLifecycleRecord,
    contexts: Sequence[Mapping[str, Any]],
    details: Mapping[str, Any],
) -> LearningOutcomeRecord:
    realized_fills = list(details["realized_fills"])
    realized_pnl = round(
        sum(float(fill.realized_pnl or 0.0) for fill in realized_fills),
        8,
    )
    quantity = sum(float(fill.quantity) for fill in realized_fills)
    entry_price = float(details["entry_price"])
    exit_price = float(details["exit_price"])
    notional = entry_price * quantity
    return_pct = 0.0 if notional <= 0 else round(realized_pnl / notional, 8)

    opened_at = _opened_at(plan, contexts)
    closed_at = _closed_at(plan, contexts, realized_fills)
    final_bucket = str(details["database_bucket"])
    classification = _mapping(details["classification"])
    reasons = _classification_reasons(contexts, classification)
    bucket_confidence = _confidence(
        _first(
            classification.get("confidence"),
            _find_value(contexts, "bucket_confidence"),
        )
    )
    contributions = _build_contributions(
        contexts,
        details["versions"],
        details["statuses"],
        final_bucket,
        bucket_confidence,
        details["classification_inputs"],
        reasons,
    )
    exit_reason = str(
        _first(
            _find_value(
                contexts,
                "exit_reason",
                "close_reason",
                "completion_reason",
            ),
            "unspecified",
        )
    )

    return LearningOutcomeRecord(
        outcome_version=LEARNING_OUTCOME_VERSION,
        outcome_id=f"performance:{plan.trade_plan_id}:realized",
        trade_plan_id=plan.trade_plan_id,
        account_id=plan.account_id,
        symbol=plan.symbol.upper(),
        strategy_bucket=final_bucket,
        manager_bucket=str(details["manager_bucket"]),
        execution_bucket=str(details["execution_bucket"]),
        database_bucket=final_bucket,
        manager_classifier_version=str(details["classifier_version"]),
        evidence_versions=dict(details["versions"]),
        evidence_contributions=contributions,
        classification_inputs=dict(details["classification_inputs"]),
        bucket_confidence=bucket_confidence,
        entry_price=entry_price,
        exit_price=exit_price,
        realized_pnl=realized_pnl,
        return_pct=return_pct,
        holding_period_days=_holding_period_days(opened_at, closed_at),
        exit_reason=exit_reason,
        risk_approved=bool(details["risk_approved"]),
        execution_status=str(details["execution_status"]),
        outcome_status="closed",
        pnl_status="realized",
    )


def build_learning_outcomes(
    request: LearningOutcomeBuildRequest,
) -> LearningOutcomeBatch:
    fills_by_plan, fills_by_order, unmatched = _index_fills(request.fills)
    outcomes: List[LearningOutcomeRecord] = []
    rejected: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen_plan_ids: set[str] = set()

    for plan in request.trade_plans:
        if plan.trade_plan_id in seen_plan_ids:
            rejected.append(
                {
                    "trade_plan_id": plan.trade_plan_id,
                    "symbol": plan.symbol,
                    "issues": ["duplicate_trade_plan_id"],
                }
            )
            continue
        seen_plan_ids.add(plan.trade_plan_id)

        contexts = _plan_contexts(plan)
        plan_fills = _fills_for_plan(
            plan,
            fills_by_plan,
            fills_by_order,
        )
        issues, details = _record_issues(
            plan,
            plan_fills,
            contexts,
        )
        if issues:
            rejected.append(
                {
                    "trade_plan_id": plan.trade_plan_id,
                    "symbol": plan.symbol.upper(),
                    "issues": issues,
                }
            )
            continue
        outcomes.append(_build_record(plan, contexts, details))

    if unmatched:
        warnings.append(
            f"{unmatched} fill(s) could not be matched to a TradePlan"
        )
    if not request.trade_plans:
        warnings.append("No TradePlan records were provided")
    if any(outcome.holding_period_days == 0.0 for outcome in outcomes):
        warnings.append(
            "Some outcomes lack complete open/close timestamps; "
            "holding_period_days defaults to 0"
        )
    if any(outcome.exit_reason == "unspecified" for outcome in outcomes):
        warnings.append(
            "Some outcomes do not contain an explicit exit_reason"
        )

    return LearningOutcomeBatch(
        performance_contract_version=PERFORMANCE_OUTCOME_VERSION,
        learning_contract_version=LEARNING_OUTCOME_VERSION,
        reviewed_trade_plans=len(request.trade_plans),
        generated_outcomes=len(outcomes),
        rejected_trade_plans=len(rejected),
        outcomes=outcomes,
        rejected_records=rejected,
        warnings=warnings,
        requires_human_review=True,
        auto_apply=False,
    )
