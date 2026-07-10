from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol.harness import Ledger, Workflow
from .replay import BlockedReason, replay_workflow


@dataclass(frozen=True)
class GatekeeperNodeDecision:
    node_id: str
    state: str
    blocked_reasons: list[BlockedReason]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "state": self.state,
            "blocked_reasons": [reason.to_dict() for reason in self.blocked_reasons],
        }


@dataclass(frozen=True)
class GatekeeperResult:
    workflow_id: str
    ready: list[str]
    decisions: dict[str, GatekeeperNodeDecision]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "ready": self.ready,
            "decisions": {
                node_id: decision.to_dict()
                for node_id, decision in self.decisions.items()
            },
        }


def evaluate_gatekeeper(
    workflow: Workflow,
    ledger: Ledger,
    *,
    through_event_id: str | None = None,
    through_event_ordinal: int | None = None,
) -> GatekeeperResult:
    replay_state = replay_workflow(
        workflow,
        ledger,
        through_event_id=through_event_id,
        through_event_ordinal=through_event_ordinal,
    )
    decisions = {
        node_id: GatekeeperNodeDecision(
            node_id=node_id,
            state=node_state.state,
            blocked_reasons=node_state.blocked_reasons,
        )
        for node_id, node_state in replay_state.nodes.items()
    }
    ready = sorted(
        node_id
        for node_id, decision in decisions.items()
        if decision.state == "runnable"
    )
    return GatekeeperResult(
        workflow_id=workflow.workflow_id,
        ready=ready,
        decisions=decisions,
    )
