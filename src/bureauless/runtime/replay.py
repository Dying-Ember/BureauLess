from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..protocol.harness import Ledger, Workflow, WorkflowGate, WorkflowNode


NodeRuntimeState = Literal["runnable", "blocked", "completed"]
AssignmentAttemptStatus = Literal[
    "in_flight",
    "completed",
    "timed_out",
    "cancelled",
    "superseded",
]


@dataclass(frozen=True)
class BlockedReason:
    code: str
    message: str
    missing_ref: str | None = None
    gate_id: str | None = None
    assignment_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.missing_ref is not None:
            payload["missing_ref"] = self.missing_ref
        if self.gate_id is not None:
            payload["gate_id"] = self.gate_id
        if self.assignment_id is not None:
            payload["assignment_id"] = self.assignment_id
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
class ReplayState:
    workflow_id: str
    terminal_complete: bool
    nodes: dict[str, NodeReplayState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "terminal_complete": self.terminal_complete,
            "nodes": {node_id: state.to_dict() for node_id, state in self.nodes.items()},
        }


def replay_workflow(workflow: Workflow, ledger: Ledger) -> ReplayState:
    assignment_attempts = _assignment_attempts_by_node(workflow, ledger)
    nodes = {
        node_id: _replay_node(
            workflow,
            ledger,
            node,
            assignment_attempts.get(node_id, []),
        )
        for node_id, node in workflow.nodes.items()
    }
    terminal_complete = _refs_satisfied(workflow.terminal_events, [], ledger)[0]
    return ReplayState(
        workflow_id=workflow.workflow_id,
        terminal_complete=terminal_complete,
        nodes=nodes,
    )


def _replay_node(
    workflow: Workflow,
    ledger: Ledger,
    node: WorkflowNode,
    assignment_attempts: list[AssignmentAttemptState],
) -> NodeReplayState:
    emitted_events = [
        event_name
        for event_name in node.emits
        if _event_ref_satisfied(f"{node.id}.{event_name}", ledger)
    ]
    if emitted_events:
        return NodeReplayState(
            node_id=node.id,
            state="completed",
            emitted_events=emitted_events,
            blocked_reasons=[],
            assignment_attempts=assignment_attempts,
        )

    blocked_reasons: list[BlockedReason] = []
    waits_satisfied, missing_waits = _refs_satisfied(
        node.waits_for_all,
        node.waits_for_any,
        ledger,
    )
    if not waits_satisfied:
        blocked_reasons.extend(
            BlockedReason(
                code="missing_event",
                message=f"Waiting for event {event_ref}",
                missing_ref=event_ref,
            )
            for event_ref in missing_waits
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
        blocked_reasons.extend(
            BlockedReason(
                code="gate_waiting",
                message=f"Gate {gate.id} is waiting for {event_ref}",
                missing_ref=event_ref,
                gate_id=gate.id,
            )
            for event_ref in missing_gate_refs
        )

    return NodeReplayState(
        node_id=node.id,
        state="blocked" if blocked_reasons else "runnable",
        emitted_events=[],
        blocked_reasons=blocked_reasons,
        assignment_attempts=assignment_attempts,
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

    for event in ledger.event_log:
        event_type = event.get("event_type")
        assignment_id = _string_or_none(event.get("assignment_id"))
        if assignment_id is None:
            continue

        if event_type == "assignment_created":
            node_id = _string_or_none(event.get("node_id"))
            if node_id is None:
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
            continue

        if _event_completes_assignment(workflow, attempt["node_id"], event):
            attempt["state"] = "completed"
            attempt["terminal_event_id"] = _string_or_none(event.get("event_id"))
            attempt["terminal_event_type"] = _string_or_none(event.get("event_type"))

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


def _event_completes_assignment(
    workflow: Workflow,
    node_id: str,
    event: dict[str, Any],
) -> bool:
    event_type = _string_or_none(event.get("event_type"))
    if event_type is None or event_type not in workflow.events:
        return False
    node = workflow.nodes.get(node_id)
    if node is None:
        return False
    if event_type not in node.emits:
        return False
    event_node_id = _string_or_none(event.get("node_id"))
    return event_node_id in {None, node_id}


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

    for event in ledger.event_log:
        if event.get("event_type") != event_type:
            continue
        if node_id is not None and event.get("node_id") != node_id:
            continue
        return True
    return False


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
