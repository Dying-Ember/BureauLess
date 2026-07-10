from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

from ..errors import ProtocolError
from .harness import Ledger, Workflow, WorkflowNode, compile_workflow


MUTATION_REASONS = {
    "discovered_missing_dependency",
    "node_needs_split",
    "stale_result",
    "other",
}
MUTATION_ACTORS = {"worker", "orchestrator"}
APPROVAL_ACTORS = {"orchestrator", "human"}

_TOP_LEVEL_FIELDS = {
    "proposal_id",
    "proposal_type",
    "workflow_id",
    "source",
    "reason",
    "rationale",
    "proposed_changes",
    "evidence_refs",
    "requires_approval",
}
_SOURCE_FIELDS = {"assignment_id", "session_id", "actor"}
_CHANGE_FIELDS = {
    "add_nodes",
    "add_edges",
    "remove_edges",
    "supersede_assignments",
}
_NODE_FIELDS = {"id", "role", "waits_for", "emits"}
_EDGE_FIELDS = {"from_node", "to_node", "event"}
_FORBIDDEN_CHANGE_FIELDS = {
    "remove_nodes",
    "rewrite_events",
    "ledger_events",
    "create_assignments",
    "assignments",
}
_INTENT_FIELDS = {
    "intent_type",
    "reason",
    "rationale",
    "proposed_changes",
    "evidence_refs",
}
_TRUSTED_PROPOSAL_FIELDS = {
    "proposal_id",
    "proposal_type",
    "workflow_id",
    "base_workflow_version_id",
    "source",
    "requires_approval",
    "intent",
}
_TRUSTED_SOURCE_FIELDS = {"assignment_id", "session_id", "agent_id", "actor"}


def canonical_workflow_payload(workflow: Workflow) -> dict[str, Any]:
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
        "broadcast_policy": workflow.broadcast_policy,
        "budget_policy": workflow.budget_policy,
    }


def workflow_content_hash(workflow: Workflow) -> str:
    return hashlib.sha256(
        json.dumps(
            canonical_workflow_payload(workflow),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def workflow_version_identity(workflow: Workflow, sequence: int) -> str:
    if sequence < 0:
        raise ProtocolError("Workflow version sequence cannot be negative")
    return (
        f"{workflow.workflow_id}:v{sequence:04d}:"
        f"{workflow_content_hash(workflow)[:12]}"
    )


@dataclass(frozen=True)
class MutationSource:
    assignment_id: str
    session_id: str | None
    actor: str

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "assignment_id": self.assignment_id,
            "actor": self.actor,
        }
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        return payload


@dataclass(frozen=True)
class MutationEdge:
    from_node: str
    to_node: str
    event: str

    @property
    def event_ref(self) -> str:
        return f"{self.from_node}.{self.event}"

    def to_dict(self) -> dict[str, str]:
        return {
            "from_node": self.from_node,
            "to_node": self.to_node,
            "event": self.event,
        }


@dataclass(frozen=True)
class MutationChanges:
    add_nodes: list[WorkflowNode]
    add_edges: list[MutationEdge]
    remove_edges: list[MutationEdge]
    supersede_assignments: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "add_nodes": [_node_to_dict(node) for node in self.add_nodes],
            "add_edges": [edge.to_dict() for edge in self.add_edges],
            "remove_edges": [edge.to_dict() for edge in self.remove_edges],
            "supersede_assignments": self.supersede_assignments,
        }


@dataclass(frozen=True)
class WorkflowMutationProposal:
    proposal_id: str
    workflow_id: str
    source: MutationSource
    reason: str
    rationale: str
    proposed_changes: MutationChanges
    evidence_refs: list[str]
    requires_approval: str
    proposal_type: str = "workflow_mutation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "workflow_id": self.workflow_id,
            "source": self.source.to_dict(),
            "reason": self.reason,
            "rationale": self.rationale,
            "proposed_changes": self.proposed_changes.to_dict(),
            "evidence_refs": self.evidence_refs,
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True)
class WorkflowMutationIntent:
    reason: str
    rationale: str
    proposed_changes: MutationChanges
    evidence_refs: list[str]
    intent_type: str = "workflow_mutation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "reason": self.reason,
            "rationale": self.rationale,
            "proposed_changes": self.proposed_changes.to_dict(),
            "evidence_refs": self.evidence_refs,
        }


@dataclass(frozen=True)
class TrustedMutationSource:
    assignment_id: str
    session_id: str
    agent_id: str
    actor: str = "worker"

    def to_dict(self) -> dict[str, str]:
        return {
            "assignment_id": self.assignment_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "actor": self.actor,
        }


@dataclass(frozen=True)
class TrustedWorkflowMutationProposal:
    proposal_id: str
    workflow_id: str
    base_workflow_version_id: str
    source: TrustedMutationSource
    requires_approval: str
    intent: WorkflowMutationIntent
    proposal_type: str = "workflow_mutation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "workflow_id": self.workflow_id,
            "base_workflow_version_id": self.base_workflow_version_id,
            "source": self.source.to_dict(),
            "requires_approval": self.requires_approval,
            "intent": self.intent.to_dict(),
        }


@dataclass(frozen=True)
class MutationValidationError:
    code: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class MutationValidationResult:
    status: str
    errors: list[MutationValidationError]
    proposal: WorkflowMutationProposal | None = None

    @property
    def ok(self) -> bool:
        return self.status == "valid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [error.to_dict() for error in self.errors],
        }


@dataclass(frozen=True)
class MutationIntentValidationResult:
    status: str
    errors: list[MutationValidationError]
    intent: WorkflowMutationIntent | None = None

    @property
    def ok(self) -> bool:
        return self.status == "valid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [error.to_dict() for error in self.errors],
        }


@dataclass(frozen=True)
class TrustedProposalBuildResult:
    status: str
    errors: list[MutationValidationError]
    proposal: TrustedWorkflowMutationProposal | None = None

    @property
    def ok(self) -> bool:
        return self.status == "valid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [error.to_dict() for error in self.errors],
        }


def validate_workflow_mutation_intent(
    data: dict[str, Any],
) -> MutationIntentValidationResult:
    if not isinstance(data, dict):
        return MutationIntentValidationResult(
            status="rejected",
            errors=[
                MutationValidationError(
                    "invalid_intent_type",
                    "Workflow mutation intent must be an object",
                )
            ],
        )

    errors = _unknown_fields(data, _INTENT_FIELDS, "intent")
    proposal_data = {
        "proposal_id": "untrusted-intent-validation",
        "proposal_type": data.get("intent_type"),
        "workflow_id": "untrusted-intent-validation",
        "source": {
            "assignment_id": "untrusted-intent-validation",
            "actor": "worker",
        },
        "reason": data.get("reason"),
        "rationale": data.get("rationale"),
        "proposed_changes": data.get("proposed_changes"),
        "evidence_refs": data.get("evidence_refs"),
        "requires_approval": "orchestrator",
    }
    proposal_result = validate_workflow_mutation_proposal(proposal_data)
    errors.extend(proposal_result.errors)
    if errors or proposal_result.proposal is None:
        return MutationIntentValidationResult(status="rejected", errors=errors)

    proposal = proposal_result.proposal
    return MutationIntentValidationResult(
        status="valid",
        errors=[],
        intent=WorkflowMutationIntent(
            intent_type=proposal.proposal_type,
            reason=proposal.reason,
            rationale=proposal.rationale,
            proposed_changes=proposal.proposed_changes,
            evidence_refs=proposal.evidence_refs,
        ),
    )


def build_trusted_workflow_mutation_proposal(
    data: dict[str, Any],
    *,
    workflow_id: str,
    assignment_id: str,
    session_id: str,
    agent_id: str,
    source_result_event_id: str,
    assignment_workflow_version_id: str,
    current_workflow_version_id: str,
    requires_approval: str,
) -> TrustedProposalBuildResult:
    intent_result = validate_workflow_mutation_intent(data)
    if not intent_result.ok or intent_result.intent is None:
        return TrustedProposalBuildResult(
            status="rejected",
            errors=intent_result.errors,
        )
    if assignment_workflow_version_id != current_workflow_version_id:
        return TrustedProposalBuildResult(
            status="stale",
            errors=[
                MutationValidationError(
                    "stale_workflow_version",
                    "Assignment workflow version is no longer current",
                    "base_workflow_version_id",
                )
            ],
        )
    if requires_approval not in APPROVAL_ACTORS:
        return TrustedProposalBuildResult(
            status="rejected",
            errors=[
                MutationValidationError(
                    "invalid_approval_actor",
                    f"requires_approval must be one of: {', '.join(sorted(APPROVAL_ACTORS))}",
                    "requires_approval",
                )
            ],
        )

    intent = intent_result.intent
    identity_payload = {
        "source_result_event_id": source_result_event_id,
        "intent_ordinal": 0,
        "base_workflow_version_id": assignment_workflow_version_id,
        "intent": intent.to_dict(),
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    proposal = TrustedWorkflowMutationProposal(
        proposal_id=f"proposal-{digest}",
        workflow_id=workflow_id,
        base_workflow_version_id=assignment_workflow_version_id,
        source=TrustedMutationSource(
            assignment_id=assignment_id,
            session_id=session_id,
            agent_id=agent_id,
        ),
        requires_approval=requires_approval,
        intent=intent,
    )
    return TrustedProposalBuildResult(status="valid", errors=[], proposal=proposal)


def validate_workflow_mutation_proposal(
    data: dict[str, Any],
) -> MutationValidationResult:
    errors: list[MutationValidationError] = []
    proposal: WorkflowMutationProposal | None = None

    if not isinstance(data, dict):
        return MutationValidationResult(
            status="rejected",
            errors=[
                MutationValidationError(
                    "invalid_proposal_type",
                    "Workflow mutation proposal must be an object",
                )
            ],
        )

    errors.extend(_unknown_fields(data, _TOP_LEVEL_FIELDS, "proposal"))
    raw_changes = data.get("proposed_changes")
    if isinstance(raw_changes, dict):
        for field in sorted(set(raw_changes) & _FORBIDDEN_CHANGE_FIELDS):
            errors.append(
                MutationValidationError(
                    "forbidden_mutation_operation",
                    f"Mutation proposals cannot use {field!r}",
                    f"proposed_changes.{field}",
                )
            )
        errors.extend(_unknown_fields(raw_changes, _CHANGE_FIELDS, "proposed_changes"))

    try:
        proposal = _parse_proposal(data)
    except ProtocolError as exc:
        errors.append(MutationValidationError("invalid_schema", str(exc)))

    if proposal is not None:
        errors.extend(_validate_semantics(proposal))

    return MutationValidationResult(
        status="rejected" if errors else "valid",
        errors=errors,
        proposal=proposal if not errors else None,
    )


def load_trusted_workflow_mutation_proposal(
    data: dict[str, Any],
) -> TrustedWorkflowMutationProposal:
    unknown = _unknown_fields(data, _TRUSTED_PROPOSAL_FIELDS, "proposal")
    source = _mapping(data, "source")
    unknown.extend(_unknown_fields(source, _TRUSTED_SOURCE_FIELDS, "source"))
    if unknown:
        details = "; ".join(error.message for error in unknown)
        raise ProtocolError(f"Invalid trusted workflow mutation proposal: {details}")
    intent_result = validate_workflow_mutation_intent(_mapping(data, "intent"))
    if not intent_result.ok or intent_result.intent is None:
        details = "; ".join(
            f"{error.code}: {error.message}" for error in intent_result.errors
        )
        raise ProtocolError(f"Invalid trusted workflow mutation proposal: {details}")
    proposal_type = _non_empty_string(data, "proposal_type")
    actor = _non_empty_string(source, "actor")
    approval = _non_empty_string(data, "requires_approval")
    if proposal_type != "workflow_mutation":
        raise ProtocolError("Trusted proposal_type must be 'workflow_mutation'")
    if actor != "worker":
        raise ProtocolError("Trusted worker proposal source actor must be 'worker'")
    if approval not in APPROVAL_ACTORS:
        raise ProtocolError(
            f"Trusted requires_approval must be one of: {', '.join(sorted(APPROVAL_ACTORS))}"
        )
    return TrustedWorkflowMutationProposal(
        proposal_id=_non_empty_string(data, "proposal_id"),
        proposal_type=proposal_type,
        workflow_id=_non_empty_string(data, "workflow_id"),
        base_workflow_version_id=_non_empty_string(
            data, "base_workflow_version_id"
        ),
        source=TrustedMutationSource(
            assignment_id=_non_empty_string(source, "assignment_id"),
            session_id=_non_empty_string(source, "session_id"),
            agent_id=_non_empty_string(source, "agent_id"),
            actor=actor,
        ),
        requires_approval=approval,
        intent=intent_result.intent,
    )


def load_workflow_mutation_proposal(
    data: dict[str, Any],
) -> WorkflowMutationProposal | TrustedWorkflowMutationProposal:
    if "intent" in data:
        return load_trusted_workflow_mutation_proposal(data)
    result = validate_workflow_mutation_proposal(data)
    if not result.ok or result.proposal is None:
        details = "; ".join(
            f"{error.code}: {error.message}" for error in result.errors
        )
        raise ProtocolError(f"Invalid workflow mutation proposal: {details}")
    return result.proposal


def mutation_proposed_changes(data: dict[str, Any]) -> dict[str, Any] | None:
    intent = data.get("intent")
    container = intent if isinstance(intent, dict) else data
    changes = container.get("proposed_changes")
    return changes if isinstance(changes, dict) else None


def materialize_current_workflow(
    initial_workflow: Workflow,
    ledger: Ledger,
) -> Workflow:
    current = initial_workflow
    proposals = {
        event.get("event_id"): event
        for event in ledger.event_log
        if event.get("event_type") == "workflow_mutation_proposed"
        and isinstance(event.get("event_id"), str)
    }
    for event in ledger.event_log:
        if event.get("event_type") != "workflow_mutation_accepted":
            continue
        source_event_id = event.get("source_event_id")
        source_event = proposals.get(source_event_id)
        if source_event is None:
            raise ProtocolError(
                "Accepted mutation references a missing proposal event"
            )
        raw_proposal = source_event.get("mutation_proposal")
        if not isinstance(raw_proposal, dict):
            raise ProtocolError("Mutation proposal event is missing mutation_proposal")
        proposal = load_workflow_mutation_proposal(raw_proposal)
        if proposal.workflow_id != initial_workflow.workflow_id:
            raise ProtocolError(
                "Mutation proposal workflow_id does not match initial workflow"
            )
        applied_changes = event.get("applied_changes")
        if not isinstance(applied_changes, dict):
            raise ProtocolError("Accepted mutation is missing applied_changes")
        current = _apply_changes(current, applied_changes)
        compile_result = compile_workflow(current)
        if not compile_result.ok:
            details = "; ".join(
                f"{error.code}: {error.message}" for error in compile_result.errors
            )
            raise ProtocolError(f"Accepted mutation produced invalid workflow: {details}")
        if _has_dependency_cycle(current):
            raise ProtocolError("Accepted mutation produced a workflow dependency cycle")
    return current


def _parse_proposal(data: dict[str, Any]) -> WorkflowMutationProposal:
    source_data = _mapping(data, "source")
    changes_data = _mapping(data, "proposed_changes")

    source_unknown = _unknown_fields(source_data, _SOURCE_FIELDS, "source")
    if source_unknown:
        raise ProtocolError(source_unknown[0].message)

    add_nodes_data = _mapping_list(changes_data, "add_nodes", default=[])
    add_nodes: list[WorkflowNode] = []
    for index, node_data in enumerate(add_nodes_data):
        unknown = _unknown_fields(node_data, _NODE_FIELDS, f"proposed_changes.add_nodes[{index}]")
        if unknown:
            raise ProtocolError(unknown[0].message)
        add_nodes.append(WorkflowNode.from_dict(node_data))

    return WorkflowMutationProposal(
        proposal_id=_non_empty_string(data, "proposal_id"),
        proposal_type=_non_empty_string(data, "proposal_type"),
        workflow_id=_non_empty_string(data, "workflow_id"),
        source=MutationSource(
            assignment_id=_non_empty_string(source_data, "assignment_id"),
            session_id=_optional_non_empty_string(source_data, "session_id"),
            actor=_non_empty_string(source_data, "actor"),
        ),
        reason=_non_empty_string(data, "reason"),
        rationale=_non_empty_string(data, "rationale"),
        proposed_changes=MutationChanges(
            add_nodes=add_nodes,
            add_edges=_edges(changes_data, "add_edges"),
            remove_edges=_edges(changes_data, "remove_edges"),
            supersede_assignments=_string_list(
                changes_data, "supersede_assignments", default=[]
            ),
        ),
        evidence_refs=_string_list(data, "evidence_refs"),
        requires_approval=_non_empty_string(data, "requires_approval"),
    )


def _apply_changes(
    workflow: Workflow,
    changes: dict[str, Any],
) -> Workflow:
    nodes = dict(workflow.nodes)
    for raw_node in _mapping_list(changes, "add_nodes", default=[]):
        node = WorkflowNode.from_dict(raw_node)
        if node.id in nodes:
            raise ProtocolError(f"Accepted mutation adds duplicate node id: {node.id}")
        nodes[node.id] = node

    current = replace(workflow, nodes=nodes)
    for raw_edge in _mapping_list(changes, "add_edges", default=[]):
        edge = _parse_edge(raw_edge)
        current = _add_edge(current, edge)
    for raw_edge in _mapping_list(changes, "remove_edges", default=[]):
        edge = _parse_edge(raw_edge)
        current = _remove_edge(current, edge)
    superseded = changes.get("supersede_assignments", [])
    if not isinstance(superseded, list) or not all(
        isinstance(item, str) and item for item in superseded
    ):
        raise ProtocolError(
            "Accepted mutation supersede_assignments must be a list of strings"
        )
    return current


def _event_branches(
    all_of: list[str], any_of: list[str]
) -> list[str] | dict[str, list[str]]:
    if any_of:
        return {"all_of": all_of, "any_of": any_of}
    return all_of


def _add_edge(workflow: Workflow, edge: MutationEdge) -> Workflow:
    source, target = _edge_nodes(workflow, edge)
    if edge.event not in source.emits:
        raise ProtocolError(
            f"Mutation edge source {source.id} does not emit {edge.event}"
        )
    if edge.event_ref in target.waits_for or _equivalent_unqualified_edge(
        workflow, target, edge
    ):
        raise ProtocolError(
            f"Mutation edge already exists: {edge.event_ref} -> {target.id}"
        )
    updated_target = replace(
        target,
        waits_for=[*target.waits_for, edge.event_ref],
        waits_for_all=[*target.waits_for_all, edge.event_ref],
    )
    return replace(workflow, nodes={**workflow.nodes, target.id: updated_target})


def _remove_edge(workflow: Workflow, edge: MutationEdge) -> Workflow:
    source, target = _edge_nodes(workflow, edge)
    if edge.event not in source.emits:
        raise ProtocolError(
            f"Mutation edge source {source.id} does not emit {edge.event}"
        )
    event_ref = edge.event_ref
    if event_ref not in target.waits_for:
        if _equivalent_unqualified_edge(workflow, target, edge):
            event_ref = edge.event
        else:
            raise ProtocolError(
                f"Mutation edge does not exist: {edge.event_ref} -> {target.id}"
            )
    updated_target = replace(
        target,
        waits_for=[ref for ref in target.waits_for if ref != event_ref],
        waits_for_all=[ref for ref in target.waits_for_all if ref != event_ref],
        waits_for_any=[ref for ref in target.waits_for_any if ref != event_ref],
    )
    return replace(workflow, nodes={**workflow.nodes, target.id: updated_target})


def _edge_nodes(
    workflow: Workflow,
    edge: MutationEdge,
) -> tuple[WorkflowNode, WorkflowNode]:
    source = workflow.nodes.get(edge.from_node)
    if source is None:
        raise ProtocolError(f"Mutation edge references unknown source: {edge.from_node}")
    target = workflow.nodes.get(edge.to_node)
    if target is None:
        raise ProtocolError(f"Mutation edge references unknown target: {edge.to_node}")
    return source, target


def _equivalent_unqualified_edge(
    workflow: Workflow,
    target: WorkflowNode,
    edge: MutationEdge,
) -> bool:
    if edge.event not in target.waits_for:
        return False
    emitters = {
        node.id for node in workflow.nodes.values() if edge.event in node.emits
    }
    return emitters == {edge.from_node}


def _parse_edge(raw_edge: dict[str, Any]) -> MutationEdge:
    return MutationEdge(
        from_node=_non_empty_string(raw_edge, "from_node"),
        to_node=_non_empty_string(raw_edge, "to_node"),
        event=_non_empty_string(raw_edge, "event"),
    )


def _has_dependency_cycle(workflow: Workflow) -> bool:
    emitters: dict[str, set[str]] = {}
    for node in workflow.nodes.values():
        for event_name in node.emits:
            emitters.setdefault(event_name, set()).add(node.id)
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in workflow.nodes}
    for target in workflow.nodes.values():
        for event_ref in target.waits_for:
            if "." in event_ref:
                source, _ = event_ref.split(".", 1)
                sources = {source}
            else:
                sources = emitters.get(event_ref, set())
            for source in sources:
                if source in adjacency:
                    adjacency[source].add(target.id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(child) for child in adjacency[node_id]):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in workflow.nodes)


def _validate_semantics(
    proposal: WorkflowMutationProposal,
) -> list[MutationValidationError]:
    errors: list[MutationValidationError] = []
    if proposal.proposal_type != "workflow_mutation":
        errors.append(
            MutationValidationError(
                "invalid_proposal_type",
                "proposal_type must be 'workflow_mutation'",
                "proposal_type",
            )
        )
    if proposal.reason not in MUTATION_REASONS:
        errors.append(
            MutationValidationError(
                "invalid_mutation_reason",
                f"Unknown mutation reason: {proposal.reason}",
                "reason",
            )
        )
    if proposal.source.actor not in MUTATION_ACTORS:
        errors.append(
            MutationValidationError(
                "invalid_mutation_actor",
                f"Mutation actor must be one of: {', '.join(sorted(MUTATION_ACTORS))}",
                "source.actor",
            )
        )
    if proposal.requires_approval not in APPROVAL_ACTORS:
        errors.append(
            MutationValidationError(
                "invalid_approval_actor",
                f"requires_approval must be one of: {', '.join(sorted(APPROVAL_ACTORS))}",
                "requires_approval",
            )
        )
    if not proposal.evidence_refs:
        errors.append(
            MutationValidationError(
                "missing_evidence_refs",
                "Mutation proposal must cite at least one evidence artifact",
                "evidence_refs",
            )
        )

    changes = proposal.proposed_changes
    if not any(
        (
            changes.add_nodes,
            changes.add_edges,
            changes.remove_edges,
            changes.supersede_assignments,
        )
    ):
        errors.append(
            MutationValidationError(
                "empty_mutation",
                "Mutation proposal must contain at least one proposed change",
                "proposed_changes",
            )
        )

    node_ids = [node.id for node in changes.add_nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append(
            MutationValidationError(
                "duplicate_added_node",
                "Mutation proposal contains duplicate added node ids",
                "proposed_changes.add_nodes",
            )
        )

    add_edges = [_edge_key(edge) for edge in changes.add_edges]
    remove_edges = [_edge_key(edge) for edge in changes.remove_edges]
    if len(add_edges) != len(set(add_edges)):
        errors.append(
            MutationValidationError(
                "duplicate_added_edge",
                "Mutation proposal contains duplicate add_edges entries",
                "proposed_changes.add_edges",
            )
        )
    if len(remove_edges) != len(set(remove_edges)):
        errors.append(
            MutationValidationError(
                "duplicate_removed_edge",
                "Mutation proposal contains duplicate remove_edges entries",
                "proposed_changes.remove_edges",
            )
        )
    if set(add_edges) & set(remove_edges):
        errors.append(
            MutationValidationError(
                "conflicting_edge_change",
                "The same edge cannot be added and removed in one proposal",
                "proposed_changes",
            )
        )
    if len(changes.supersede_assignments) != len(set(changes.supersede_assignments)):
        errors.append(
            MutationValidationError(
                "duplicate_superseded_assignment",
                "supersede_assignments must not contain duplicates",
                "proposed_changes.supersede_assignments",
            )
        )
    return errors


def _edges(data: dict[str, Any], key: str) -> list[MutationEdge]:
    edges = []
    for index, raw_edge in enumerate(_mapping_list(data, key, default=[])):
        unknown = _unknown_fields(raw_edge, _EDGE_FIELDS, f"proposed_changes.{key}[{index}]")
        if unknown:
            raise ProtocolError(unknown[0].message)
        edge = MutationEdge(
            from_node=_non_empty_string(raw_edge, "from_node"),
            to_node=_non_empty_string(raw_edge, "to_node"),
            event=_non_empty_string(raw_edge, "event"),
        )
        if edge.from_node == edge.to_node:
            raise ProtocolError(f"Mutation edge {key}[{index}] cannot be a self-edge")
        edges.append(edge)
    return edges


def _unknown_fields(
    data: dict[str, Any], allowed: set[str], path: str
) -> list[MutationValidationError]:
    return [
        MutationValidationError(
            "unknown_field",
            f"Unknown field {field!r} at {path}",
            f"{path}.{field}",
        )
        for field in sorted(set(data) - allowed)
    ]


def _non_empty_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"Mutation field {key!r} must be a non-empty string")
    return value


def _optional_non_empty_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"Mutation field {key!r} must be a non-empty string when present")
    return value


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ProtocolError(f"Mutation field {key!r} must be an object")
    return value


def _mapping_list(
    data: dict[str, Any], key: str, default: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Mutation field {key!r} must be a list of objects")
    return value


def _string_list(
    data: dict[str, Any], key: str, default: list[str] | None = None
) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ProtocolError(f"Mutation field {key!r} must be a list of non-empty strings")
    return value


def _edge_key(edge: MutationEdge) -> tuple[str, str, str]:
    return edge.from_node, edge.to_node, edge.event


def _node_to_dict(node: WorkflowNode) -> dict[str, Any]:
    waits_for: list[str] | dict[str, list[str]]
    if node.waits_for_any:
        waits_for = {
            "all_of": node.waits_for_all,
            "any_of": node.waits_for_any,
        }
    else:
        waits_for = node.waits_for_all
    return {
        "id": node.id,
        "role": node.role,
        "waits_for": waits_for,
        "emits": node.emits,
    }
