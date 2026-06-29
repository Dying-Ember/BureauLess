from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from ..protocol.harness import Ledger, Workflow, WorkflowGate, WorkflowNode
from ..protocol.mutations import materialize_current_workflow


NodeRuntimeState = Literal["runnable", "blocked", "completed"]
AssignmentAttemptStatus = Literal[
    "in_flight",
    "completed",
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
class _AcceptedWorkflowEvent:
    event_type: str
    node_id: str | None
    assignment_id: str | None
    log_index: int


@dataclass(frozen=True)
class ReplayState:
    workflow_id: str
    terminal_complete: bool
    nodes: dict[str, NodeReplayState]
    mutation_proposals: dict[str, MutationReplayState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "terminal_complete": self.terminal_complete,
            "nodes": {node_id: state.to_dict() for node_id, state in self.nodes.items()},
            "mutation_proposals": {
                event_id: state.to_dict()
                for event_id, state in self.mutation_proposals.items()
            },
        }


def replay_workflow(initial_workflow: Workflow, ledger: Ledger) -> ReplayState:
    workflow = materialize_current_workflow(initial_workflow, ledger)
    assignment_attempts = _assignment_attempts_by_node(workflow, ledger)
    mutation_proposals = _derive_mutation_proposals(workflow, ledger)
    pending_mutations_by_node = _pending_mutations_by_node(mutation_proposals)
    review_blocks_by_node = _mutation_review_blocks_by_node(
        initial_workflow, ledger
    )
    nodes = {
        node_id: _replay_node(
            workflow,
            ledger,
            node,
            assignment_attempts.get(node_id, []),
            pending_mutations_by_node.get(node_id, []),
            review_blocks_by_node.get(node_id, []),
        )
        for node_id, node in workflow.nodes.items()
    }
    terminal_complete = _refs_satisfied(workflow.terminal_events, [], ledger)[0]
    return ReplayState(
        workflow_id=workflow.workflow_id,
        terminal_complete=terminal_complete,
        nodes=nodes,
        mutation_proposals=mutation_proposals,
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
        impact_proposal = proposal
        if state == "accepted" and decision is not None:
            applied_changes = decision.get("applied_changes")
            if isinstance(applied_changes, dict):
                impact_proposal = {
                    **proposal,
                    "proposed_changes": applied_changes,
                }
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
            if impact.classification != "needs_review" or impact.node_id is None:
                continue
            if impact.node_id not in after.nodes:
                continue
            result.setdefault(impact.node_id, []).append(
                BlockedReason(
                    code="needs_review",
                    message=(
                        f"Assignment {impact.assignment_id} requires review after "
                        "workflow mutation"
                    ),
                    assignment_id=impact.assignment_id,
                    mutation_event_id=mutation_event_id,
                )
            )
        before = after
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
            raw_attempts[assignment_id] = {
                "assignment_id": assignment_id,
                "node_id": node_id,
                "state": "in_flight",
                "created_event_id": _string_or_none(event.get("event_id")),
                "terminal_event_id": None,
                "terminal_event_type": None,
                "retry_of": None,
                "superseded_by": None,
            }
            order.append(assignment_id)
            for accepted_event in accepted_events_by_index.get(index, []):
                _mark_assignment_completed(workflow, raw_attempts, accepted_event)
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
        if assignment_id is not None:
            raw_workflow_keys.add((assignment_id, node_id, event_type))
        if not _workflow_event_is_accepted(event, decisions_by_assignment.get(assignment_id)):
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
) -> bool:
    event_type = _string_or_none(event.get("event_type"))
    if event_type is None:
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
