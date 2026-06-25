from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .assignments import AssignmentPacket
from ..core import ProtocolError
from .harness import Ledger, Workflow
from .ledger import append_ledger_event


@dataclass(frozen=True)
class ResultProposal:
    result_id: str
    assignment_id: str
    agent_id: str
    status: str
    effective_model: str | None
    effective_provider: str | None
    emitted_events: list[str]
    artifacts: list[dict[str, Any]]
    outcome_metrics: dict[str, Any]
    verification: dict[str, Any]
    native_log_refs: list[dict[str, Any]]
    review_status: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "result_id": self.result_id,
            "assignment_id": self.assignment_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "emitted_events": self.emitted_events,
            "artifacts": self.artifacts,
            "outcome_metrics": self.outcome_metrics,
            "verification": self.verification,
            "native_log_refs": self.native_log_refs,
        }
        if self.effective_model is not None:
            payload["effective_model"] = self.effective_model
        if self.effective_provider is not None:
            payload["effective_provider"] = self.effective_provider
        if self.review_status is not None:
            payload["review_status"] = self.review_status
        return payload


def load_result_proposal(data: dict[str, Any]) -> ResultProposal:
    return ResultProposal(
        result_id=_as_string(data, "result_id"),
        assignment_id=_as_string(data, "assignment_id"),
        agent_id=_as_string(data, "agent_id"),
        status=_as_string(data, "status"),
        effective_model=_as_optional_string(data.get("effective_model")),
        effective_provider=_as_optional_string(data.get("effective_provider")),
        emitted_events=_as_string_list(data, "emitted_events", default=[]),
        artifacts=_as_mapping_list(data, "artifacts", default=[]),
        outcome_metrics=_as_mapping(data, "outcome_metrics", default={}),
        verification=_as_mapping(data, "verification", default={}),
        native_log_refs=_as_mapping_list(data, "native_log_refs", default=[]),
        review_status=_as_optional_string(data.get("review_status")),
    )


def import_result_proposal(
    workflow: Workflow,
    ledger: Ledger,
    assignment: AssignmentPacket,
    result: ResultProposal,
) -> Ledger:
    validate_result_proposal(workflow, assignment, result)
    result_event = {
        "event_id": f"event-{result.result_id}",
        "event_type": "result_submitted",
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "assignment_id": assignment.assignment_id,
        "node_id": assignment.node_id,
        "role": assignment.role,
        "agent_id": result.agent_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": result.to_dict(),
    }
    updated = append_ledger_event(ledger, result_event, workflow)
    for index, event_type in enumerate(result.emitted_events, start=1):
        updated = append_ledger_event(
            updated,
            {
                "event_id": f"event-{result.result_id}-emit-{index}",
                "event_type": event_type,
                "mission_id": workflow.mission_id,
                "workflow_id": workflow.workflow_id,
                "assignment_id": assignment.assignment_id,
                "result_id": result.result_id,
                "node_id": assignment.node_id,
                "role": assignment.role,
                "agent_id": result.agent_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_event_id": result_event["event_id"],
            },
            workflow,
        )
    return updated


def validate_result_proposal(
    workflow: Workflow,
    assignment: AssignmentPacket,
    result: ResultProposal,
) -> None:
    if assignment.workflow_id != workflow.workflow_id:
        raise ProtocolError("Assignment workflow_id does not match workflow")
    if result.assignment_id != assignment.assignment_id:
        raise ProtocolError("Result assignment_id does not match assignment")
    if assignment.node_id not in workflow.nodes:
        raise ProtocolError(f"Assignment references unknown node: {assignment.node_id}")

    node = workflow.nodes[assignment.node_id]
    if assignment.role != node.role:
        raise ProtocolError("Assignment role does not match workflow node role")

    allowed_events = set(node.emits)
    unauthorized = sorted(set(result.emitted_events) - allowed_events)
    if unauthorized:
        raise ProtocolError(
            f"Result emitted events not allowed for assignment: {', '.join(unauthorized)}"
        )

    _validate_outcome_metrics_policy(assignment, result)

    for artifact in result.artifacts:
        for field in ("artifact_id", "path", "sha256", "created_by", "source_event"):
            if not artifact.get(field):
                raise ProtocolError(f"Result artifact is missing required field: {field}")
        if artifact.get("mutable") is not False:
            raise ProtocolError("Result artifact must have mutable: false")


def _validate_outcome_metrics_policy(
    assignment: AssignmentPacket,
    result: ResultProposal,
) -> None:
    policy = assignment.outcome_metrics_policy
    if policy.get("final_status") == "required" and not result.status:
        raise ProtocolError("Result status is required by outcome_metrics_policy")
    if policy.get("wall_time") == "required" and "wall_time_ms" not in result.outcome_metrics:
        raise ProtocolError("Result outcome_metrics.wall_time_ms is required")
    if (
        policy.get("changed_files") == "required"
        and "changed_files_count" not in result.outcome_metrics
    ):
        raise ProtocolError("Result outcome_metrics.changed_files_count is required")
    if policy.get("token_usage") == "required" and "total_tokens" not in result.outcome_metrics:
        raise ProtocolError("Result outcome_metrics.total_tokens is required")
    if policy.get("cost_usage") == "required" and "cost_usd" not in result.outcome_metrics:
        raise ProtocolError("Result outcome_metrics.cost_usd is required")


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"Result field {key!r} must be a string")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Result field {key!r} must be an object")
    return value


def _as_string_list(
    data: dict[str, Any],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProtocolError(f"Result field {key!r} must be a list of strings")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Result field {key!r} must be a list of objects")
    return value


def _as_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError("Optional result field must be a string when present")
    return value
