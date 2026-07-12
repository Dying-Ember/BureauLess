from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ProtocolError
from .harness import Mission, Workflow, compile_workflow
from .routing import RoutingDecision, load_routing_decision, validate_routing_decision


@dataclass(frozen=True)
class WorkerBinding:
    node_id: str
    role: str
    agent_id: str
    model: str

    def to_dict(self) -> dict[str, str]:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "agent_id": self.agent_id,
            "model": self.model,
        }


@dataclass(frozen=True)
class InitialControlPlaneProposal:
    proposal_id: str
    workflow: Workflow
    routing_decision: RoutingDecision
    worker_bindings: list[WorkerBinding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "workflow": workflow_to_dict(self.workflow),
            "routing_decision": self.routing_decision.to_dict(),
            "worker_bindings": [binding.to_dict() for binding in self.worker_bindings],
        }


def load_initial_control_plane_proposal(
    intent: Any,
    mission: Mission,
) -> InitialControlPlaneProposal:
    if not isinstance(intent, dict) or intent.get("intent_type") != "initial_control_plane":
        raise ProtocolError("Bootstrap requires one initial_control_plane intent")
    proposal_id = _string(intent, "proposal_id")
    raw_workflow = intent.get("workflow")
    if not isinstance(raw_workflow, dict):
        raise ProtocolError("Initial control-plane workflow must be an object")
    workflow = Workflow.from_dict(raw_workflow)
    if workflow.mission_id != mission.mission_id:
        raise ProtocolError("Initial control-plane workflow mission_id does not match mission")
    if workflow.status != "proposed":
        raise ProtocolError("Initial control-plane workflow must have status proposed")
    if workflow.proposed_by != "orchestrator":
        raise ProtocolError("Initial control-plane workflow must be proposed_by orchestrator")
    compiled = compile_workflow(workflow)
    if not compiled.ok:
        details = "; ".join(error.message for error in compiled.errors)
        raise ProtocolError(f"Initial control-plane workflow is invalid: {details}")
    raw_routing = intent.get("routing_decision")
    if not isinstance(raw_routing, dict):
        raise ProtocolError("Initial control-plane routing_decision must be an object")
    routing_decision = load_routing_decision(raw_routing)
    validate_routing_decision(mission, routing_decision, workflow=workflow)
    raw_bindings = intent.get("worker_bindings")
    if not isinstance(raw_bindings, list):
        raise ProtocolError("Initial control-plane worker_bindings must be a list")
    bindings = [
        WorkerBinding(
            node_id=_string(item, "node_id"),
            role=_string(item, "role"),
            agent_id=_string(item, "agent_id"),
            model=_string(item, "model"),
        )
        for item in raw_bindings
        if isinstance(item, dict)
    ]
    if len(bindings) != len(raw_bindings):
        raise ProtocolError("Initial control-plane worker_bindings entries must be objects")
    by_node = {binding.node_id: binding for binding in bindings}
    if len(by_node) != len(bindings) or set(by_node) != set(workflow.nodes):
        raise ProtocolError("Initial control-plane must bind every workflow node exactly once")
    for node_id, node in workflow.nodes.items():
        if by_node[node_id].role != node.role:
            raise ProtocolError("Initial control-plane binding role does not match workflow node")
        if _is_placeholder(by_node[node_id].model):
            raise ProtocolError("Initial control-plane binding model must be a concrete provider model")
    return InitialControlPlaneProposal(proposal_id, workflow, routing_decision, bindings)


def collect_initial_control_plane_errors(
    intent: Any,
    mission: Mission,
    *,
    allowed_agent_ids: set[str] | None = None,
    allowed_models: set[str] | None = None,
) -> list[str]:
    if not isinstance(intent, dict) or intent.get("intent_type") != "initial_control_plane":
        return ["Bootstrap requires one initial_control_plane intent"]

    errors: list[str] = []
    proposal_id = intent.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        errors.append("Initial control-plane proposal_id must be a non-empty string")
    normalized_allowed_models = (
        {model.casefold() for model in allowed_models}
        if allowed_models is not None
        else None
    )
    raw_workflow = intent.get("workflow")
    workflow: Workflow | None = None
    if not isinstance(raw_workflow, dict):
        errors.append("Initial control-plane workflow must be an object")
    else:
        if raw_workflow.get("mission_id") != mission.mission_id:
            errors.append("Initial control-plane workflow mission_id does not match mission")
        try:
            workflow = Workflow.from_dict(raw_workflow)
        except ProtocolError as exc:
            errors.append(str(exc))
        else:
            if workflow.status != "proposed":
                errors.append("Initial control-plane workflow must have status proposed")
            if workflow.proposed_by != "orchestrator":
                errors.append("Initial control-plane workflow must be proposed_by orchestrator")
            compiled = compile_workflow(workflow)
            errors.extend(error.message for error in compiled.errors)

        raw_nodes = raw_workflow.get("nodes")
        if isinstance(raw_nodes, list) and not any(
            isinstance(node, dict) and "patch_ready" in node.get("emits", [])
            for node in raw_nodes
        ):
            errors.append("Initial control-plane requires an implementation node emitting patch_ready")

    raw_routing = intent.get("routing_decision")
    if not isinstance(raw_routing, dict):
        errors.append("Initial control-plane routing_decision must be an object")
    else:
        if raw_routing.get("mission_id") != mission.mission_id:
            errors.append("Routing decision mission_id does not match mission")
        if raw_routing.get("decision_type") != "routing_decision":
            errors.append("Routing decision decision_type must be routing_decision")
        if (
            isinstance(raw_workflow, dict)
            and raw_routing.get("workflow_id") != raw_workflow.get("workflow_id")
        ):
            errors.append("Routing decision workflow_id does not match workflow")
        if isinstance(raw_workflow, dict) and raw_routing.get("selected_mode") != raw_workflow.get("mode"):
            errors.append("Routing decision selected_mode does not match workflow mode")
        try:
            routing = load_routing_decision(raw_routing)
            validate_routing_decision(mission, routing, workflow=workflow)
        except ProtocolError as exc:
            errors.append(str(exc))

    raw_bindings = intent.get("worker_bindings")
    if not isinstance(raw_bindings, list):
        errors.append("Initial control-plane worker_bindings must be a list")
    else:
        binding_nodes: list[str] = []
        for index, binding in enumerate(raw_bindings):
            if not isinstance(binding, dict):
                errors.append(f"Initial control-plane worker_bindings[{index}] must be an object")
                continue
            node_id = binding.get("node_id")
            role = binding.get("role")
            if not isinstance(node_id, str) or not node_id:
                errors.append(f"Initial control-plane worker_bindings[{index}].node_id must be a non-empty string")
            else:
                binding_nodes.append(node_id)
            if not isinstance(role, str) or not role:
                errors.append(f"Initial control-plane worker_bindings[{index}].role must be a non-empty string")
            agent_id = binding.get("agent_id")
            model = binding.get("model")
            if not isinstance(agent_id, str) or not agent_id:
                errors.append(f"Initial control-plane worker_bindings[{index}].agent_id must be a non-empty string")
            elif allowed_agent_ids is not None and agent_id not in allowed_agent_ids:
                errors.append(f"Initial control-plane proposes unsupported agent: {agent_id}")
            if not isinstance(model, str) or not model or _is_placeholder(model):
                errors.append(f"Initial control-plane worker_bindings[{index}].model must be a concrete provider model")
            elif normalized_allowed_models is not None and model.casefold() not in normalized_allowed_models:
                errors.append(f"Initial control-plane proposes model outside approved policy: {model}")
        if len(binding_nodes) != len(set(binding_nodes)):
            errors.append("Initial control-plane worker_bindings contain duplicate node_id values")
        if workflow is not None and set(binding_nodes) != set(workflow.nodes):
            errors.append("Initial control-plane must bind every workflow node exactly once")
        if workflow is not None:
            for binding in raw_bindings:
                if not isinstance(binding, dict):
                    continue
                node_id = binding.get("node_id")
                role = binding.get("role")
                if (
                    isinstance(node_id, str)
                    and node_id in workflow.nodes
                    and isinstance(role, str)
                    and role != workflow.nodes[node_id].role
                ):
                    errors.append(
                        f"Initial control-plane binding role does not match workflow node: {node_id}"
                    )

    return list(dict.fromkeys(errors))


def validate_initial_control_plane_requirements(
    proposal: InitialControlPlaneProposal,
    requirements: dict[str, Any] | None,
) -> None:
    if requirements is None:
        return
    if not isinstance(requirements, dict):
        raise ProtocolError("Control-plane requirements must be an object")
    independent_verification = requirements.get("independent_verification", False)
    terminal_commit = requirements.get("terminal_commit", False)
    if not isinstance(independent_verification, bool) or not isinstance(terminal_commit, bool):
        raise ProtocolError("Control-plane requirement values must be boolean")
    workflow = proposal.workflow
    errors: list[str] = []
    verification_nodes = [
        node
        for node in workflow.nodes.values()
        if any("verification" in event for event in node.emits)
    ]
    implementation_nodes = [
        node for node in workflow.nodes.values() if "patch_ready" in node.emits
    ]
    if independent_verification:
        if not verification_nodes:
            errors.append("Control-plane requires an independent verification node")
        if any(
            verifier.id == implementer.id
            for verifier in verification_nodes
            for implementer in implementation_nodes
        ):
            errors.append("Implementation and final verification must be separate nodes")
    if terminal_commit:
        commit_nodes = [
            node
            for node in workflow.nodes.values()
            if "commit" in node.id or "commit" in node.role or any("commit" in event for event in node.emits)
        ]
        if not commit_nodes:
            errors.append("Control-plane requires a terminal commit node")
        verification_events = {
            event for node in verification_nodes for event in node.emits
        }
        if not any(
            verification_events
            & {event_ref.split(".", 1)[-1] for event_ref in node.waits_for}
            for node in commit_nodes
        ):
            errors.append("Terminal commit must wait for independent verification")
    if errors:
        raise ProtocolError("Control-plane requirements rejected:\n- " + "\n- ".join(errors))


def accepts_initial_control_plane(intent: Any, proposal_id: str) -> bool:
    return (
        isinstance(intent, dict)
        and intent.get("intent_type") == "accept_initial_control_plane"
        and intent.get("proposal_id") == proposal_id
    )


def workflow_to_dict(workflow: Workflow) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "mission_id": workflow.mission_id,
        "mode": workflow.mode,
        "status": workflow.status,
        "reason": workflow.reason,
        "proposed_by": workflow.proposed_by,
        "roles": {
            name: {"can_emit": role.can_emit, "can_consume": role.can_consume}
            for name, role in workflow.roles.items()
        },
        "events": {
            name: {"producer_roles": event.producer_roles}
            for name, event in workflow.events.items()
        },
        "nodes": [
            {
                "id": node.id,
                "role": node.role,
                "waits_for": _branches(node.waits_for_all, node.waits_for_any),
                "emits": node.emits,
            }
            for node in workflow.nodes.values()
        ],
        "gates": [
            {
                "id": gate.id,
                "node_id": gate.node_id,
                "requires": _branches(gate.requires_all, gate.requires_any),
            }
            for gate in workflow.gates
        ],
        "terminal_events": workflow.terminal_events,
        "broadcast_policy": workflow.broadcast_policy,
        "budget_policy": workflow.budget_policy,
    }


def _branches(all_of: list[str], any_of: list[str]) -> list[str] | dict[str, list[str]]:
    return {"all_of": all_of, "any_of": any_of} if any_of else all_of


def _string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Initial control-plane field {field} must be a non-empty string")
    return value


def _is_placeholder(value: str) -> bool:
    return value.startswith("<") or value.endswith(">") or value.startswith("chosen-by-")
