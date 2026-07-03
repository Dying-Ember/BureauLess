from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ProtocolError
from .assignments import AssignmentPacket, load_assignment
from .harness import Mission, Workflow
from .routing import RoutingDecision, load_routing_decision, validate_routing_decision


VALID_TURN_REPORT_STATUSES = {"in_progress", "blocked", "completed"}
VALID_TURN_REPORT_TELEMETRY_MODES = {"observed", "degraded"}
VALID_TURN_REPORT_POLICY_STATUSES = {"compliant", "violated", "degraded"}


@dataclass(frozen=True)
class TurnReport:
    report_id: str
    assignment_id: str
    agent_id: str
    status: str
    tool_calls_since_last_report: int
    summary: str
    new_findings: list[dict[str, Any]]
    artifact_refs: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    suggested_ledger_updates: list[dict[str, Any]]
    token_usage: dict[str, int]
    observed_at: str | None = None
    telemetry_mode: str | None = None
    source_event_ids: list[str] | None = None
    policy_compliance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "report_id": self.report_id,
            "assignment_id": self.assignment_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "tool_calls_since_last_report": self.tool_calls_since_last_report,
            "summary": self.summary,
            "new_findings": self.new_findings,
            "artifact_refs": self.artifact_refs,
            "blockers": self.blockers,
            "suggested_ledger_updates": self.suggested_ledger_updates,
            "token_usage": self.token_usage,
        }
        if self.observed_at is not None:
            payload["observed_at"] = self.observed_at
        if self.telemetry_mode is not None:
            payload["telemetry_mode"] = self.telemetry_mode
        if self.source_event_ids is not None:
            payload["source_event_ids"] = self.source_event_ids
        if self.policy_compliance is not None:
            payload["policy_compliance"] = self.policy_compliance
        return payload


@dataclass(frozen=True)
class DispatchPacket:
    packet_id: str
    mission_id: str
    workflow_id: str
    routing_decision: RoutingDecision
    assignment: AssignmentPacket
    review_constraints: dict[str, Any]
    turn_report_policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "mission_id": self.mission_id,
            "workflow_id": self.workflow_id,
            "routing_decision": self.routing_decision.to_dict(),
            "assignment": self.assignment.to_dict(),
            "review_constraints": self.review_constraints,
            "turn_report_policy": self.turn_report_policy,
        }


def load_turn_report(data: dict[str, Any]) -> TurnReport:
    status = _as_string(data, "status")
    if status not in VALID_TURN_REPORT_STATUSES:
        raise ProtocolError(
            "Turn report status must be one of: blocked, completed, in_progress"
        )
    tool_calls_since_last_report = _as_int(data, "tool_calls_since_last_report")
    if tool_calls_since_last_report < 0:
        raise ProtocolError("Turn report tool_calls_since_last_report must be >= 0")
    telemetry_mode = _as_optional_string(data.get("telemetry_mode"))
    if telemetry_mode is not None and telemetry_mode not in VALID_TURN_REPORT_TELEMETRY_MODES:
        raise ProtocolError("Turn report telemetry_mode must be observed or degraded")
    policy_compliance = (
        _as_mapping(data, "policy_compliance")
        if data.get("policy_compliance") is not None
        else None
    )
    if policy_compliance is not None:
        policy_status = _as_string(policy_compliance, "status")
        if policy_status not in VALID_TURN_REPORT_POLICY_STATUSES:
            raise ProtocolError("Turn report policy_compliance.status is invalid")
        _as_string_list(policy_compliance, "reasons", default=[])
    return TurnReport(
        report_id=_as_string(data, "report_id"),
        assignment_id=_as_string(data, "assignment_id"),
        agent_id=_as_string(data, "agent_id"),
        status=status,
        tool_calls_since_last_report=tool_calls_since_last_report,
        summary=_as_string(data, "summary"),
        new_findings=_as_mapping_list(data, "new_findings", default=[]),
        artifact_refs=_as_mapping_list(data, "artifact_refs", default=[]),
        blockers=_as_mapping_list(data, "blockers", default=[]),
        suggested_ledger_updates=_as_mapping_list(
            data,
            "suggested_ledger_updates",
            default=[],
        ),
        token_usage=_as_token_usage(data.get("token_usage", {})),
        observed_at=_as_optional_string(data.get("observed_at")),
        telemetry_mode=telemetry_mode,
        source_event_ids=_as_optional_string_list(data.get("source_event_ids")),
        policy_compliance=policy_compliance,
    )


def load_dispatch_packet(data: dict[str, Any]) -> DispatchPacket:
    return DispatchPacket(
        packet_id=_as_string(data, "packet_id"),
        mission_id=_as_string(data, "mission_id"),
        workflow_id=_as_string(data, "workflow_id"),
        routing_decision=load_routing_decision(_as_mapping(data, "routing_decision")),
        assignment=load_assignment(_as_mapping(data, "assignment")),
        review_constraints=_as_mapping(data, "review_constraints", default={}),
        turn_report_policy=_as_mapping(data, "turn_report_policy", default={}),
    )


def compile_dispatch_packet(
    mission: Mission,
    workflow: Workflow,
    routing_decision: RoutingDecision,
    assignment: AssignmentPacket,
    *,
    packet_id: str,
    review_constraints: dict[str, Any] | None = None,
    turn_report_policy: dict[str, Any] | None = None,
) -> DispatchPacket:
    validate_routing_decision(mission, routing_decision, workflow=workflow)
    if assignment.workflow_id != workflow.workflow_id:
        raise ProtocolError("Dispatch assignment workflow_id does not match workflow")
    if workflow.mission_id != mission.mission_id:
        raise ProtocolError("Dispatch workflow mission_id does not match mission")
    node = workflow.nodes.get(assignment.node_id)
    if node is None:
        raise ProtocolError("Dispatch assignment node_id does not exist in workflow")
    if assignment.role != node.role:
        raise ProtocolError("Dispatch assignment role does not match workflow node role")
    expected_events = set(assignment.expected_events)
    emitted_by_node = set(node.emits)
    if not expected_events <= emitted_by_node:
        raise ProtocolError("Dispatch assignment expected_events exceed workflow node emits")
    if "update_canonical_ledger" not in assignment.forbidden_actions:
        raise ProtocolError(
            "Dispatch assignment must forbid canonical ledger updates by the worker"
        )
    resolved_turn_report_policy = turn_report_policy or {
        "after_each_tool_call": True,
        "max_report_tokens": 600,
    }
    _validate_turn_report_policy(resolved_turn_report_policy)
    resolved_review_constraints = review_constraints or _default_review_constraints(
        workflow,
        assignment,
    )
    _validate_review_constraints(workflow, assignment, resolved_review_constraints)
    return DispatchPacket(
        packet_id=packet_id,
        mission_id=mission.mission_id,
        workflow_id=workflow.workflow_id,
        routing_decision=routing_decision,
        assignment=assignment,
        review_constraints=resolved_review_constraints,
        turn_report_policy=resolved_turn_report_policy,
    )


def validate_dispatch_packet(
    mission: Mission,
    workflow: Workflow,
    packet: DispatchPacket,
) -> None:
    if packet.mission_id != mission.mission_id:
        raise ProtocolError("Dispatch packet mission_id does not match mission")
    if packet.workflow_id != workflow.workflow_id:
        raise ProtocolError("Dispatch packet workflow_id does not match workflow")
    compiled = compile_dispatch_packet(
        mission,
        workflow,
        packet.routing_decision,
        packet.assignment,
        packet_id=packet.packet_id,
        review_constraints=packet.review_constraints,
        turn_report_policy=packet.turn_report_policy,
    )
    if compiled.to_dict() != packet.to_dict():
        raise ProtocolError("Dispatch packet is not in canonical compiled form")


def _default_review_constraints(
    workflow: Workflow,
    assignment: AssignmentPacket,
) -> dict[str, Any]:
    required_gate_ids = [gate.id for gate in workflow.gates if gate.node_id == assignment.node_id]
    requires_review_decision = assignment.node_id == "commit" or any(
        event == "commit_created" for event in assignment.expected_events
    )
    return {
        "required_gate_ids": required_gate_ids,
        "requires_review_decision": requires_review_decision,
        "forbid_scope_expansion": True,
        "forbid_new_agents": True,
    }


def _validate_review_constraints(
    workflow: Workflow,
    assignment: AssignmentPacket,
    constraints: dict[str, Any],
) -> None:
    required_gate_ids = constraints.get("required_gate_ids", [])
    if not isinstance(required_gate_ids, list) or not all(
        isinstance(item, str) and item for item in required_gate_ids
    ):
        raise ProtocolError("Dispatch review_constraints.required_gate_ids must be a list of strings")
    known_gate_ids = {gate.id for gate in workflow.gates}
    unknown_gate_ids = sorted(set(required_gate_ids) - known_gate_ids)
    if unknown_gate_ids:
        raise ProtocolError(
            f"Dispatch review_constraints references unknown gates: {', '.join(unknown_gate_ids)}"
        )
    requires_review_decision = constraints.get("requires_review_decision")
    if not isinstance(requires_review_decision, bool):
        raise ProtocolError(
            "Dispatch review_constraints.requires_review_decision must be boolean"
        )
    if assignment.node_id == "commit" and not requires_review_decision:
        raise ProtocolError(
            "Commit-like dispatch packets must require an explicit review decision"
        )
    for field in ("forbid_scope_expansion", "forbid_new_agents"):
        if not isinstance(constraints.get(field), bool):
            raise ProtocolError(f"Dispatch review_constraints.{field} must be boolean")


def _validate_turn_report_policy(policy: dict[str, Any]) -> None:
    if not isinstance(policy.get("after_each_tool_call"), bool):
        raise ProtocolError("Dispatch turn_report_policy.after_each_tool_call must be boolean")
    max_report_tokens = policy.get("max_report_tokens")
    if not isinstance(max_report_tokens, int) or max_report_tokens <= 0:
        raise ProtocolError("Dispatch turn_report_policy.max_report_tokens must be > 0")


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Dispatch field {key!r} must be a non-empty string")
    return value


def _as_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ProtocolError(f"Dispatch field {key!r} must be an integer")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Dispatch field {key!r} must be an object")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Dispatch field {key!r} must be a list of objects")
    return value


def _as_string_list(
    data: dict[str, Any],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProtocolError(f"Dispatch field {key!r} must be a list of strings")
    return value


def _as_token_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ProtocolError("Turn report token_usage must be an object")
    normalized: dict[str, int] = {}
    for field in ("input_tokens", "output_tokens"):
        field_value = value.get(field, 0)
        if not isinstance(field_value, int) or field_value < 0:
            raise ProtocolError(f"Turn report token_usage.{field} must be a non-negative integer")
        normalized[field] = field_value
    return normalized


def _as_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProtocolError("Optional turn report fields must be non-empty strings")
    return value


def _as_optional_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProtocolError("Turn report source_event_ids must be a list of strings")
    return value
