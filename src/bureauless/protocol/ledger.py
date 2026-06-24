from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from ..core import ProtocolError
from .harness import Ledger, Workflow


LIFECYCLE_EVENT_TYPES = {
    "assignment_created",
    "result_submitted",
    "review_approved",
    "review_rejected",
    "worker_timeout",
    "assignment_cancelled",
    "assignment_retry_requested",
    "assignment_superseded",
    "budget_soft_limit_reached",
    "budget_hard_limit_reached",
    "artifact_invalidated",
    "gate_expired",
    "tool_call_failed",
    "partial_result_submitted",
}


def append_ledger_event(
    ledger: Ledger,
    event: dict[str, Any],
    workflow: Workflow | None = None,
) -> Ledger:
    validate_ledger_event(ledger, event, workflow)
    return replace(ledger, event_log=[*ledger.event_log, event])


def validate_ledger_event(
    ledger: Ledger,
    event: dict[str, Any],
    workflow: Workflow | None = None,
) -> None:
    event_id = _required_string(event, "event_id")
    event_type = _required_string(event, "event_type")

    if any(existing.get("event_id") == event_id for existing in ledger.event_log):
        raise ProtocolError(f"Duplicate ledger event id: {event_id}")

    allowed_event_types = set(LIFECYCLE_EVENT_TYPES)
    if workflow is not None:
        allowed_event_types.update(workflow.events)
    if event_type not in allowed_event_types:
        raise ProtocolError(f"Unknown ledger event type: {event_type}")

    mission_id = event.get("mission_id")
    if mission_id is not None and mission_id != ledger.mission_id:
        raise ProtocolError(
            f"Ledger event mission_id {mission_id!r} does not match ledger {ledger.mission_id!r}"
        )

    if workflow is not None:
        workflow_id = event.get("workflow_id")
        if workflow_id is not None and workflow_id != workflow.workflow_id:
            raise ProtocolError(
                f"Ledger event workflow_id {workflow_id!r} does not match workflow {workflow.workflow_id!r}"
            )

        node_id = event.get("node_id")
        if node_id is not None and node_id not in workflow.nodes:
            raise ProtocolError(f"Ledger event references unknown node_id: {node_id}")

        role = event.get("role")
        if role is not None and role not in workflow.roles:
            raise ProtocolError(f"Ledger event references unknown role: {role}")

        if event_type in workflow.events and role is not None:
            allowed_roles = set(workflow.events[event_type].producer_roles)
            if role not in allowed_roles:
                raise ProtocolError(
                    f"Role {role} is not allowed to produce event {event_type}"
                )


def write_ledger(path: Path, ledger: Ledger) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(ledger_to_dict(ledger), handle, sort_keys=False)


def ledger_to_dict(ledger: Ledger) -> dict[str, Any]:
    return {
        "mission_id": ledger.mission_id,
        "ledger_version": ledger.ledger_version,
        "current_goal": ledger.current_goal,
        "current_plan_ref": ledger.current_plan_ref,
        "public_findings": ledger.public_findings,
        "decisions": ledger.decisions,
        "risks": ledger.risks,
        "artifacts": ledger.artifacts,
        "broadcasts": ledger.broadcasts,
        "open_questions": ledger.open_questions,
        "event_log": ledger.event_log,
    }


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Ledger event field {key!r} must be a non-empty string")
    return value
