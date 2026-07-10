from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import yaml

from ..errors import ProtocolError
from ..runtime.gatekeeper import evaluate_gatekeeper
from .harness import Ledger, Mission, Workflow
from .ledger import rebuild_ledger_projection
from .mutations import materialize_current_workflow, workflow_version_identity


DEFAULT_FORBIDDEN_ACTIONS = [
    "expand_assignment_scope",
    "create_new_agents",
    "update_canonical_ledger",
    "choose_larger_model_without_approval",
]


@dataclass(frozen=True)
class ContextCapsule:
    context_capsule_id: str
    policy_version: str
    mission_id: str
    workflow_id: str
    assignment_id: str
    node_id: str
    role: str
    workspace_ref: str | None
    dependency_node_ids: list[str]
    required_gates: list[dict[str, Any]]
    role_permissions: dict[str, list[str]]
    accepted_facts: list[dict[str, Any]]
    accepted_decisions: list[dict[str, Any]]
    active_risks: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    artifact_refs: list[dict[str, Any]]
    source_event_ids: list[str]
    mission_constraints: dict[str, Any]
    excluded: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "context_capsule_id": self.context_capsule_id,
            "policy_version": self.policy_version,
            "mission_id": self.mission_id,
            "workflow_id": self.workflow_id,
            "assignment_id": self.assignment_id,
            "node_id": self.node_id,
            "role": self.role,
            "dependency_node_ids": self.dependency_node_ids,
            "required_gates": self.required_gates,
            "role_permissions": self.role_permissions,
            "accepted_facts": self.accepted_facts,
            "accepted_decisions": self.accepted_decisions,
            "active_risks": self.active_risks,
            "open_questions": self.open_questions,
            "artifact_refs": self.artifact_refs,
            "source_event_ids": self.source_event_ids,
            "mission_constraints": self.mission_constraints,
            "excluded": self.excluded,
        }
        if self.workspace_ref is not None:
            payload["workspace_ref"] = self.workspace_ref
        return payload


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
    mission: Mission | None = None,
) -> AssignmentPacket:
    resolved_assignment_id = assignment_id or f"assign-{uuid4()}"
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

    capsule = compile_context_capsule(
        workflow,
        ledger,
        node_id,
        assignment_id=resolved_assignment_id,
        mission=mission,
    )
    return AssignmentPacket(
        assignment_id=resolved_assignment_id,
        workflow_id=current_workflow.workflow_id,
        node_id=node.id,
        role=node.role,
        goal=f"Execute workflow node {node.id} as role {node.role}.",
        visible_context={
            "mission_id": current_workflow.mission_id,
            "mission_goal": ledger.current_goal,
            "workflow_reason": current_workflow.reason,
            "workflow_version_id": workflow_version_id(current_workflow, ledger),
            "workflow_structure": _workflow_structure(
                current_workflow,
                ledger,
                assignment_id=resolved_assignment_id,
                node_id=node.id,
            ),
            "context_capsule": capsule.to_dict(),
        },
        artifact_refs=capsule.artifact_refs,
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
            "",
            "## Artifact Refs",
            yaml.safe_dump(assignment.artifact_refs, sort_keys=False).strip()
            if assignment.artifact_refs
            else "- None",
            "",
            "## Structural Escape Hatch",
            "If the assignment is blocked by workflow structure, return status blocked,",
            "verification.status workflow_structure, and optionally one control_intents item:",
            "intent_type: workflow_mutation",
            "reason: discovered_missing_dependency | node_needs_split | stale_result | other",
            "rationale: <why the current structure blocks correct execution>",
            "proposed_changes: {add_nodes: [], add_edges: [], remove_edges: [], supersede_assignments: []}",
            "evidence_refs: [<artifact-id>]",
            "Omit control_intents when no structural change is needed.",
            "Do not choose proposal IDs, provenance, workflow versions, approval policy, or edit the ledger.",
        ]
    )


def workflow_version_id(workflow: Workflow, ledger: Ledger) -> str:
    sequence = sum(
        event.get("event_type") == "workflow_mutation_accepted"
        and event.get("workflow_id") == workflow.workflow_id
        for event in ledger.event_log
    )
    return workflow_version_identity(workflow, sequence)


def _workflow_structure(
    workflow: Workflow,
    ledger: Ledger,
    *,
    assignment_id: str,
    node_id: str,
) -> dict[str, Any]:
    assignments = {
        event["assignment_id"]: {
            "assignment_id": event["assignment_id"],
            "node_id": event.get("node_id"),
        }
        for event in ledger.event_log
        if event.get("event_type") == "assignment_created"
        and event.get("workflow_id") == workflow.workflow_id
        and isinstance(event.get("assignment_id"), str)
    }
    assignments[assignment_id] = {
        "assignment_id": assignment_id,
        "node_id": node_id,
    }
    superseded = {
        event.get("assignment_id")
        for event in ledger.event_log
        if event.get("event_type") == "assignment_superseded"
        and event.get("workflow_id") == workflow.workflow_id
    }
    return {
        "roles": sorted(workflow.roles),
        "events": sorted(workflow.events),
        "nodes": [
            {
                "id": node.id,
                "role": node.role,
                "waits_for": _event_branches(node.waits_for_all, node.waits_for_any),
                "emits": node.emits,
            }
            for node in workflow.nodes.values()
        ],
        "gates": [
            {
                "id": gate.id,
                "node_id": gate.node_id,
                "requires": _event_branches(gate.requires_all, gate.requires_any),
            }
            for gate in workflow.gates
        ],
        "terminal_events": workflow.terminal_events,
        "active_assignments": [
            assignments[key]
            for key in sorted(assignments)
            if key not in superseded
        ],
    }


def _event_branches(all_of: list[str], any_of: list[str]) -> list[str] | dict[str, list[str]]:
    if any_of:
        return {"all_of": all_of, "any_of": any_of}
    return all_of


def compile_context_capsule(
    workflow: Workflow,
    ledger: Ledger,
    node_id: str,
    *,
    assignment_id: str,
    policy_version: str = "context-v1",
    mission: Mission | None = None,
) -> ContextCapsule:
    ledger = rebuild_ledger_projection(ledger)
    workflow = materialize_current_workflow(workflow, ledger)
    node = workflow.nodes.get(node_id)
    if node is None:
        raise ProtocolError(f"Unknown workflow node id: {node_id}")

    scoped_node_ids = _scoped_node_ids(workflow, node_id)
    scoped_node_id_set = set(scoped_node_ids)
    events_by_id = {
        event_id: event
        for event in ledger.event_log
        if isinstance((event_id := event.get("event_id")), str) and event_id
    }
    source_event_ids = sorted(
        event_id
        for event_id, event in events_by_id.items()
        if isinstance(event.get("node_id"), str) and event["node_id"] in scoped_node_id_set
    )
    accepted_facts = sorted(
        (
            finding
            for finding in ledger.public_findings
            if _event_node_id(events_by_id, finding.get("source_event")) in scoped_node_id_set
        ),
        key=_finding_sort_key,
    )
    accepted_decisions = sorted(
        (
            decision
            for decision in ledger.decisions
            if _decision_node_id(events_by_id, decision) in scoped_node_id_set
        ),
        key=_decision_sort_key,
    )
    active_risks = sorted(
        (
            risk
            for risk in ledger.risks
            if _scoped_record(risk, scoped_node_id_set)
            and risk.get("status") != "resolved"
        ),
        key=lambda item: _stable_record_key(item, "risk_id"),
    )
    open_questions = sorted(
        (
            question
            for question in ledger.open_questions
            if _scoped_record(question, scoped_node_id_set)
            and question.get("status") != "resolved"
        ),
        key=lambda item: _stable_record_key(item, "question_id"),
    )
    artifact_refs = _artifact_refs_for_scope(
        ledger,
        events_by_id,
        scoped_node_id_set,
    )
    role = workflow.roles[node.role]
    return ContextCapsule(
        context_capsule_id=f"context-{assignment_id}",
        policy_version=policy_version,
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        assignment_id=assignment_id,
        node_id=node_id,
        role=node.role,
        workspace_ref=_optional_string(ledger.projection.get("accepted_workspace_ref")),
        dependency_node_ids=scoped_node_ids,
        required_gates=[
            {
                "gate_id": gate.id,
                "requires_all": sorted(gate.requires_all),
                "requires_any": sorted(gate.requires_any),
            }
            for gate in workflow.gates
            if gate.node_id == node_id
        ],
        role_permissions={
            "can_emit": sorted(role.can_emit),
            "can_consume": sorted(role.can_consume),
        },
        accepted_facts=accepted_facts,
        accepted_decisions=accepted_decisions,
        active_risks=active_risks,
        open_questions=open_questions,
        artifact_refs=artifact_refs,
        source_event_ids=source_event_ids,
        mission_constraints=_mission_constraints(workflow, ledger, mission),
        excluded={
            "raw_tool_logs": "excluded_by_default",
            "full_native_traces": "excluded_by_default",
            "unrelated_branch_history": "not_in_dependency_scope",
            "superseded_history": "excluded_by_default",
        },
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


def _scoped_node_ids(workflow: Workflow, node_id: str) -> list[str]:
    event_producers = _event_producers(workflow)
    gate_requirements = {
        gate.node_id: [*gate.requires_all, *gate.requires_any]
        for gate in workflow.gates
    }
    visited: set[str] = set()

    def visit(current_node_id: str) -> None:
        if current_node_id in visited:
            return
        visited.add(current_node_id)
        current = workflow.nodes[current_node_id]
        required_events = [
            *_event_names(current.waits_for_all),
            *_event_names(current.waits_for_any),
            *_event_names(gate_requirements.get(current_node_id, [])),
        ]
        for event_name in required_events:
            for producer_node_id in event_producers.get(event_name, []):
                visit(producer_node_id)

    visit(node_id)
    return sorted(visited)


def _event_producers(workflow: Workflow) -> dict[str, list[str]]:
    producers: dict[str, list[str]] = {}
    for node in workflow.nodes.values():
        for event_name in node.emits:
            producers.setdefault(event_name, []).append(node.id)
    for event_name in producers:
        producers[event_name].sort()
    return producers


def _event_names(refs: list[str]) -> list[str]:
    return [ref.split(".", 1)[0] if "." in ref else ref for ref in refs]


def _event_node_id(events_by_id: dict[str, dict[str, Any]], event_id: Any) -> str | None:
    if not isinstance(event_id, str):
        return None
    event = events_by_id.get(event_id, {})
    node_id = event.get("node_id")
    return node_id if isinstance(node_id, str) and node_id else None


def _decision_node_id(
    events_by_id: dict[str, dict[str, Any]],
    decision: dict[str, Any],
) -> str | None:
    for key in ("reviewed_event", "source_event"):
        node_id = _event_node_id(events_by_id, decision.get(key))
        if node_id is not None:
            return node_id
    return None


def _scoped_record(record: dict[str, Any], scoped_node_id_set: set[str]) -> bool:
    node_id = record.get("node_id")
    if isinstance(node_id, str) and node_id:
        return node_id in scoped_node_id_set
    return True


def _artifact_refs_for_scope(
    ledger: Ledger,
    events_by_id: dict[str, dict[str, Any]],
    scoped_node_id_set: set[str],
) -> list[dict[str, Any]]:
    artifacts_by_id = {
        artifact.get("artifact_id"): artifact
        for artifact in ledger.artifacts
        if isinstance(artifact.get("artifact_id"), str)
    }
    scoped_refs: dict[str, dict[str, Any]] = {}

    for event in ledger.event_log:
        if event.get("event_type") != "review_decision_recorded":
            continue
        reviewed_event_id = event.get("reviewed_event")
        if _event_node_id(events_by_id, reviewed_event_id) not in scoped_node_id_set:
            continue
        evidence_refs = event.get("evidence_refs", [])
        if not isinstance(evidence_refs, list):
            continue
        for ref in evidence_refs:
            if not isinstance(ref, str) or not ref:
                continue
            artifact = artifacts_by_id.get(ref)
            if artifact is not None:
                payload = dict(artifact)
            else:
                payload = {"ref": ref}
            scoped_refs[_stable_artifact_key(payload)] = payload

    for artifact in ledger.artifacts:
        source_event = artifact.get("source_event")
        if _event_node_id(events_by_id, source_event) not in scoped_node_id_set:
            continue
        payload = dict(artifact)
        scoped_refs[_stable_artifact_key(payload)] = payload

    return [scoped_refs[key] for key in sorted(scoped_refs)]


def _mission_constraints(
    workflow: Workflow,
    ledger: Ledger,
    mission: Mission | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "current_goal": ledger.current_goal,
        "workflow_reason": workflow.reason,
        "mode": workflow.mode,
        "budget_policy": workflow.budget_policy,
        "broadcast_policy": workflow.broadcast_policy,
    }
    if mission is not None:
        payload["mission_status"] = mission.status
        payload["allowed_modes"] = sorted(mission.allowed_modes)
        payload["default_mode"] = mission.default_mode
        payload["budget"] = mission.budget
        payload["human_gate"] = mission.human_gate
    return payload


def _finding_sort_key(finding: dict[str, Any]) -> tuple[str, str]:
    return (
        _stable_record_key(finding, "finding_id"),
        _optional_string(finding.get("source_event")) or "",
    )


def _decision_sort_key(decision: dict[str, Any]) -> tuple[str, str]:
    return (
        _stable_record_key(decision, "decision_id"),
        _optional_string(decision.get("source_event")) or "",
    )


def _stable_record_key(record: dict[str, Any], primary_key: str) -> str:
    value = record.get(primary_key)
    if isinstance(value, str) and value:
        return value
    fallback = record.get("content") or record.get("reason") or record.get("source_event")
    return fallback if isinstance(fallback, str) else yaml.safe_dump(record, sort_keys=True)


def _stable_artifact_key(record: dict[str, Any]) -> str:
    for key in ("artifact_id", "path", "ref"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return yaml.safe_dump(record, sort_keys=True)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
