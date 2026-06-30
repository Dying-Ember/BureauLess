from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..errors import ProtocolError
from ..protocol.budget import estimate_cost_from_snapshot, load_price_snapshot
from .advisors import summarize_advisor_scores


@dataclass(frozen=True)
class MetricsEntry:
    assignment_id: str
    status: str
    agent_id: str
    role: str
    task_type: str
    risk_level: str
    model: str
    provider: str
    workflow_mode: str
    wall_time_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    cost_source: str
    cost_confidence: str
    changed_files_count: int | None
    verification_status: str | None
    review_status: str | None
    usage_confidence: str
    context_policy_version: str
    context_capsule_tokens: int | None
    included_fact_ids: list[str]
    included_artifact_refs: list[str]
    context_requests: list[dict[str, Any]]
    first_pass_success: bool | None
    rework_required: bool | None
    context_fit_classification: str
    context_fit_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "status": self.status,
            "agent_id": self.agent_id,
            "role": self.role,
            "task_type": self.task_type,
            "risk_level": self.risk_level,
            "model": self.model,
            "provider": self.provider,
            "workflow_mode": self.workflow_mode,
            "wall_time_ms": self.wall_time_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "cost_source": self.cost_source,
            "cost_confidence": self.cost_confidence,
            "changed_files_count": self.changed_files_count,
            "verification_status": self.verification_status,
            "review_status": self.review_status,
            "usage_confidence": self.usage_confidence,
            "context_policy_version": self.context_policy_version,
            "context_capsule_tokens": self.context_capsule_tokens,
            "included_fact_ids": self.included_fact_ids,
            "included_artifact_refs": self.included_artifact_refs,
            "context_requests": self.context_requests,
            "first_pass_success": self.first_pass_success,
            "rework_required": self.rework_required,
            "context_fit_classification": self.context_fit_classification,
            "context_fit_reason": self.context_fit_reason,
        }


@dataclass(frozen=True)
class ObservedRuntimeBudget:
    session_count: int
    completed_count: int
    total_tokens_used: int
    total_cost_usd: float | None
    known_cost_usd_total: float
    missing_usage_count: int
    missing_cost_count: int
    observed_coordination_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_count": self.session_count,
            "completed_count": self.completed_count,
            "total_tokens_used": self.total_tokens_used,
            "total_cost_usd": self.total_cost_usd,
            "known_cost_usd_total": self.known_cost_usd_total,
            "missing_usage_count": self.missing_usage_count,
            "missing_cost_count": self.missing_cost_count,
            "observed_coordination_ratio": self.observed_coordination_ratio,
        }


def summarize_metrics(path: Path, price_snapshot_path: Path | None = None) -> dict[str, Any]:
    entries = _load_entries(path)
    advisor_outcomes = _load_advisor_outcomes(path)
    advisor_score_summary = _load_advisor_score_summary(path)
    if price_snapshot_path is not None:
        snapshot = load_price_snapshot(price_snapshot_path)
        entries = [_apply_price_snapshot(entry, snapshot) for entry in entries]
    return {
        "entries": [entry.to_dict() for entry in entries],
        "summary": _group_entries(entries),
        "observed_budget": _observed_budget(entries).to_dict(),
        "advisor_outcomes": advisor_outcomes,
        "advisor_score_summary": advisor_score_summary,
        "context_summary": _summarize_context(entries),
        "policy_recommendations": _policy_recommendations(entries),
    }


def _load_entries(path: Path) -> list[MetricsEntry]:
    if path.is_dir():
        entries: list[MetricsEntry] = []
        for record_path in sorted(path.glob("*.yaml")):
            data = _load_yaml(record_path)
            entries.extend(_entries_from_mapping(data))
        return entries

    data = _load_yaml(path)
    return _entries_from_mapping(data)


def _load_advisor_outcomes(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        outcomes: list[dict[str, Any]] = []
        for record_path in sorted(path.glob("*.yaml")):
            data = _load_yaml(record_path)
            outcomes.extend(_advisor_outcomes_from_mapping(data))
        return outcomes
    return _advisor_outcomes_from_mapping(_load_yaml(path))


def _load_advisor_score_summary(path: Path) -> dict[str, Any]:
    if path.is_dir():
        return {
            "scores": [],
            "classification_counts": {
                "good_call": 0,
                "bad_call": 0,
                "good_skip": 0,
                "missed_call": 0,
            },
            "insufficient_evidence_count": 0,
        }
    data = _load_yaml(path)
    if "event_log" not in data:
        return {
            "scores": [],
            "classification_counts": {
                "good_call": 0,
                "bad_call": 0,
                "good_skip": 0,
                "missed_call": 0,
            },
            "insufficient_evidence_count": 0,
        }
    ledger = load_ledger_from_mapping(data)
    return summarize_advisor_scores(
        ledger,
        artifact_root=path.parent,
    )


def _entries_from_mapping(data: dict[str, Any]) -> list[MetricsEntry]:
    if "event_log" in data:
        return _entries_from_ledger_mapping(data)
    if "session_id" in data:
        return [_entry_from_session_mapping(data)]
    raise ProtocolError("Metrics summarize expects a ledger YAML or session YAML")


def _advisor_outcomes_from_mapping(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "event_log" not in data:
        return []
    ledger = load_ledger_from_mapping(data)
    outcomes: list[dict[str, Any]] = []
    for event in ledger.event_log:
        if event.get("event_type") != "advisor_outcome_recorded":
            continue
        payload = {
            "advisor_outcome_id": _string_or_unknown(event.get("advisor_outcome_id")),
            "status": _string_or_unknown(event.get("status")),
            "source_decision_type": _string_or_unknown(event.get("source_decision_type")),
            "source_decision_ref": _string_or_unknown(event.get("source_decision_ref")),
            "advisor_decision_ref": _string_or_unknown(event.get("advisor_decision_ref")),
            "outcome_ref": _string_or_unknown(event.get("outcome_ref")),
            "classification": _string_or_none(event.get("classification")),
            "pending_reason": _string_or_none(event.get("pending_reason")),
            "actual_advisor_tokens": _int_or_none(event.get("actual_advisor_tokens")),
            "actual_total_tokens": _int_or_none(event.get("actual_total_tokens")),
            "rework_count": _int_or_none(event.get("rework_count")),
            "broadcast_tokens": _int_or_none(event.get("broadcast_tokens")),
            "duplicate_context_observed": _bool_or_none(
                event.get("duplicate_context_observed")
            ),
            "price_snapshot_attribution": _mapping_or_none(
                event.get("price_snapshot_attribution")
            ),
        }
        outcomes.append(payload)
    return outcomes


def _entries_from_ledger_mapping(data: dict[str, Any]) -> list[MetricsEntry]:
    ledger = load_ledger_from_mapping(data)
    entries: list[MetricsEntry] = []
    for event in ledger.event_log:
        if event.get("event_type") != "result_submitted":
            continue
        result = event.get("result", {})
        if not isinstance(result, dict):
            continue
        outcome_metrics = result.get("outcome_metrics", {})
        if not isinstance(outcome_metrics, dict):
            outcome_metrics = {}
        verification = result.get("verification", {})
        if not isinstance(verification, dict):
            verification = {}
        context_delivery = _mapping_or_empty(result.get("context_delivery"))
        context_requests = _mapping_list_or_empty(result.get("context_requests"))
        outcome = _mapping_or_empty(result.get("outcome"))
        classification, reason = _classify_context_fit(
            context_delivery=context_delivery,
            context_requests=context_requests,
            review_status=_string_or_none(result.get("review_status")),
            verification_status=_string_or_none(verification.get("status")),
            first_pass_success=_bool_or_none(outcome.get("first_pass_success")),
            rework_required=_bool_or_none(outcome.get("rework_required")),
        )
        entries.append(
            MetricsEntry(
                assignment_id=_string_or_unknown(result.get("assignment_id")),
                status=_string_or_unknown(result.get("status")),
                agent_id=_string_or_unknown(result.get("agent_id")),
                role=_string_or_unknown(result.get("role")),
                task_type=_string_or_unknown(result.get("task_type")),
                risk_level=_string_or_unknown(result.get("risk_level")),
                model=_string_or_unknown(result.get("effective_model")),
                provider=_string_or_unknown(result.get("effective_provider")),
                workflow_mode=_string_or_unknown(event.get("workflow_mode")),
                wall_time_ms=_int_or_none(outcome_metrics.get("wall_time_ms")),
                input_tokens=_int_or_none(outcome_metrics.get("input_tokens")),
                output_tokens=_int_or_none(outcome_metrics.get("output_tokens")),
                total_tokens=_int_or_none(outcome_metrics.get("total_tokens")),
                cost_usd=_float_or_none(outcome_metrics.get("cost_usd")),
                cost_source=_string_or_unknown(outcome_metrics.get("cost_source"), "unknown"),
                cost_confidence=_string_or_unknown(outcome_metrics.get("cost_confidence"), "none"),
                changed_files_count=_int_or_none(outcome_metrics.get("changed_files_count")),
                verification_status=_string_or_none(verification.get("status")),
                review_status=_string_or_none(result.get("review_status")),
                usage_confidence=_string_or_unknown(outcome_metrics.get("usage_confidence"), "none"),
                context_policy_version=_string_or_unknown(
                    context_delivery.get("policy_version"),
                    "unknown",
                ),
                context_capsule_tokens=_int_or_none(context_delivery.get("capsule_tokens")),
                included_fact_ids=_string_list(context_delivery.get("included_fact_ids")),
                included_artifact_refs=_string_list(
                    context_delivery.get("included_artifact_refs")
                ),
                context_requests=context_requests,
                first_pass_success=_bool_or_none(outcome.get("first_pass_success")),
                rework_required=_bool_or_none(outcome.get("rework_required")),
                context_fit_classification=classification,
                context_fit_reason=reason,
            )
        )
    return entries


def _entry_from_session_mapping(data: dict[str, Any]) -> MetricsEntry:
    outcome_metrics = data.get("outcome_metrics", {})
    if not isinstance(outcome_metrics, dict):
        outcome_metrics = {}
    result_proposal = data.get("result_proposal", {})
    if not isinstance(result_proposal, dict):
        result_proposal = {}
    verification = result_proposal.get("verification", {})
    if not isinstance(verification, dict):
        verification = {}
    context_delivery = _mapping_or_empty(data.get("context_delivery"))
    context_requests = _mapping_list_or_empty(data.get("context_requests"))
    outcome = _mapping_or_empty(data.get("outcome"))
    model = data.get("effective_model")
    if not isinstance(model, str) or not model:
        model = result_proposal.get("effective_model")
    provider = data.get("effective_provider")
    if not isinstance(provider, str) or not provider:
        provider = result_proposal.get("effective_provider")
    classification, reason = _classify_context_fit(
        context_delivery=context_delivery,
        context_requests=context_requests,
        review_status=_string_or_none(result_proposal.get("review_status")),
        verification_status=_string_or_none(verification.get("status")),
        first_pass_success=_bool_or_none(outcome.get("first_pass_success")),
        rework_required=_bool_or_none(outcome.get("rework_required")),
    )

    return MetricsEntry(
        assignment_id=_string_or_unknown(data.get("assignment_id")),
        status=_string_or_unknown(data.get("status")),
        agent_id=_string_or_unknown(data.get("agent_id")),
        role=_string_or_unknown(data.get("role")),
        task_type=_string_or_unknown(data.get("task_type")),
        risk_level=_string_or_unknown(data.get("risk_level")),
        model=_string_or_unknown(model),
        provider=_string_or_unknown(provider),
        workflow_mode=_string_or_unknown(data.get("workflow_mode")),
        wall_time_ms=_int_or_none(outcome_metrics.get("wall_time_ms")),
        input_tokens=_int_or_none(outcome_metrics.get("input_tokens")),
        output_tokens=_int_or_none(outcome_metrics.get("output_tokens")),
        total_tokens=_int_or_none(outcome_metrics.get("total_tokens")),
        cost_usd=_float_or_none(outcome_metrics.get("cost_usd")),
        cost_source=_string_or_unknown(outcome_metrics.get("cost_source"), "unknown"),
        cost_confidence=_string_or_unknown(outcome_metrics.get("cost_confidence"), "none"),
        changed_files_count=_int_or_none(outcome_metrics.get("changed_files_count")),
        verification_status=_string_or_none(verification.get("status")),
        review_status=_string_or_none(result_proposal.get("review_status")),
        usage_confidence=_string_or_unknown(outcome_metrics.get("usage_confidence"), "none"),
        context_policy_version=_string_or_unknown(context_delivery.get("policy_version"), "unknown"),
        context_capsule_tokens=_int_or_none(context_delivery.get("capsule_tokens")),
        included_fact_ids=_string_list(context_delivery.get("included_fact_ids")),
        included_artifact_refs=_string_list(context_delivery.get("included_artifact_refs")),
        context_requests=context_requests,
        first_pass_success=_bool_or_none(outcome.get("first_pass_success")),
        rework_required=_bool_or_none(outcome.get("rework_required")),
        context_fit_classification=classification,
        context_fit_reason=reason,
    )


def _group_entries(entries: list[MetricsEntry]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (
            entry.agent_id,
            entry.role,
            entry.task_type,
            entry.risk_level,
            entry.model,
            entry.provider,
            entry.context_policy_version,
        )
        bucket = grouped.setdefault(
            key,
            {
                "agent_id": entry.agent_id,
                "role": entry.role,
                "task_type": entry.task_type,
                "risk_level": entry.risk_level,
                "model": entry.model,
                "provider": entry.provider,
                "workflow_mode": entry.workflow_mode,
                "context_policy_version": entry.context_policy_version,
                "count": 0,
                "completed": 0,
                "wall_time_ms_total": 0,
                "total_tokens_total": 0,
                "cost_usd_total": 0.0,
                "missing_usage_count": 0,
                "context_request_count": 0,
                "under_provisioned_count": 0,
                "over_provisioned_count": 0,
                "mis_scoped_count": 0,
                "insufficient_evidence_count": 0,
            },
        )
        bucket["count"] += 1
        if entry.status == "completed":
            bucket["completed"] += 1
        if entry.wall_time_ms is not None:
            bucket["wall_time_ms_total"] += entry.wall_time_ms
        if entry.total_tokens is not None:
            bucket["total_tokens_total"] += entry.total_tokens
        else:
            bucket["missing_usage_count"] += 1
        if entry.cost_usd is not None:
            bucket["cost_usd_total"] += entry.cost_usd
        bucket["context_request_count"] += len(entry.context_requests)
        if entry.context_fit_classification == "under_provisioned":
            bucket["under_provisioned_count"] += 1
        elif entry.context_fit_classification == "over_provisioned":
            bucket["over_provisioned_count"] += 1
        elif entry.context_fit_classification == "mis_scoped":
            bucket["mis_scoped_count"] += 1
        elif entry.context_fit_classification == "insufficient_evidence":
            bucket["insufficient_evidence_count"] += 1
    return [grouped[key] for key in sorted(grouped)]


def _observed_budget(entries: list[MetricsEntry]) -> ObservedRuntimeBudget:
    coordination_modes = {"single_agent_with_review", "small_dag", "parallel_swarm"}
    total_tokens_used = 0
    known_cost_usd_total = 0.0
    missing_cost_count = 0
    coordination_tokens = 0
    known_mode_tokens = 0

    for entry in entries:
        if entry.total_tokens is not None:
            total_tokens_used += entry.total_tokens
            if entry.workflow_mode != "unknown":
                known_mode_tokens += entry.total_tokens
                if entry.workflow_mode in coordination_modes:
                    coordination_tokens += entry.total_tokens
        if entry.cost_usd is not None:
            known_cost_usd_total += entry.cost_usd
        else:
            missing_cost_count += 1

    observed_coordination_ratio = None
    if known_mode_tokens > 0:
        observed_coordination_ratio = round(coordination_tokens / known_mode_tokens, 6)

    return ObservedRuntimeBudget(
        session_count=len(entries),
        completed_count=sum(1 for entry in entries if entry.status == "completed"),
        total_tokens_used=total_tokens_used,
        total_cost_usd=None if missing_cost_count else round(known_cost_usd_total, 6),
        known_cost_usd_total=round(known_cost_usd_total, 6),
        missing_usage_count=sum(1 for entry in entries if entry.total_tokens is None),
        missing_cost_count=missing_cost_count,
        observed_coordination_ratio=observed_coordination_ratio,
    )


def _apply_price_snapshot(entry: MetricsEntry, snapshot: dict[str, Any]) -> MetricsEntry:
    if entry.cost_usd is not None:
        return entry
    estimate = estimate_cost_from_snapshot(
        snapshot,
        entry.model,
        entry.input_tokens,
        entry.output_tokens,
    )
    return MetricsEntry(
        assignment_id=entry.assignment_id,
        status=entry.status,
        agent_id=entry.agent_id,
        role=entry.role,
        task_type=entry.task_type,
        risk_level=entry.risk_level,
        model=entry.model,
        provider=entry.provider,
        workflow_mode=entry.workflow_mode,
        wall_time_ms=entry.wall_time_ms,
        input_tokens=entry.input_tokens,
        output_tokens=entry.output_tokens,
        total_tokens=entry.total_tokens,
        cost_usd=estimate.cost_usd,
        cost_source=estimate.source,
        cost_confidence=estimate.confidence,
        changed_files_count=entry.changed_files_count,
        verification_status=entry.verification_status,
        review_status=entry.review_status,
        usage_confidence=entry.usage_confidence,
        context_policy_version=entry.context_policy_version,
        context_capsule_tokens=entry.context_capsule_tokens,
        included_fact_ids=entry.included_fact_ids,
        included_artifact_refs=entry.included_artifact_refs,
        context_requests=entry.context_requests,
        first_pass_success=entry.first_pass_success,
        rework_required=entry.rework_required,
        context_fit_classification=entry.context_fit_classification,
        context_fit_reason=entry.context_fit_reason,
    )


def _summarize_context(entries: list[MetricsEntry]) -> dict[str, Any]:
    total_requests = sum(len(entry.context_requests) for entry in entries)
    total_added_tokens = 0
    repeated_requests: dict[str, int] = {}
    fit_counts = {
        "under_provisioned": 0,
        "well_provisioned": 0,
        "over_provisioned": 0,
        "mis_scoped": 0,
        "insufficient_evidence": 0,
    }
    for entry in entries:
        fit_counts[entry.context_fit_classification] = (
            fit_counts.get(entry.context_fit_classification, 0) + 1
        )
        for request in entry.context_requests:
            total_added_tokens += _int_or_zero(request.get("added_tokens"))
            for ref in _string_list(request.get("requested_refs")):
                repeated_requests[ref] = repeated_requests.get(ref, 0) + 1
    return {
        "entry_count": len(entries),
        "total_context_requests": total_requests,
        "total_added_tokens": total_added_tokens,
        "fit_counts": fit_counts,
        "repeated_requested_refs": [
            {"ref": ref, "count": count}
            for ref, count in sorted(repeated_requests.items())
            if count > 1
        ],
    }


def _policy_recommendations(entries: list[MetricsEntry]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (
            entry.role,
            entry.task_type,
            entry.risk_level,
            entry.model,
            entry.context_policy_version,
        )
        bucket = grouped.setdefault(
            key,
            {
                "role": entry.role,
                "task_type": entry.task_type,
                "risk_level": entry.risk_level,
                "model": entry.model,
                "policy_version": entry.context_policy_version,
                "request_counts": {},
                "under_provisioned_count": 0,
                "mis_scoped_count": 0,
                "insufficient_evidence_count": 0,
            },
        )
        if entry.context_fit_classification == "under_provisioned":
            bucket["under_provisioned_count"] += 1
        elif entry.context_fit_classification == "mis_scoped":
            bucket["mis_scoped_count"] += 1
        elif entry.context_fit_classification == "insufficient_evidence":
            bucket["insufficient_evidence_count"] += 1
        for request in entry.context_requests:
            for ref in _string_list(request.get("requested_refs")):
                counts = bucket["request_counts"]
                counts[ref] = counts.get(ref, 0) + 1

    recommendations: list[dict[str, Any]] = []
    for key in sorted(grouped):
        bucket = grouped[key]
        for ref, count in sorted(bucket["request_counts"].items()):
            if count >= 2 and bucket["under_provisioned_count"] > 0:
                recommendations.append(
                    {
                        "recommendation_type": "promote_requested_evidence",
                        "policy_version": bucket["policy_version"],
                        "role": bucket["role"],
                        "task_type": bucket["task_type"],
                        "risk_level": bucket["risk_level"],
                        "model": bucket["model"],
                        "target_ref": ref,
                        "request_count": count,
                        "evidence_basis": "repeated_context_requests",
                        "auto_apply": False,
                    }
                )
        if bucket["mis_scoped_count"] >= 2:
            recommendations.append(
                {
                    "recommendation_type": "review_scope_filters",
                    "policy_version": bucket["policy_version"],
                    "role": bucket["role"],
                    "task_type": bucket["task_type"],
                    "risk_level": bucket["risk_level"],
                    "model": bucket["model"],
                    "mis_scoped_count": bucket["mis_scoped_count"],
                    "auto_apply": False,
                }
            )
        if bucket["insufficient_evidence_count"] >= 2:
            recommendations.append(
                {
                    "recommendation_type": "audit_evidence_availability",
                    "policy_version": bucket["policy_version"],
                    "role": bucket["role"],
                    "task_type": bucket["task_type"],
                    "risk_level": bucket["risk_level"],
                    "model": bucket["model"],
                    "insufficient_evidence_count": bucket["insufficient_evidence_count"],
                    "auto_apply": False,
                }
            )
    return recommendations


def _classify_context_fit(
    *,
    context_delivery: dict[str, Any],
    context_requests: list[dict[str, Any]],
    review_status: str | None,
    verification_status: str | None,
    first_pass_success: bool | None,
    rework_required: bool | None,
) -> tuple[str, str | None]:
    denied_count = 0
    unavailable_count = 0
    granted_count = 0
    added_tokens = 0
    for request in context_requests:
        denied_count += len(_mapping_list_or_empty(request.get("denied_refs")))
        unavailable_count += len(_mapping_list_or_empty(request.get("unavailable_refs")))
        granted_count += len(_mapping_list_or_empty(request.get("granted_artifacts")))
        added_tokens += _int_or_zero(request.get("added_tokens"))

    capsule_tokens = _int_or_none(context_delivery.get("capsule_tokens"))
    if unavailable_count > 0 and granted_count == 0:
        return "insufficient_evidence", "Requested evidence was unavailable."
    if denied_count > 0 and granted_count == 0 and unavailable_count == 0:
        return "mis_scoped", "Context requests targeted out-of-scope evidence."
    if granted_count > 0:
        return "under_provisioned", "Required evidence arrived only after a scoped request."
    if (
        first_pass_success is True
        and rework_required is False
        and review_status in {None, "approved"}
        and verification_status in {None, "passed", "not_run"}
        and capsule_tokens is not None
        and added_tokens == 0
        and capsule_tokens > 4000
    ):
        return "over_provisioned", "Large initial capsule succeeded without follow-up requests."
    if (
        first_pass_success is True
        and rework_required is False
        and review_status in {None, "approved"}
        and verification_status in {None, "passed", "not_run"}
    ):
        return "well_provisioned", "Initial capsule was sufficient for the observed outcome."
    return "insufficient_evidence", "Observable signals are not yet strong enough."


def load_ledger_from_mapping(data: dict[str, Any]):
    from ..protocol.harness import Ledger

    return Ledger.from_dict(data)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ProtocolError("Metrics document must be an object")
    return data


def _string_or_unknown(value: Any, default: str = "unknown") -> str:
    return value if isinstance(value, str) and value else default


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list_or_empty(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None
