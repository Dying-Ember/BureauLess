from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import yaml

from ..core import ProtocolError
from ..runtime.gatekeeper import evaluate_gatekeeper
from .harness import Ledger, Workflow
from .mutations import materialize_current_workflow


DEFAULT_FORBIDDEN_ACTIONS = [
    "expand_assignment_scope",
    "create_new_agents",
    "update_canonical_ledger",
    "choose_larger_model_without_approval",
]


@dataclass(frozen=True)
class AssignmentPacket:
    assignment_id: str
    workflow_id: str
    node_id: str
    role: str
    goal: str
    visible_context: dict[str, Any]
    artifact_refs: list[dict[str, Any]]
    allowed_tools: list[str]
    forbidden_actions: list[str]
    expected_events: list[str]
    outcome_metrics_policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "role": self.role,
            "goal": self.goal,
            "visible_context": self.visible_context,
            "artifact_refs": self.artifact_refs,
            "allowed_tools": self.allowed_tools,
            "forbidden_actions": self.forbidden_actions,
            "expected_events": self.expected_events,
            "outcome_metrics_policy": self.outcome_metrics_policy,
        }


def export_assignment(
    workflow: Workflow,
    ledger: Ledger,
    node_id: str,
    assignment_id: str | None = None,
    force: bool = False,
) -> AssignmentPacket:
    current_workflow = materialize_current_workflow(workflow, ledger)
    node = current_workflow.nodes.get(node_id)
    if node is None:
        raise ProtocolError(f"Unknown workflow node id: {node_id}")

    if not force:
        gatekeeper = evaluate_gatekeeper(workflow, ledger)
        decision = gatekeeper.decisions[node_id]
        if decision.state != "runnable":
            reasons = ", ".join(reason.message for reason in decision.blocked_reasons)
            raise ProtocolError(f"Node {node_id} is not runnable: {reasons}")

    return AssignmentPacket(
        assignment_id=assignment_id or f"assign-{uuid4()}",
        workflow_id=current_workflow.workflow_id,
        node_id=node.id,
        role=node.role,
        goal=f"Execute workflow node {node.id} as role {node.role}.",
        visible_context={
            "mission_id": current_workflow.mission_id,
            "mission_goal": ledger.current_goal,
            "workflow_reason": current_workflow.reason,
        },
        artifact_refs=[],
        allowed_tools=[],
        forbidden_actions=DEFAULT_FORBIDDEN_ACTIONS,
        expected_events=node.emits,
        outcome_metrics_policy={
            "wall_time": "required",
            "final_status": "required",
            "changed_files": "required",
            "token_usage": "optional",
            "cost_usage": "optional",
        },
    )


def render_assignment_prompt(assignment: AssignmentPacket) -> str:
    return "\n".join(
        [
            f"# Assignment {assignment.assignment_id}",
            "",
            f"Workflow: {assignment.workflow_id}",
            f"Node: {assignment.node_id}",
            f"Role: {assignment.role}",
            "",
            "## Goal",
            assignment.goal,
            "",
            "## Expected Events",
            _lines(assignment.expected_events),
            "",
            "## Forbidden Actions",
            _lines(assignment.forbidden_actions),
            "",
            "## Visible Context",
            yaml.safe_dump(assignment.visible_context, sort_keys=False).strip(),
        ]
    )


def load_assignment(data: dict[str, Any]) -> AssignmentPacket:
    return AssignmentPacket(
        assignment_id=_as_string(data, "assignment_id"),
        workflow_id=_as_string(data, "workflow_id"),
        node_id=_as_string(data, "node_id"),
        role=_as_string(data, "role"),
        goal=_as_string(data, "goal"),
        visible_context=_as_mapping(data, "visible_context"),
        artifact_refs=_as_mapping_list(data, "artifact_refs", default=[]),
        allowed_tools=_as_string_list(data, "allowed_tools", default=[]),
        forbidden_actions=_as_string_list(data, "forbidden_actions"),
        expected_events=_as_string_list(data, "expected_events"),
        outcome_metrics_policy=_as_mapping(data, "outcome_metrics_policy", default={}),
    )


def _lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"Assignment field {key!r} must be a string")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Assignment field {key!r} must be an object")
    return value


def _as_string_list(
    data: dict[str, Any],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProtocolError(f"Assignment field {key!r} must be a list of strings")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Assignment field {key!r} must be a list of objects")
    return value
