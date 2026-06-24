from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..core import ProtocolError
from ..protocol.budget import estimate_cost_from_snapshot, load_price_snapshot


@dataclass(frozen=True)
class MetricsEntry:
    assignment_id: str
    status: str
    agent_id: str
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "status": self.status,
            "agent_id": self.agent_id,
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
        }


def summarize_metrics(path: Path, price_snapshot_path: Path | None = None) -> dict[str, Any]:
    entries = _load_entries(path)
    if price_snapshot_path is not None:
        snapshot = load_price_snapshot(price_snapshot_path)
        entries = [_apply_price_snapshot(entry, snapshot) for entry in entries]
    return {
        "entries": [entry.to_dict() for entry in entries],
        "summary": _group_entries(entries),
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


def _entries_from_mapping(data: dict[str, Any]) -> list[MetricsEntry]:
    if "event_log" in data:
        return _entries_from_ledger_mapping(data)
    if "session_id" in data:
        return [_entry_from_session_mapping(data)]
    raise ProtocolError("Metrics summarize expects a ledger YAML or session YAML")


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
        entries.append(
            MetricsEntry(
                assignment_id=_string_or_unknown(result.get("assignment_id")),
                status=_string_or_unknown(result.get("status")),
                agent_id=_string_or_unknown(result.get("agent_id")),
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

    return MetricsEntry(
        assignment_id=_string_or_unknown(data.get("assignment_id")),
        status=_string_or_unknown(data.get("status")),
        agent_id=_string_or_unknown(data.get("agent_id")),
        model=_string_or_unknown(data.get("effective_model")),
        provider=_string_or_unknown(data.get("effective_provider")),
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
    )


def _group_entries(entries: list[MetricsEntry]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (entry.agent_id, entry.model, entry.provider, entry.workflow_mode)
        bucket = grouped.setdefault(
            key,
            {
                "agent_id": entry.agent_id,
                "model": entry.model,
                "provider": entry.provider,
                "workflow_mode": entry.workflow_mode,
                "count": 0,
                "completed": 0,
                "wall_time_ms_total": 0,
                "total_tokens_total": 0,
                "cost_usd_total": 0.0,
                "missing_usage_count": 0,
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
    return [grouped[key] for key in sorted(grouped)]


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
    )


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


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
