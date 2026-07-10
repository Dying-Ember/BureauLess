from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from ..errors import ProtocolError
from ..protocol.harness import (
    STRICT_ACCEPTANCE_LEDGER_VERSION,
    Ledger,
    Workflow,
    WorkflowGate,
    WorkflowNode,
)
from ..protocol.ledger import rebuild_ledger_projection
from ..protocol.mutations import (
    materialize_current_workflow,
    mutation_proposed_changes,
    workflow_content_hash,
    workflow_version_identity,
)


NodeRuntimeState = Literal["runnable", "blocked", "completed"]
AssignmentAttemptStatus = Literal[
    "in_flight",
    "retry_scheduled",
    "awaiting_context",
    "context_blocked",
    "awaiting_acceptance",
    "completed",
    "rejected",
    "timed_out",
    "cancelled",
    "superseded",
]
MutationDecisionStatus = Literal["pending", "accepted", "rejected"]
AssignmentImpactClassification = Literal[
    "affected",
    "unaffected",
    "needs_review",
]


@dataclass(frozen=True)
class BlockedReason:
    code: str
    message: str
    missing_ref: str | None = None
    gate_id: str | None = None
    assignment_id: str | None = None
    mutation_event_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.missing_ref is not None:
            payload["missing_ref"] = self.missing_ref
        if self.gate_id is not None:
            payload["gate_id"] = self.gate_id
        if self.assignment_id is not None:
            payload["assignment_id"] = self.assignment_id
        if self.mutation_event_id is not None:
            payload["mutation_event_id"] = self.mutation_event_id
        return payload


@dataclass(frozen=True)
class AssignmentAttemptState:
    assignment_id: str
    node_id: str
    state: AssignmentAttemptStatus
    created_event_id: str | None
    terminal_event_id: str | None
    terminal_event_type: str | None
    retry_of: str | None
    superseded_by: str | None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "assignment_id": self.assignment_id,
            "node_id": self.node_id,
            "state": self.state,
        }
        if self.created_event_id is not None:
            payload["created_event_id"] = self.created_event_id
        if self.terminal_event_id is not None:
            payload["terminal_event_id"] = self.terminal_event_id
        if self.terminal_event_type is not None:
            payload["terminal_event_type"] = self.terminal_event_type
        if self.retry_of is not None:
            payload["retry_of"] = self.retry_of
        if self.superseded_by is not None:
            payload["superseded_by"] = self.superseded_by
        return payload


@dataclass(frozen=True)
class AssignmentImpact:
    assignment_id: str
    node_id: str | None
    classification: AssignmentImpactClassification
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "assignment_id": self.assignment_id,
            "classification": self.classification,
            "reasons": self.reasons,
        }
        if self.node_id is not None:
            payload["node_id"] = self.node_id
        return payload


@dataclass(frozen=True)
class NodeReplayState:
    node_id: str
    state: NodeRuntimeState
    emitted_events: list[str]
    blocked_reasons: list[BlockedReason]
    assignment_attempts: list[AssignmentAttemptState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "state": self.state,
            "emitted_events": self.emitted_events,
            "blocked_reasons": [reason.to_dict() for reason in self.blocked_reasons],
            "assignment_attempts": [attempt.to_dict() for attempt in self.assignment_attempts],
        }


@dataclass(frozen=True)
class MutationReplayState:
    proposal_id: str
    proposal_event_id: str
    state: MutationDecisionStatus
    affected_node_ids: list[str]
    decision_event_id: str | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "proposal_id": self.proposal_id,
            "proposal_event_id": self.proposal_event_id,
            "state": self.state,
            "affected_node_ids": self.affected_node_ids,
        }
        if self.decision_event_id is not None:
            payload["decision_event_id"] = self.decision_event_id
        return payload


@dataclass(frozen=True)
class AssignmentVersionValidity:
    assignment_id: str
    node_id: str | None
    creation_version_id: str | None
    active_version_id: str
    status: AssignmentImpactClassification
    reasons: list[str]
    transition_event_id: str | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "assignment_id": self.assignment_id,
            "active_version_id": self.active_version_id,
            "status": self.status,
            "reasons": self.reasons,
        }
        if self.node_id is not None:
            payload["node_id"] = self.node_id
        if self.creation_version_id is not None:
            payload["creation_version_id"] = self.creation_version_id
        if self.transition_event_id is not None:
            payload["transition_event_id"] = self.transition_event_id
        return payload


@dataclass(frozen=True)
class _AcceptedWorkflowEvent:
    event_type: str
    node_id: str | None
    assignment_id: str | None
    log_index: int


@dataclass(frozen=True)
class ReplayState:
    workflow_id: str
    workflow_version_id: str
    through_event_id: str | None
    through_event_ordinal: int | None
    terminal_complete: bool
    nodes: dict[str, NodeReplayState]
    mutation_proposals: dict[str, MutationReplayState]
    assignment_validity: dict[str, AssignmentVersionValidity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version_id": self.workflow_version_id,
            "through_event_id": self.through_event_id,
            "through_event_ordinal": self.through_event_ordinal,
            "terminal_complete": self.terminal_complete,
            "nodes": {node_id: state.to_dict() for node_id, state in self.nodes.items()},
            "mutation_proposals": {
                event_id: state.to_dict()
                for event_id, state in self.mutation_proposals.items()
            },
            "assignment_validity": {
                assignment_id: validity.to_dict()
                for assignment_id, validity in self.assignment_validity.items()
            },
        }


@dataclass(frozen=True)
class WorkflowVersionState:
    version_id: str
    sequence: int
    content_hash: str
    parent_version_id: str | None
    accepted_event_id: str | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version_id": self.version_id,
            "sequence": self.sequence,
            "content_hash": self.content_hash,
        }
        if self.parent_version_id is not None:
            payload["parent_version_id"] = self.parent_version_id
        if self.accepted_event_id is not None:
            payload["accepted_event_id"] = self.accepted_event_id
        return payload


@dataclass(frozen=True)
class EventWorkflowVersion:
    event_id: str
    event_ordinal: int
    workflow_version_id: str
    workflow_version_before: str
    workflow_version_after: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_ordinal": self.event_ordinal,
            "workflow_version_id": self.workflow_version_id,
            "workflow_version_before": self.workflow_version_before,
            "workflow_version_after": self.workflow_version_after,
        }


@dataclass(frozen=True)
class WorkflowVersionProjection:
    initial_version_id: str
    current_version_id: str
    versions: list[WorkflowVersionState]
    events: list[EventWorkflowVersion]

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_version_id": self.initial_version_id,
            "current_version_id": self.current_version_id,
            "versions": [version.to_dict() for version in self.versions],
            "events": [event.to_dict() for event in self.events],
        }


def project_workflow_versions(
    initial_workflow: Workflow,
    ledger: Ledger,
) -> WorkflowVersionProjection:
    initial_hash = workflow_content_hash(initial_workflow)
    initial_id = workflow_version_identity(initial_workflow, 0)
    versions = [
        WorkflowVersionState(
            version_id=initial_id,
            sequence=0,
            content_hash=initial_hash,
            parent_version_id=None,
            accepted_event_id=None,
        )
    ]
    events: list[EventWorkflowVersion] = []
    current_workflow = initial_workflow
    current_version = initial_id
    sequence = 0

    for index, event in enumerate(ledger.event_log):
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ProtocolError("Workflow version projection requires event_id")
        before_version = current_version
        after_version = before_version
        if event.get("event_type") == "workflow_mutation_accepted":
            prefix = replace(ledger, event_log=ledger.event_log[: index + 1])
            next_workflow = materialize_current_workflow(initial_workflow, prefix)
            next_sequence = sequence + 1
            after_version = workflow_version_identity(next_workflow, next_sequence)
            _validate_recorded_workflow_transition(
                event,
                before_workflow=current_workflow,
                after_workflow=next_workflow,
                before_version=before_version,
                after_version=after_version,
            )
            versions.append(
                WorkflowVersionState(
                    version_id=after_version,
                    sequence=next_sequence,
                    content_hash=workflow_content_hash(next_workflow),
                    parent_version_id=before_version,
                    accepted_event_id=event_id,
                )
            )
            current_workflow = next_workflow
            current_version = after_version
            sequence = next_sequence
        events.append(
            EventWorkflowVersion(
                event_id=event_id,
                event_ordinal=index,
                workflow_version_id=after_version,
                workflow_version_before=before_version,
                workflow_version_after=after_version,
            )
        )

    return WorkflowVersionProjection(
        initial_version_id=initial_id,
        current_version_id=current_version,
        versions=versions,
        events=events,
    )


def _validate_recorded_workflow_transition(
    event: dict[str, Any],
    *,
    before_workflow: Workflow,
    after_workflow: Workflow,
    before_version: str,
    after_version: str,
) -> None:
    expected = {
        "workflow_version_before": before_version,
        "workflow_version_after": after_version,
        "workflow_hash_before": workflow_content_hash(before_workflow),
        "workflow_hash_after": workflow_content_hash(after_workflow),
        "parent_workflow_version_id": before_version,
    }
    for field, value in expected.items():
        recorded = event.get(field)
        if recorded is not None and recorded != value:
            raise ProtocolError(
                f"Recorded workflow transition {field} does not match replay"
            )


def replay_workflow(
    initial_workflow: Workflow,
    ledger: Ledger,
    *,
    through_event_id: str | None = None,
    through_event_ordinal: int | None = None,
) -> ReplayState:
    ledger = select_ledger_prefix(
        ledger,
        through_event_id=through_event_id,
        through_event_ordinal=through_event_ordinal,
    )
    workflow = materialize_current_workflow(initial_workflow, ledger)
    version_projection = project_workflow_versions(initial_workflow, ledger)
    assignment_validity = _derive_assignment_version_validity(
        initial_workflow, ledger, version_projection
    )
    assignment_attempts = _assignment_attempts_by_node(workflow, ledger)
    mutation_proposals = _derive_mutation_proposals(workflow, ledger)
    pending_mutations_by_node = _pending_mutations_by_node(mutation_proposals)
    review_blocks_by_node = _mutation_review_blocks_by_node(
        initial_workflow, ledger
    )
    circuit_blocks_by_node = _retry_circuit_blocks_by_node(ledger)
    nodes = {
        node_id: _replay_node(
            workflow,
            ledger,
            node,
            assignment_attempts.get(node_id, []),
            pending_mutations_by_node.get(node_id, []),
            [
                *review_blocks_by_node.get(node_id, []),
                *circuit_blocks_by_node.get(node_id, []),
            ],
        )
        for node_id, node in workflow.nodes.items()
    }
    terminal_complete = _refs_satisfied(workflow.terminal_events, [], ledger)[0]
    return ReplayState(
        workflow_id=workflow.workflow_id,
        workflow_version_id=version_projection.current_version_id,
        through_event_id=(
            ledger.event_log[-1].get("event_id") if ledger.event_log else None
        ),
        through_event_ordinal=(len(ledger.event_log) - 1 if ledger.event_log else None),
        terminal_complete=terminal_complete,
        nodes=nodes,
        mutation_proposals=mutation_proposals,
        assignment_validity=assignment_validity,
    )


def select_ledger_prefix(
    ledger: Ledger,
    *,
    through_event_id: str | None = None,
    through_event_ordinal: int | None = None,
) -> Ledger:
    if through_event_id is not None and through_event_ordinal is not None:
        raise ProtocolError(
            "Specify either through_event_id or through_event_ordinal, not both"
        )
    if through_event_id is None and through_event_ordinal is None:
        return ledger

    if through_event_id is not None:
        if not through_event_id:
            raise ProtocolError("through_event_id must be a non-empty string")
        index = next(
            (
                position
                for position, event in enumerate(ledger.event_log)
                if event.get("event_id") == through_event_id
            ),
            None,
        )
        if index is None:
            raise ProtocolError(f"Unknown through_event_id: {through_event_id}")
    else:
        if (
            isinstance(through_event_ordinal, bool)
            or not isinstance(through_event_ordinal, int)
            or through_event_ordinal < 0
            or through_event_ordinal >= len(ledger.event_log)
        ):
            raise ProtocolError(
                f"Unknown through_event_ordinal: {through_event_ordinal}"
            )
        index = through_event_ordinal

    return rebuild_ledger_projection(
        replace(ledger, event_log=ledger.event_log[: index + 1])
    )


def evaluate_assignment_impacts(
    before: Workflow,
    after: Workflow,
    ledger: Ledger,
    applied_changes: dict[str, Any] | None = None,
) -> dict[str, AssignmentImpact]:
    assignment_nodes = _assignment_node_sets(ledger)
    explicit_superseded = set()
    if applied_changes is not None:
        raw_superseded = applied_changes.get("supersede_assignments", [])
        if isinstance(raw_superseded, list):
            explicit_superseded = {
                item for item in raw_superseded if isinstance(item, str) and item
            }
            for assignment_id in explicit_superseded:
                assignment_nodes.setdefault(assignment_id, set())

    before_ancestors = _ancestor_sets(before)
    after_ancestors = _ancestor_sets(after)
    impacts: dict[str, AssignmentImpact] = {}
    for assignment_id in sorted(assignment_nodes):
        node_ids = assignment_nodes[assignment_id]
        if len(node_ids) != 1:
            reason = (
                "assignment_node_missing"
                if not node_ids
                else "assignment_node_conflict"
            )
            impacts[assignment_id] = AssignmentImpact(
                assignment_id=assignment_id,
                node_id=None,
                classification="needs_review",
                reasons=[reason],
            )
            continue

        node_id = next(iter(node_ids))
        if assignment_id in explicit_superseded:
            impacts[assignment_id] = AssignmentImpact(
                assignment_id=assignment_id,
                node_id=node_id,
                classification="affected",
                reasons=["explicitly_superseded"],
            )
            continue
        before_node = before.nodes.get(node_id)
        after_node = after.nodes.get(node_id)
        if before_node is None or after_node is None:
            impacts[assignment_id] = AssignmentImpact(
                assignment_id=assignment_id,
                node_id=node_id,
                classification="needs_review",
                reasons=["node_missing_from_workflow_version"],
            )
            continue

        reasons: list[str] = []
        if _node_contract(before_node) != _node_contract(after_node):
            reasons.append("node_contract_changed")
        if before_ancestors.get(node_id, set()) != after_ancestors.get(node_id, set()):
            reasons.append("dependency_closure_changed")
        impacts[assignment_id] = AssignmentImpact(
            assignment_id=assignment_id,
            node_id=node_id,
            classification="affected" if reasons else "unaffected",
            reasons=reasons or ["execution_context_unchanged"],
        )
    return impacts


def build_mutation_supersession_events(
    workflow: Workflow,
    accepted_event: dict[str, Any],
    impacts: dict[str, AssignmentImpact],
) -> list[dict[str, Any]]:
    if accepted_event.get("event_type") != "workflow_mutation_accepted":
        raise ValueError("Supersession events require workflow_mutation_accepted")
    mutation_event_id = _string_or_none(accepted_event.get("event_id"))
    if mutation_event_id is None:
        raise ValueError("Accepted mutation event requires event_id")

    events: list[dict[str, Any]] = []
    for assignment_id, impact in sorted(impacts.items()):
        if impact.classification != "affected" or impact.node_id is None:
            continue
        payload: dict[str, Any] = {
            "event_id": f"event-{mutation_event_id}-supersede-{assignment_id}",
            "event_type": "assignment_superseded",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": assignment_id,
            "node_id": impact.node_id,
            "source_event_id": mutation_event_id,
            "mutation_event_id": mutation_event_id,
            "superseded_by": mutation_event_id,
            "impact_reasons": impact.reasons,
        }
        created_at = _string_or_none(accepted_event.get("created_at"))
        if created_at is not None:
            payload["created_at"] = created_at
        events.append(payload)
    return events


def _replay_node(
    workflow: Workflow,
    ledger: Ledger,
    node: WorkflowNode,
    assignment_attempts: list[AssignmentAttemptState],
    pending_mutations: list[MutationReplayState],
    review_blocks: list[BlockedReason],
) -> NodeReplayState:
    emitted_events = [
        event_name
        for event_name in node.emits
        if _event_ref_satisfied(f"{node.id}.{event_name}", ledger)
    ]
    if emitted_events and not review_blocks:
        return NodeReplayState(
            node_id=node.id,
            state="completed",
            emitted_events=emitted_events,
            blocked_reasons=[],
            assignment_attempts=assignment_attempts,
        )

    blocked_reasons: list[BlockedReason] = list(review_blocks)
    blocked_reasons.extend(
        BlockedReason(
            code="mutation_pending",
            message=(
                f"Workflow mutation {mutation.proposal_id} may invalidate "
                f"node {node.id}"
            ),
            mutation_event_id=mutation.proposal_event_id,
        )
        for mutation in pending_mutations
    )
    waits_satisfied, missing_waits = _refs_satisfied(
        node.waits_for_all,
        node.waits_for_any,
        ledger,
    )
    if not waits_satisfied:
        blocked_reasons.extend(
            _missing_event_reason(event_ref, ledger) for event_ref in missing_waits
        )

    active_assignments = [attempt for attempt in assignment_attempts if attempt.state == "in_flight"]
    blocked_reasons.extend(
        BlockedReason(
            code="assignment_in_flight",
            message=f"Assignment {attempt.assignment_id} is already in flight",
            assignment_id=attempt.assignment_id,
        )
        for attempt in active_assignments
    )
    awaiting_acceptance = [
        attempt
        for attempt in assignment_attempts
        if attempt.state == "awaiting_acceptance"
    ]
    blocked_reasons.extend(
        BlockedReason(
            code="awaiting_acceptance",
            message=f"Assignment {attempt.assignment_id} is awaiting outcome acceptance",
            assignment_id=attempt.assignment_id,
        )
        for attempt in awaiting_acceptance
    )
    awaiting_context = [
        attempt for attempt in assignment_attempts if attempt.state == "awaiting_context"
    ]
    blocked_reasons.extend(
        BlockedReason(
            code="awaiting_context",
            message=f"Assignment {attempt.assignment_id} is awaiting bounded context",
            assignment_id=attempt.assignment_id,
        )
        for attempt in awaiting_context
    )
    context_blocked = [
        attempt for attempt in assignment_attempts if attempt.state == "context_blocked"
    ]
    blocked_reasons.extend(
        BlockedReason(
            code="context_unresolved",
            message=f"Assignment {attempt.assignment_id} context request did not resume",
            assignment_id=attempt.assignment_id,
        )
        for attempt in context_blocked
    )
    retry_scheduled = [
        attempt for attempt in assignment_attempts if attempt.state == "retry_scheduled"
    ]
    blocked_reasons.extend(
        BlockedReason(
            code="retry_scheduled",
            message=f"Retry attempt {attempt.assignment_id} is scheduled",
            assignment_id=attempt.assignment_id,
        )
        for attempt in retry_scheduled
    )
    retried_attempt_ids = {
        attempt.retry_of
        for attempt in assignment_attempts
        if attempt.retry_of is not None
    }
    rejected_attempts = [
        attempt
        for attempt in assignment_attempts
        if attempt.state == "rejected"
        and attempt.assignment_id not in retried_attempt_ids
    ]
    blocked_reasons.extend(
        BlockedReason(
            code="outcome_rejected",
            message=(
                f"Assignment {attempt.assignment_id} outcome was rejected and "
                "requires an explicit retry or escalation decision"
            ),
            assignment_id=attempt.assignment_id,
        )
        for attempt in rejected_attempts
    )

    for gate in workflow.gates:
        if gate.node_id != node.id:
            continue
        if _gate_expired(gate, ledger):
            blocked_reasons.append(
                BlockedReason(
                    code="gate_expired",
                    message=f"Gate {gate.id} has expired",
                    gate_id=gate.id,
                )
            )
            continue
        gate_satisfied, missing_gate_refs = _gate_satisfied(gate, ledger)
        if gate_satisfied:
            continue
        for event_ref in missing_gate_refs:
            reason = _missing_event_reason(event_ref, ledger)
            blocked_reasons.append(
                BlockedReason(
                    code=(
                        "superseded"
                        if reason.code == "superseded"
                        else "gate_waiting"
                    ),
                    message=(
                        reason.message
                        if reason.code == "superseded"
                        else f"Gate {gate.id} is waiting for {event_ref}"
                    ),
                    missing_ref=event_ref,
                    gate_id=gate.id,
                    assignment_id=reason.assignment_id,
                )
            )

    return NodeReplayState(
        node_id=node.id,
        state="blocked" if blocked_reasons else "runnable",
        emitted_events=[],
        blocked_reasons=blocked_reasons,
        assignment_attempts=assignment_attempts,
    )


def _derive_mutation_proposals(
    workflow: Workflow,
    ledger: Ledger,
) -> dict[str, MutationReplayState]:
    decisions = {
        event.get("source_event_id"): event
        for event in ledger.event_log
        if event.get("event_type")
        in {"workflow_mutation_accepted", "workflow_mutation_rejected"}
        and isinstance(event.get("source_event_id"), str)
    }
    result: dict[str, MutationReplayState] = {}
    for event in ledger.event_log:
        if event.get("event_type") != "workflow_mutation_proposed":
            continue
        event_id = _string_or_none(event.get("event_id"))
        proposal = event.get("mutation_proposal")
        if event_id is None or not isinstance(proposal, dict):
            continue
        proposal_id = _string_or_none(proposal.get("proposal_id"))
        if proposal_id is None:
            continue
        decision = decisions.get(event_id)
        decision_type = decision.get("event_type") if decision is not None else None
        if decision_type == "workflow_mutation_accepted":
            state: MutationDecisionStatus = "accepted"
        elif decision_type == "workflow_mutation_rejected":
            state = "rejected"
        else:
            state = "pending"
        changes = mutation_proposed_changes(proposal)
        impact_proposal = {"proposed_changes": changes} if changes is not None else {}
        if state == "accepted" and decision is not None:
            applied_changes = decision.get("applied_changes")
            if isinstance(applied_changes, dict):
                impact_proposal = {"proposed_changes": applied_changes}
        result[event_id] = MutationReplayState(
            proposal_id=proposal_id,
            proposal_event_id=event_id,
            state=state,
            affected_node_ids=_affected_nodes_for_proposal(
                workflow, ledger, impact_proposal
            ),
            decision_event_id=(
                _string_or_none(decision.get("event_id"))
                if decision is not None
                else None
            ),
        )
    return result


def _pending_mutations_by_node(
    mutations: dict[str, MutationReplayState],
) -> dict[str, list[MutationReplayState]]:
    result: dict[str, list[MutationReplayState]] = {}
    for mutation in mutations.values():
        if mutation.state != "pending":
            continue
        for node_id in mutation.affected_node_ids:
            result.setdefault(node_id, []).append(mutation)
    return result


def _mutation_review_blocks_by_node(
    initial_workflow: Workflow,
    ledger: Ledger,
) -> dict[str, list[BlockedReason]]:
    result: dict[str, list[BlockedReason]] = {}
    prefix_events: list[dict[str, Any]] = []
    before = initial_workflow
    for event in ledger.event_log:
        prefix_events.append(event)
        if event.get("event_type") != "workflow_mutation_accepted":
            continue
        prefix_ledger = replace(ledger, event_log=list(prefix_events))
        after = materialize_current_workflow(initial_workflow, prefix_ledger)
        applied_changes = event.get("applied_changes")
        impacts = evaluate_assignment_impacts(
            before,
            after,
            prefix_ledger,
            applied_changes if isinstance(applied_changes, dict) else None,
        )
        mutation_event_id = _string_or_none(event.get("event_id"))
        for impact in impacts.values():
            if impact.classification not in {"affected", "needs_review"} or impact.node_id is None:
                continue
            if impact.node_id not in after.nodes:
                continue
            result.setdefault(impact.node_id, []).append(
                BlockedReason(
                    code=(
                        "superseded"
                        if impact.classification == "affected"
                        else "needs_review"
                    ),
                    message=(
                        f"Assignment {impact.assignment_id} is "
                        f"{impact.classification} after workflow mutation"
                    ),
                    assignment_id=impact.assignment_id,
                    mutation_event_id=mutation_event_id,
                )
            )
        before = after
    return result


def _derive_assignment_version_validity(
    initial_workflow: Workflow,
    ledger: Ledger,
    projection: WorkflowVersionProjection,
) -> dict[str, AssignmentVersionValidity]:
    event_versions = {
        event.event_id: event.workflow_version_id for event in projection.events
    }
    validity: dict[str, AssignmentVersionValidity] = {}
    for event in ledger.event_log:
        if event.get("event_type") != "assignment_created":
            continue
        assignment_id = _string_or_none(event.get("assignment_id"))
        event_id = _string_or_none(event.get("event_id"))
        if assignment_id is None:
            continue
        recorded_version = _string_or_none(event.get("workflow_version_id"))
        validity[assignment_id] = AssignmentVersionValidity(
            assignment_id=assignment_id,
            node_id=_string_or_none(event.get("node_id")),
            creation_version_id=recorded_version or event_versions.get(event_id or ""),
            active_version_id=projection.current_version_id,
            status="unaffected",
            reasons=["valid_in_active_workflow_version"],
            transition_event_id=None,
        )

    before = initial_workflow
    for index, event in enumerate(ledger.event_log):
        if event.get("event_type") != "workflow_mutation_accepted":
            continue
        prefix = replace(ledger, event_log=ledger.event_log[: index + 1])
        after = materialize_current_workflow(initial_workflow, prefix)
        changes = event.get("applied_changes")
        impacts = evaluate_assignment_impacts(
            before,
            after,
            prefix,
            changes if isinstance(changes, dict) else None,
        )
        transition_id = _string_or_none(event.get("event_id"))
        for assignment_id, impact in impacts.items():
            current = validity.get(assignment_id)
            if current is None or impact.classification == "unaffected":
                continue
            validity[assignment_id] = replace(
                current,
                status=impact.classification,
                reasons=impact.reasons,
                transition_event_id=transition_id,
            )
        before = after

    for event in ledger.event_log:
        if event.get("event_type") != "assignment_superseded":
            continue
        assignment_id = _string_or_none(event.get("assignment_id"))
        current = validity.get(assignment_id or "")
        if current is not None:
            validity[current.assignment_id] = replace(
                current,
                status="affected",
                reasons=["explicitly_superseded"],
                transition_event_id=(
                    _string_or_none(event.get("mutation_event_id"))
                    or _string_or_none(event.get("event_id"))
                ),
            )
    return validity


def _retry_circuit_blocks_by_node(
    ledger: Ledger,
) -> dict[str, list[BlockedReason]]:
    result: dict[str, list[BlockedReason]] = {}
    for index, event in enumerate(ledger.event_log):
        if event.get("event_type") != "assignment_circuit_opened":
            continue
        node_id = _string_or_none(event.get("node_id"))
        terminal_state = _string_or_none(event.get("terminal_state"))
        assignment_id = _string_or_none(event.get("assignment_id"))
        if node_id is None or terminal_state not in {"needs_review", "needs_replan"}:
            continue
        if any(
            later.get("event_type") == "assignment_created"
            and later.get("node_id") == node_id
            and later.get("assignment_id") != assignment_id
            for later in ledger.event_log[index + 1 :]
        ):
            continue
        result.setdefault(node_id, []).append(
            BlockedReason(
                code=terminal_state,
                message=(
                    f"Assignment {assignment_id or 'unknown'} retry circuit is open: "
                    f"{event.get('reason', 'retry stopped')}"
                ),
                assignment_id=assignment_id,
            )
        )
    return result


def _affected_nodes_for_proposal(
    workflow: Workflow,
    ledger: Ledger,
    proposal: dict[str, Any],
) -> list[str]:
    changes = proposal.get("proposed_changes")
    if not isinstance(changes, dict):
        return []

    direct: set[str] = set()
    for field in ("add_edges", "remove_edges"):
        edges = changes.get(field, [])
        if not isinstance(edges, list):
            continue
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            to_node = _string_or_none(edge.get("to_node"))
            if to_node in workflow.nodes:
                direct.add(to_node)

    superseded = changes.get("supersede_assignments", [])
    if isinstance(superseded, list):
        assignment_nodes = _assignment_node_index(ledger)
        direct.update(
            assignment_nodes[assignment_id]
            for assignment_id in superseded
            if isinstance(assignment_id, str)
            and assignment_id in assignment_nodes
        )

    added_nodes = changes.get("add_nodes", [])
    if isinstance(added_nodes, list):
        direct.update(
            node_id
            for raw_node in added_nodes
            if isinstance(raw_node, dict)
            and (node_id := _string_or_none(raw_node.get("id"))) in workflow.nodes
        )

    return sorted(_downstream_closure(workflow, direct))


def _assignment_node_index(ledger: Ledger) -> dict[str, str]:
    result: dict[str, str] = {}
    for event in ledger.event_log:
        assignment_id = _string_or_none(event.get("assignment_id"))
        node_id = _string_or_none(event.get("node_id"))
        if assignment_id is not None and node_id is not None:
            result.setdefault(assignment_id, node_id)
    return result


def _assignment_node_sets(ledger: Ledger) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for event in ledger.event_log:
        assignment_id = _string_or_none(event.get("assignment_id"))
        if assignment_id is None:
            continue
        node_id = _string_or_none(event.get("node_id"))
        result.setdefault(assignment_id, set())
        if node_id is not None:
            result[assignment_id].add(node_id)
    return result


def _downstream_closure(workflow: Workflow, roots: set[str]) -> set[str]:
    adjacency = _dependency_adjacency(workflow)
    affected = set(roots)
    pending = list(roots)
    while pending:
        node_id = pending.pop()
        for downstream in adjacency.get(node_id, set()):
            if downstream not in affected:
                affected.add(downstream)
                pending.append(downstream)
    return affected


def _dependency_adjacency(workflow: Workflow) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in workflow.nodes}
    emitters: dict[str, set[str]] = {}
    for node in workflow.nodes.values():
        for event_name in node.emits:
            emitters.setdefault(event_name, set()).add(node.id)
    for consumer in workflow.nodes.values():
        for event_ref in consumer.waits_for:
            if "." in event_ref:
                producer, _ = event_ref.split(".", 1)
                producers = {producer}
            else:
                producers = emitters.get(event_ref, set())
            for producer in producers:
                if producer in adjacency:
                    adjacency[producer].add(consumer.id)
    return adjacency


def _ancestor_sets(workflow: Workflow) -> dict[str, set[str]]:
    adjacency = _dependency_adjacency(workflow)
    reverse: dict[str, set[str]] = {node_id: set() for node_id in workflow.nodes}
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].add(source)

    result: dict[str, set[str]] = {}
    for node_id in workflow.nodes:
        ancestors: set[str] = set()
        pending = list(reverse[node_id])
        while pending:
            ancestor = pending.pop()
            if ancestor in ancestors:
                continue
            ancestors.add(ancestor)
            pending.extend(reverse.get(ancestor, set()))
        result[node_id] = ancestors
    return result


def _node_contract(node: WorkflowNode) -> tuple[Any, ...]:
    return (
        node.role,
        tuple(sorted(node.emits)),
        tuple(sorted(node.waits_for_all)),
        tuple(sorted(node.waits_for_any)),
    )


def _assignment_attempts_by_node(
    workflow: Workflow,
    ledger: Ledger,
) -> dict[str, list[AssignmentAttemptState]]:
    attempts = _derive_assignment_attempts(workflow, ledger)
    grouped: dict[str, list[AssignmentAttemptState]] = {
        node_id: []
        for node_id in workflow.nodes
    }
    for attempt in attempts:
        grouped.setdefault(attempt.node_id, []).append(attempt)
    return grouped


def _derive_assignment_attempts(
    workflow: Workflow,
    ledger: Ledger,
) -> list[AssignmentAttemptState]:
    terminal_status_by_event = {
        "worker_timeout": "timed_out",
        "assignment_cancelled": "cancelled",
        "assignment_superseded": "superseded",
    }
    raw_attempts: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    accepted_events_by_index = _accepted_workflow_events_by_log_index(ledger)

    for index, event in enumerate(ledger.event_log):
        event_type = event.get("event_type")
        assignment_id = _string_or_none(event.get("assignment_id"))
        if assignment_id is None:
            for accepted_event in accepted_events_by_index.get(index, []):
                _mark_assignment_completed(workflow, raw_attempts, accepted_event)
            continue

        if event_type == "assignment_created":
            node_id = _string_or_none(event.get("node_id"))
            if node_id is None:
                for accepted_event in accepted_events_by_index.get(index, []):
                    _mark_assignment_completed(workflow, raw_attempts, accepted_event)
                continue
            existing_retry_of = (
                raw_attempts[assignment_id].get("retry_of")
                if assignment_id in raw_attempts
                else None
            )
            raw_attempts[assignment_id] = {
                "assignment_id": assignment_id,
                "node_id": node_id,
                "state": "in_flight",
                "created_event_id": _string_or_none(event.get("event_id")),
                "terminal_event_id": None,
                "terminal_event_type": None,
                "retry_of": existing_retry_of,
                "superseded_by": None,
            }
            order.append(assignment_id)
            for accepted_event in accepted_events_by_index.get(index, []):
                _mark_assignment_completed(workflow, raw_attempts, accepted_event)
            continue

        if event_type == "assignment_retry_scheduled":
            node_id = _string_or_none(event.get("node_id"))
            retry_of = _string_or_none(event.get("retry_of"))
            prior = raw_attempts.get(retry_of) if retry_of is not None else None
            if prior is not None:
                prior["state"] = "rejected"
                prior["terminal_event_id"] = _string_or_none(event.get("event_id"))
                prior["terminal_event_type"] = event_type
            if node_id is not None:
                raw_attempts[assignment_id] = {
                    "assignment_id": assignment_id,
                    "node_id": node_id,
                    "state": "retry_scheduled",
                    "created_event_id": _string_or_none(event.get("event_id")),
                    "terminal_event_id": None,
                    "terminal_event_type": None,
                    "retry_of": retry_of,
                    "superseded_by": None,
                }
                order.append(assignment_id)
            continue

        if event_type == "assignment_circuit_opened":
            attempt = raw_attempts.get(assignment_id)
            if attempt is not None:
                attempt["state"] = "rejected"
                attempt["terminal_event_id"] = _string_or_none(event.get("event_id"))
                attempt["terminal_event_type"] = event_type
            continue

        if event_type == "assignment_retry_requested":
            node_id = _string_or_none(event.get("node_id"))
            if assignment_id not in raw_attempts and node_id is not None:
                raw_attempts[assignment_id] = {
                    "assignment_id": assignment_id,
                    "node_id": node_id,
                    "state": "in_flight",
                    "created_event_id": None,
                    "terminal_event_id": None,
                    "terminal_event_type": None,
                    "retry_of": _string_or_none(event.get("retry_of")),
                    "superseded_by": None,
                }
                order.append(assignment_id)
            attempt = raw_attempts.get(assignment_id)
            if attempt is not None:
                attempt["retry_of"] = _string_or_none(event.get("retry_of"))
            for accepted_event in accepted_events_by_index.get(index, []):
                _mark_assignment_completed(workflow, raw_attempts, accepted_event)
            continue

        attempt = raw_attempts.get(assignment_id)
        if attempt is None:
            node_id = _string_or_none(event.get("node_id"))
            if node_id is None:
                continue
            raw_attempts[assignment_id] = {
                "assignment_id": assignment_id,
                "node_id": node_id,
                "state": "in_flight",
                "created_event_id": None,
                "terminal_event_id": None,
                "terminal_event_type": None,
                "retry_of": None,
                "superseded_by": None,
            }
            order.append(assignment_id)
            attempt = raw_attempts[assignment_id]

        if event_type in terminal_status_by_event:
            attempt["state"] = terminal_status_by_event[event_type]
            attempt["terminal_event_id"] = _string_or_none(event.get("event_id"))
            attempt["terminal_event_type"] = event_type
            if event_type == "assignment_superseded":
                attempt["superseded_by"] = _string_or_none(event.get("superseded_by"))
        elif event_type == "context_requested":
            attempt["state"] = "awaiting_context"
            attempt["terminal_event_id"] = _string_or_none(event.get("event_id"))
            attempt["terminal_event_type"] = event_type
        elif event_type == "context_resolved":
            attempt["state"] = (
                "awaiting_context"
                if event.get("status") in {"granted", "partially_granted"}
                else "context_blocked"
            )
            attempt["terminal_event_id"] = _string_or_none(event.get("event_id"))
            attempt["terminal_event_type"] = event_type
        elif event_type == "context_resumed":
            attempt["state"] = "in_flight"
            attempt["terminal_event_id"] = None
            attempt["terminal_event_type"] = None
        elif (
            ledger.ledger_version >= STRICT_ACCEPTANCE_LEDGER_VERSION
            and event_type == "result_submitted"
        ):
            attempt["state"] = "awaiting_acceptance"
            attempt["terminal_event_id"] = _string_or_none(event.get("event_id"))
            attempt["terminal_event_type"] = event_type
        elif (
            ledger.ledger_version >= STRICT_ACCEPTANCE_LEDGER_VERSION
            and event_type == "node_outcome_decided"
        ):
            disposition = event.get("disposition")
            attempt["state"] = (
                "completed"
                if disposition in {"accepted", "partially_accepted"}
                else "rejected"
            )
            attempt["terminal_event_id"] = _string_or_none(event.get("event_id"))
            attempt["terminal_event_type"] = event_type
        for accepted_event in accepted_events_by_index.get(index, []):
            _mark_assignment_completed(workflow, raw_attempts, accepted_event)

    return [
        AssignmentAttemptState(
            assignment_id=raw_attempts[assignment_id]["assignment_id"],
            node_id=raw_attempts[assignment_id]["node_id"],
            state=raw_attempts[assignment_id]["state"],
            created_event_id=raw_attempts[assignment_id]["created_event_id"],
            terminal_event_id=raw_attempts[assignment_id]["terminal_event_id"],
            terminal_event_type=raw_attempts[assignment_id]["terminal_event_type"],
            retry_of=raw_attempts[assignment_id]["retry_of"],
            superseded_by=raw_attempts[assignment_id]["superseded_by"],
        )
        for assignment_id in order
    ]


def _mark_assignment_completed(
    workflow: Workflow,
    raw_attempts: dict[str, dict[str, Any]],
    event: _AcceptedWorkflowEvent,
) -> None:
    assignment_id = event.assignment_id
    if assignment_id is None:
        return
    attempt = raw_attempts.get(assignment_id)
    if attempt is None:
        return
    if not _workflow_event_completes_assignment(workflow, attempt["node_id"], event):
        return
    attempt["state"] = "completed"
    attempt["terminal_event_type"] = event.event_type


def _workflow_event_completes_assignment(
    workflow: Workflow,
    node_id: str,
    event: _AcceptedWorkflowEvent,
) -> bool:
    if event.event_type not in workflow.events:
        return False
    node = workflow.nodes.get(node_id)
    if node is None:
        return False
    if event.event_type not in node.emits:
        return False
    return event.node_id in {None, node_id}


def _gate_satisfied(gate: WorkflowGate, ledger: Ledger) -> tuple[bool, list[str]]:
    return _refs_satisfied(gate.requires_all, gate.requires_any, ledger)


def _gate_expired(gate: WorkflowGate, ledger: Ledger) -> bool:
    return any(
        event.get("event_type") == "gate_expired"
        and event.get("gate_id") == gate.id
        for event in ledger.event_log
    )


def _refs_satisfied(
    all_of: list[str],
    any_of: list[str],
    ledger: Ledger,
) -> tuple[bool, list[str]]:
    missing = [event_ref for event_ref in all_of if not _event_ref_satisfied(event_ref, ledger)]
    any_satisfied = not any_of or any(_event_ref_satisfied(event_ref, ledger) for event_ref in any_of)
    if any_of and not any_satisfied:
        missing.extend(any_of)
    return not missing and any_satisfied, missing


def _event_ref_satisfied(event_ref: str, ledger: Ledger) -> bool:
    if "." in event_ref:
        node_id, event_type = event_ref.split(".", 1)
    else:
        node_id, event_type = None, event_ref

    superseded_assignments = {
        event.get("assignment_id")
        for event in ledger.event_log
        if event.get("event_type") == "assignment_superseded"
        and isinstance(event.get("assignment_id"), str)
    }
    for event in _accepted_workflow_events(ledger):
        if event.event_type != event_type:
            continue
        if node_id is not None and event.node_id != node_id:
            continue
        if event.assignment_id in superseded_assignments:
            continue
        return True
    return False


def _accepted_workflow_events(
    ledger: Ledger,
) -> list[_AcceptedWorkflowEvent]:
    events_by_index = _accepted_workflow_events_by_log_index(ledger)
    return [
        event
        for index in sorted(events_by_index)
        for event in events_by_index[index]
    ]


def _accepted_workflow_events_by_log_index(
    ledger: Ledger,
) -> dict[int, list[_AcceptedWorkflowEvent]]:
    strict = ledger.ledger_version >= STRICT_ACCEPTANCE_LEDGER_VERSION
    decisions_by_assignment: dict[str, dict[str, Any]] = {}
    for event in ledger.event_log:
        if event.get("event_type") != "node_outcome_decided":
            continue
        assignment_id = _string_or_none(event.get("assignment_id"))
        if assignment_id is None:
            continue
        decisions_by_assignment[assignment_id] = event

    raw_workflow_keys: set[tuple[str | None, str | None, str]] = set()
    accepted_by_index: dict[int, list[_AcceptedWorkflowEvent]] = {}
    for index, event in enumerate(ledger.event_log):
        event_type = _string_or_none(event.get("event_type"))
        if event_type is None:
            continue
        assignment_id = _string_or_none(event.get("assignment_id"))
        node_id = _string_or_none(event.get("node_id"))
        if assignment_id is not None and not strict:
            raw_workflow_keys.add((assignment_id, node_id, event_type))
        if not _workflow_event_is_accepted(
            event,
            decisions_by_assignment.get(assignment_id),
            strict=strict,
        ):
            continue
        accepted_by_index.setdefault(index, []).append(
            _AcceptedWorkflowEvent(
                event_type=event_type,
                node_id=node_id,
                assignment_id=assignment_id,
                log_index=index,
            )
        )

    for index, event in enumerate(ledger.event_log):
        if event.get("event_type") != "node_outcome_decided":
            continue
        if event.get("disposition") not in {"accepted", "partially_accepted"}:
            continue
        assignment_id = _string_or_none(event.get("assignment_id"))
        node_id = _string_or_none(event.get("node_id"))
        accepted_event_types = event.get("accepted_event_types", [])
        if assignment_id is None or node_id is None:
            continue
        if not isinstance(accepted_event_types, list):
            continue
        for accepted_event_type in accepted_event_types:
            if not isinstance(accepted_event_type, str) or not accepted_event_type:
                continue
            key = (assignment_id, node_id, accepted_event_type)
            if key in raw_workflow_keys:
                continue
            accepted_by_index.setdefault(index, []).append(
                _AcceptedWorkflowEvent(
                    event_type=accepted_event_type,
                    node_id=node_id,
                    assignment_id=assignment_id,
                    log_index=index,
                )
            )
    return accepted_by_index


def _workflow_event_is_accepted(
    event: dict[str, Any],
    decision: dict[str, Any] | None,
    *,
    strict: bool,
) -> bool:
    event_type = _string_or_none(event.get("event_type"))
    if event_type is None:
        return False
    if strict:
        return False
    if decision is None:
        return True
    if decision.get("disposition") not in {"accepted", "partially_accepted"}:
        return False
    accepted_event_types = decision.get("accepted_event_types", [])
    return (
        isinstance(accepted_event_types, list)
        and event_type in accepted_event_types
    )


def _missing_event_reason(event_ref: str, ledger: Ledger) -> BlockedReason:
    superseded_assignment = _superseded_assignment_for_ref(event_ref, ledger)
    if superseded_assignment is not None:
        return BlockedReason(
            code="superseded",
            message=(
                f"Event {event_ref} was emitted only by superseded assignment "
                f"{superseded_assignment}"
            ),
            missing_ref=event_ref,
            assignment_id=superseded_assignment,
        )
    return BlockedReason(
        code="missing_event",
        message=f"Waiting for event {event_ref}",
        missing_ref=event_ref,
    )


def _superseded_assignment_for_ref(
    event_ref: str,
    ledger: Ledger,
) -> str | None:
    if "." in event_ref:
        node_id, event_type = event_ref.split(".", 1)
    else:
        node_id, event_type = None, event_ref
    superseded_assignments = {
        event.get("assignment_id")
        for event in ledger.event_log
        if event.get("event_type") == "assignment_superseded"
        and isinstance(event.get("assignment_id"), str)
    }
    for event in ledger.event_log:
        assignment_id = event.get("assignment_id")
        if assignment_id not in superseded_assignments:
            continue
        if event.get("event_type") != event_type:
            continue
        if node_id is not None and event.get("node_id") != node_id:
            continue
        return assignment_id
    return None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
