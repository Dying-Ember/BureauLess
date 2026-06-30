from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..core import ProtocolError


VALID_MISSION_MODES = {
    "single_agent",
    "single_agent_with_review",
    "small_dag",
    "parallel_swarm",
    "stop_and_ask_human",
}


@dataclass(frozen=True)
class Mission:
    mission_id: str
    goal: str
    status: str
    default_mode: str
    allowed_modes: list[str]
    budget: dict[str, Any]
    models: dict[str, Any]
    human_gate: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mission":
        mission = cls(
            mission_id=_as_string(data, "mission_id"),
            goal=_as_string(data, "goal"),
            status=_as_string(data, "status"),
            default_mode=_as_string(data, "default_mode"),
            allowed_modes=_as_string_list(data, "allowed_modes"),
            budget=_as_mapping(data, "budget", default={}),
            models=_as_mapping(data, "models", default={}),
            human_gate=_as_mapping(data, "human_gate", default={}),
        )
        mission.validate()
        return mission

    def validate(self) -> None:
        if self.default_mode not in VALID_MISSION_MODES:
            raise ProtocolError(f"Mission default_mode is invalid: {self.default_mode}")
        invalid_modes = sorted(set(self.allowed_modes) - VALID_MISSION_MODES)
        if invalid_modes:
            raise ProtocolError(f"Mission has invalid allowed_modes: {', '.join(invalid_modes)}")
        if self.default_mode not in self.allowed_modes:
            raise ProtocolError("Mission default_mode must be included in allowed_modes")


@dataclass(frozen=True)
class Ledger:
    mission_id: str
    ledger_version: int
    current_goal: str
    current_plan_ref: str
    projection: dict[str, Any]
    public_findings: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    broadcasts: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    event_log: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Ledger":
        ledger = cls(
            mission_id=_as_string(data, "mission_id"),
            ledger_version=_as_int(data, "ledger_version"),
            current_goal=_as_string(data, "current_goal"),
            current_plan_ref=_as_string(data, "current_plan_ref"),
            projection=_as_mapping(data, "projection", default={}),
            public_findings=_as_mapping_list(data, "public_findings", default=[]),
            decisions=_as_mapping_list(data, "decisions", default=[]),
            risks=_as_mapping_list(data, "risks", default=[]),
            artifacts=_as_mapping_list(data, "artifacts", default=[]),
            broadcasts=_as_mapping_list(data, "broadcasts", default=[]),
            open_questions=_as_mapping_list(data, "open_questions", default=[]),
            event_log=_as_mapping_list(data, "event_log", default=[]),
        )
        ledger.validate()
        return ledger

    def validate(self) -> None:
        for finding in self.public_findings:
            missing = [
                field
                for field in ("source_event", "source_agent", "accepted_by", "review_decision_id")
                if not finding.get(field)
            ]
            if missing:
                finding_id = finding.get("finding_id", "<unknown>")
                raise ProtocolError(
                    f"Ledger finding {finding_id} is missing provenance: {', '.join(missing)}"
                )


@dataclass(frozen=True)
class RoleSpec:
    name: str
    can_emit: list[str]
    can_consume: list[str]

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "RoleSpec":
        return cls(
            name=name,
            can_emit=_as_string_list(data, "can_emit", default=[]),
            can_consume=_as_string_list(data, "can_consume", default=[]),
        )


@dataclass(frozen=True)
class EventSpec:
    name: str
    producer_roles: list[str]

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "EventSpec":
        return cls(
            name=name,
            producer_roles=_as_string_list(data, "producer_roles", default=[]),
        )


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    role: str
    waits_for: list[str]
    emits: list[str]
    waits_for_all: list[str]
    waits_for_any: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowNode":
        waits_for_all, waits_for_any = _event_ref_branches(data.get("waits_for", []))
        return cls(
            id=_as_string(data, "id"),
            role=_as_string(data, "role"),
            waits_for=[*waits_for_all, *waits_for_any],
            emits=_as_string_list(data, "emits", default=[]),
            waits_for_all=waits_for_all,
            waits_for_any=waits_for_any,
        )


@dataclass(frozen=True)
class WorkflowGate:
    id: str
    node_id: str
    requires: list[str]
    requires_all: list[str]
    requires_any: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowGate":
        requires_all, requires_any = _event_ref_branches(data.get("requires", []))
        return cls(
            id=_as_string(data, "id"),
            node_id=_as_string(data, "node_id"),
            requires=[*requires_all, *requires_any],
            requires_all=requires_all,
            requires_any=requires_any,
        )


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    mission_id: str
    mode: str
    roles: dict[str, RoleSpec]
    events: dict[str, EventSpec]
    nodes: dict[str, WorkflowNode]
    gates: list[WorkflowGate]
    terminal_events: list[str]
    status: str
    reason: str
    proposed_by: str
    broadcast_policy: dict[str, Any]
    budget_policy: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workflow":
        raw_roles = _as_mapping(data, "roles")
        raw_events = _as_mapping(data, "events")
        raw_nodes = data.get("nodes")
        if not isinstance(raw_nodes, list):
            raise ProtocolError("Workflow field 'nodes' must be a list")

        roles = {
            name: RoleSpec.from_dict(name, value)
            for name, value in raw_roles.items()
            if isinstance(value, dict)
        }
        if len(roles) != len(raw_roles):
            raise ProtocolError("Workflow field 'roles' must map role names to objects")

        events = {
            name: EventSpec.from_dict(name, value)
            for name, value in raw_events.items()
            if isinstance(value, dict)
        }
        if len(events) != len(raw_events):
            raise ProtocolError("Workflow field 'events' must map event names to objects")

        nodes: dict[str, WorkflowNode] = {}
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                raise ProtocolError("Each workflow node must be an object")
            node = WorkflowNode.from_dict(raw_node)
            if node.id in nodes:
                raise ProtocolError(f"Duplicate workflow node id: {node.id}")
            nodes[node.id] = node

        gates = [WorkflowGate.from_dict(raw_gate) for raw_gate in _as_mapping_list(data, "gates", default=[])]

        return cls(
            workflow_id=_as_string(data, "workflow_id"),
            mission_id=_as_string(data, "mission_id"),
            mode=_as_string(data, "mode"),
            roles=roles,
            events=events,
            nodes=nodes,
            gates=gates,
            terminal_events=_event_refs(data.get("terminal_events", [])),
            status=_as_string(data, "status", default="proposed"),
            reason=_as_string(data, "reason", default=""),
            proposed_by=_as_string(data, "proposed_by", default="orchestrator"),
            broadcast_policy=_as_mapping(data, "broadcast_policy", default={}),
            budget_policy=_as_mapping(data, "budget_policy", default={}),
        )


@dataclass(frozen=True)
class CompileError:
    code: str
    message: str
    node_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {"code": self.code, "message": self.message}
        if self.node_id is not None:
            payload["node_id"] = self.node_id
        return payload


@dataclass(frozen=True)
class CompileResult:
    status: str
    errors: list[CompileError]

    @property
    def ok(self) -> bool:
        return self.status == "compiled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [error.to_dict() for error in self.errors],
        }


def load_mission(path: Path) -> Mission:
    return Mission.from_dict(_load_yaml_mapping(path, "Mission"))


def load_ledger(path: Path) -> Ledger:
    from .ledger import rebuild_ledger_projection

    return rebuild_ledger_projection(Ledger.from_dict(_load_yaml_mapping(path, "Ledger")))


def load_workflow(path: Path) -> Workflow:
    return Workflow.from_dict(_load_yaml_mapping(path, "Workflow"))


def compile_workflow(workflow: Workflow) -> CompileResult:
    errors: list[CompileError] = []

    if workflow.mode not in VALID_MISSION_MODES:
        errors.append(
            CompileError("invalid_mode", f"Workflow mode is invalid: {workflow.mode}")
        )

    if not workflow.terminal_events:
        errors.append(
            CompileError(
                "missing_terminal_events",
                "Workflow must declare at least one terminal event",
            )
        )

    errors.extend(_validate_event_registry(workflow))
    errors.extend(_validate_nodes(workflow))
    errors.extend(_validate_gates(workflow))
    errors.extend(_validate_terminal_events(workflow))
    errors.extend(_validate_committer_gates(workflow))

    return CompileResult(status="rejected" if errors else "compiled", errors=errors)


def _validate_event_registry(workflow: Workflow) -> list[CompileError]:
    errors: list[CompileError] = []
    for event in workflow.events.values():
        for role_name in event.producer_roles:
            role = workflow.roles.get(role_name)
            if role is None:
                errors.append(
                    CompileError(
                        "unknown_event_producer_role",
                        f"Event {event.name} references unknown producer role {role_name}",
                    )
                )
                continue
            if event.name not in role.can_emit:
                errors.append(
                    CompileError(
                        "producer_role_cannot_emit",
                        f"Role {role_name} is listed as a producer for {event.name} but cannot emit it",
                    )
                )
    return errors


def _validate_nodes(workflow: Workflow) -> list[CompileError]:
    errors: list[CompileError] = []
    for node in workflow.nodes.values():
        role = workflow.roles.get(node.role)
        if role is None:
            errors.append(
                CompileError("unknown_role", f"Node {node.id} references unknown role {node.role}", node.id)
            )
            continue

        for event_name in node.emits:
            if event_name not in workflow.events:
                errors.append(
                    CompileError("unknown_event", f"Node emits unknown event {event_name}", node.id)
                )
            elif event_name not in role.can_emit:
                errors.append(
                    CompileError(
                        "unauthorized_emit",
                        f"Role {node.role} cannot emit event {event_name}",
                        node.id,
                    )
                )

        for event_ref in node.waits_for:
            event_name = _event_name(event_ref)
            if event_name not in workflow.events:
                errors.append(
                    CompileError("unknown_wait_event", f"Node waits for unknown event {event_ref}", node.id)
                )
            elif event_name not in role.can_consume:
                errors.append(
                    CompileError(
                        "unauthorized_consume",
                        f"Role {node.role} cannot consume event {event_name}",
                        node.id,
                    )
                )
            if not _event_ref_is_satisfiable(workflow, event_ref):
                errors.append(
                    CompileError(
                        "unsatisfied_wait_event",
                        f"Node waits for event that no upstream node emits: {event_ref}",
                        node.id,
                    )
                )
    return errors


def _validate_gates(workflow: Workflow) -> list[CompileError]:
    errors: list[CompileError] = []
    for gate in workflow.gates:
        if gate.node_id not in workflow.nodes:
            errors.append(
                CompileError(
                    "unknown_gate_node",
                    f"Gate {gate.id} references unknown node {gate.node_id}",
                    gate.node_id,
                )
            )
        for event_ref in gate.requires:
            event_name = _event_name(event_ref)
            if event_name not in workflow.events:
                errors.append(
                    CompileError(
                        "unknown_gate_event",
                        f"Gate {gate.id} requires unknown event {event_ref}",
                        gate.node_id,
                    )
                )
            if not _event_ref_is_satisfiable(workflow, event_ref):
                errors.append(
                    CompileError(
                        "unsatisfied_gate_event",
                        f"Gate {gate.id} requires event that no upstream node emits: {event_ref}",
                        gate.node_id,
                    )
                )
    return errors


def _validate_terminal_events(workflow: Workflow) -> list[CompileError]:
    errors: list[CompileError] = []
    for event_ref in workflow.terminal_events:
        event_name = _event_name(event_ref)
        if event_name not in workflow.events:
            errors.append(
                CompileError(
                    "unknown_terminal_event",
                    f"Terminal event is not declared: {event_ref}",
                )
            )
        if not _event_ref_is_satisfiable(workflow, event_ref):
            errors.append(
                CompileError(
                    "unsatisfied_terminal_event",
                    f"Terminal event is not emitted by any node: {event_ref}",
                )
            )
    return errors


def _validate_committer_gates(workflow: Workflow) -> list[CompileError]:
    errors: list[CompileError] = []
    for node in workflow.nodes.values():
        emits_commit_event = any("commit" in event_name for event_name in node.emits)
        if "commit" not in node.id and "commit" not in node.role and not emits_commit_event:
            continue
        waits = {_event_name(event_ref) for event_ref in node.waits_for}
        missing = sorted({"patch_ready", "review_approved"} - waits)
        if missing:
            errors.append(
                CompileError(
                    "missing_commit_gate",
                    f"Commit node must wait for patch_ready and review_approved; missing {', '.join(missing)}",
                    node.id,
                )
            )
    return errors


def _event_ref_is_satisfiable(workflow: Workflow, event_ref: str) -> bool:
    if "." in event_ref:
        node_id, event_name = event_ref.split(".", 1)
        node = workflow.nodes.get(node_id)
        return node is not None and event_name in node.emits
    event_name = _event_name(event_ref)
    return any(event_name in node.emits for node in workflow.nodes.values())


def _event_name(event_ref: str) -> str:
    return event_ref.split(".", 1)[1] if "." in event_ref else event_ref


def _load_yaml_mapping(path: Path, label: str) -> dict[str, Any]:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise ProtocolError(f"{label} documents must use .yaml or .yml")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ProtocolError(f"{label} document must be an object")
    return data


def _as_string(data: dict[str, Any], key: str, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ProtocolError(f"Field {key!r} must be a string")
    return value


def _as_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ProtocolError(f"Field {key!r} must be an integer")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Field {key!r} must be an object")
    return value


def _as_string_list(
    data: dict[str, Any],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProtocolError(f"Field {key!r} must be a list of strings")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Field {key!r} must be a list of objects")
    return value


def _event_refs(value: Any) -> list[str]:
    all_of, any_of = _event_ref_branches(value)
    return [*all_of, *any_of]


def _event_ref_branches(value: Any) -> tuple[list[str], list[str]]:
    if value is None:
        return [], []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value, []
    if isinstance(value, dict):
        all_of: list[str] = []
        any_of: list[str] = []
        for key in ("all_of", "any_of"):
            branch = value.get(key, [])
            if not isinstance(branch, list) or not all(isinstance(item, str) for item in branch):
                raise ProtocolError(f"waits_for/requires field {key!r} must be a list of strings")
            if key == "all_of":
                all_of = branch
            else:
                any_of = branch
        return all_of, any_of
    raise ProtocolError("Event references must be a list or an object with all_of/any_of")
