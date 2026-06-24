from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..protocol.harness import Ledger, Workflow, WorkflowGate, WorkflowNode


NodeRuntimeState = Literal["runnable", "blocked", "completed"]


@dataclass(frozen=True)
class BlockedReason:
    code: str
    message: str
    missing_ref: str | None = None
    gate_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.missing_ref is not None:
            payload["missing_ref"] = self.missing_ref
        if self.gate_id is not None:
            payload["gate_id"] = self.gate_id
        return payload


@dataclass(frozen=True)
class NodeReplayState:
    node_id: str
    state: NodeRuntimeState
    emitted_events: list[str]
    blocked_reasons: list[BlockedReason]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "state": self.state,
            "emitted_events": self.emitted_events,
            "blocked_reasons": [reason.to_dict() for reason in self.blocked_reasons],
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
    nodes = {
        node_id: _replay_node(workflow, ledger, node)
        for node_id, node in workflow.nodes.items()
    }
    terminal_complete = _refs_satisfied(workflow.terminal_events, [], ledger)[0]
    return ReplayState(
        workflow_id=workflow.workflow_id,
        terminal_complete=terminal_complete,
        nodes=nodes,
    )


def _replay_node(workflow: Workflow, ledger: Ledger, node: WorkflowNode) -> NodeReplayState:
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
    )


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
