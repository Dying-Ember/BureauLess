from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..errors import ProtocolError
from .assignments import AssignmentPacket


VALID_NODE_OUTCOME_STATUSES = {
    "completed",
    "failed",
    "timed_out",
    "cancelled",
    "partial",
    "superseded",
    "stale",
    "needs_review",
}

VALID_NODE_OUTCOME_DISPOSITIONS = {"accepted", "partially_accepted", "rejected"}


@dataclass(frozen=True)
class NodeOutcome:
    outcome_id: str
    assignment_id: str
    session_id: str
    workflow_id: str
    node_id: str
    role: str
    agent_id: str
    status: str
    effective_model: str | None
    effective_provider: str | None
    pre_state_ref: str | None
    post_state_ref: str | None
    observed_delta: dict[str, Any]
    verification: dict[str, Any]
    native_log_refs: list[dict[str, Any]]
    diff_refs: list[dict[str, Any]]
    outcome_metrics: dict[str, Any]
    extraction: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "outcome_id": self.outcome_id,
            "assignment_id": self.assignment_id,
            "session_id": self.session_id,
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "role": self.role,
            "agent_id": self.agent_id,
            "status": self.status,
            "pre_state_ref": self.pre_state_ref,
            "post_state_ref": self.post_state_ref,
            "observed_delta": self.observed_delta,
            "verification": self.verification,
            "native_log_refs": self.native_log_refs,
            "diff_refs": self.diff_refs,
            "outcome_metrics": self.outcome_metrics,
            "extraction": self.extraction,
        }
        if self.effective_model is not None:
            payload["effective_model"] = self.effective_model
        if self.effective_provider is not None:
            payload["effective_provider"] = self.effective_provider
        return payload


def load_node_outcome(data: dict[str, Any]) -> NodeOutcome:
    status = _as_string(data, "status")
    if status not in VALID_NODE_OUTCOME_STATUSES:
        raise ProtocolError(
            f"Node outcome status must be one of: {', '.join(sorted(VALID_NODE_OUTCOME_STATUSES))}"
        )
    return NodeOutcome(
        outcome_id=_as_string(data, "outcome_id"),
        assignment_id=_as_string(data, "assignment_id"),
        session_id=_as_string(data, "session_id"),
        workflow_id=_as_string(data, "workflow_id"),
        node_id=_as_string(data, "node_id"),
        role=_as_string(data, "role"),
        agent_id=_as_string(data, "agent_id"),
        status=status,
        effective_model=_as_optional_string(data.get("effective_model")),
        effective_provider=_as_optional_string(data.get("effective_provider")),
        pre_state_ref=_as_optional_string(data.get("pre_state_ref")),
        post_state_ref=_as_optional_string(data.get("post_state_ref")),
        observed_delta=_as_mapping(data, "observed_delta", default={}),
        verification=_as_mapping(data, "verification", default={}),
        native_log_refs=_as_mapping_list(data, "native_log_refs", default=[]),
        diff_refs=_as_mapping_list(data, "diff_refs", default=[]),
        outcome_metrics=_as_mapping(data, "outcome_metrics", default={}),
        extraction=_as_mapping(data, "extraction", default={}),
    )


def node_outcome_from_session(
    assignment: AssignmentPacket,
    session_record: dict[str, Any],
    *,
    outcome_id: str | None = None,
) -> NodeOutcome:
    record_status = _as_string(session_record, "status")
    status = _map_session_status(record_status)
    result = session_record.get("result_proposal")
    effective_model = None
    effective_provider = None
    verification = {"status": "not_run"}
    if isinstance(result, dict):
        effective_model = _as_optional_string(result.get("effective_model"))
        effective_provider = _as_optional_string(result.get("effective_provider"))
        verification = _as_mapping(result, "verification", default={"status": "not_run"})

    outcome_metrics = _as_mapping(session_record, "outcome_metrics", default={})
    diff_refs = _as_mapping_list(session_record, "diff_refs", default=[])
    observed_delta = {
        "changed_files_count": outcome_metrics.get("changed_files_count", 0),
        "patch_bytes": outcome_metrics.get("patch_bytes", 0),
        "diff_refs": diff_refs,
    }
    workspace = _as_mapping(session_record, "workspace", default={})
    return NodeOutcome(
        outcome_id=outcome_id or f"outcome-{_as_string(session_record, 'session_id')}",
        assignment_id=assignment.assignment_id,
        session_id=_as_string(session_record, "session_id"),
        workflow_id=assignment.workflow_id,
        node_id=assignment.node_id,
        role=assignment.role,
        agent_id=_as_string(session_record, "agent_id"),
        status=status,
        effective_model=effective_model,
        effective_provider=effective_provider,
        pre_state_ref=_as_optional_string(workspace.get("pre_state_ref")),
        post_state_ref=_as_optional_string(workspace.get("post_state_ref")),
        observed_delta=observed_delta,
        verification=verification,
        native_log_refs=[],
        diff_refs=diff_refs,
        outcome_metrics=outcome_metrics,
        extraction=_as_mapping(session_record, "extraction", default={}),
    )


def build_node_outcome_decision_event(
    outcome: NodeOutcome,
    *,
    event_id: str,
    mission_id: str,
    workflow_id: str,
    actor: str,
    disposition: str,
    accepted_event_types: list[str] | None = None,
    validation_rule: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if disposition not in VALID_NODE_OUTCOME_DISPOSITIONS:
        raise ProtocolError(
            "Node outcome disposition must be one of: accepted, partially_accepted, rejected"
        )
    payload = {
        "event_id": event_id,
        "event_type": "node_outcome_decided",
        "mission_id": mission_id,
        "workflow_id": workflow_id,
        "assignment_id": outcome.assignment_id,
        "node_id": outcome.node_id,
        "role": outcome.role,
        "agent_id": outcome.agent_id,
        "session_id": outcome.session_id,
        "source_outcome_id": outcome.outcome_id,
        "outcome_status": outcome.status,
        "actor": actor,
        "disposition": disposition,
        "accepted_event_types": accepted_event_types or [],
    }
    if outcome.pre_state_ref is not None:
        payload["pre_state_ref"] = outcome.pre_state_ref
    if outcome.post_state_ref is not None:
        payload["post_state_ref"] = outcome.post_state_ref
    if validation_rule is not None:
        payload["validation_rule"] = validation_rule
    if created_at is not None:
        payload["created_at"] = created_at
    return payload


def reconcile_node_outcome_state(
    outcome: NodeOutcome,
    accepted_workspace_ref: str | None,
) -> NodeOutcome:
    if (
        accepted_workspace_ref is None
        or outcome.pre_state_ref is None
        or outcome.pre_state_ref == accepted_workspace_ref
    ):
        return outcome
    if outcome.observed_delta.get("changed_files_count", 0):
        return replace(outcome, status="needs_review")
    return replace(outcome, status="stale")


def _map_session_status(status: str) -> str:
    mapping = {
        "completed": "completed",
        "failed": "failed",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
        "superseded": "superseded",
    }
    try:
        return mapping[status]
    except KeyError as exc:
        raise ProtocolError(f"Cannot derive node outcome from session status: {status}") from exc


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"Node outcome field {key!r} must be a string")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Node outcome field {key!r} must be an object")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Node outcome field {key!r} must be a list of objects")
    return value


def _as_optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
