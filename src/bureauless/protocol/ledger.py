from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from ..core import ProtocolError
from .harness import Ledger, Workflow
from .mutations import load_workflow_mutation_proposal


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
    "node_outcome_decided",
    "gate_expired",
    "tool_call_failed",
    "partial_result_submitted",
    "workflow_mutation_proposed",
    "workflow_mutation_accepted",
    "workflow_mutation_rejected",
}

MUTATION_DECISION_EVENT_TYPES = {
    "workflow_mutation_accepted",
    "workflow_mutation_rejected",
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

    if event_type == "workflow_mutation_proposed":
        _validate_mutation_proposed_event(ledger, event, workflow)
    elif event_type in MUTATION_DECISION_EVENT_TYPES:
        _validate_mutation_decision_event(ledger, event, event_type)
    elif event_type == "assignment_superseded":
        _validate_mutation_supersession_event(ledger, event)
    elif event_type == "node_outcome_decided":
        _validate_node_outcome_decision_event(event)

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


def _validate_mutation_proposed_event(
    ledger: Ledger,
    event: dict[str, Any],
    workflow: Workflow | None,
) -> None:
    raw_proposal = event.get("mutation_proposal")
    if not isinstance(raw_proposal, dict):
        raise ProtocolError(
            "workflow_mutation_proposed requires a mutation_proposal object"
        )
    proposal = load_workflow_mutation_proposal(raw_proposal)
    if workflow is not None and proposal.workflow_id != workflow.workflow_id:
        raise ProtocolError(
            "Mutation proposal workflow_id does not match the active workflow"
        )
    for existing in ledger.event_log:
        existing_proposal = existing.get("mutation_proposal")
        if (
            isinstance(existing_proposal, dict)
            and existing_proposal.get("proposal_id") == proposal.proposal_id
        ):
            raise ProtocolError(
                f"Duplicate workflow mutation proposal id: {proposal.proposal_id}"
            )


def _validate_mutation_decision_event(
    ledger: Ledger,
    event: dict[str, Any],
    event_type: str,
) -> None:
    source_event_id = _required_string(event, "source_event_id")
    source_event = next(
        (
            candidate
            for candidate in ledger.event_log
            if candidate.get("event_id") == source_event_id
        ),
        None,
    )
    if source_event is None or source_event.get("event_type") != "workflow_mutation_proposed":
        raise ProtocolError(
            "Mutation decision source_event_id must reference an existing "
            "workflow_mutation_proposed event"
        )

    prior_decision = next(
        (
            candidate
            for candidate in ledger.event_log
            if candidate.get("event_type") in MUTATION_DECISION_EVENT_TYPES
            and candidate.get("source_event_id") == source_event_id
        ),
        None,
    )
    if prior_decision is not None:
        raise ProtocolError(
            f"Mutation proposal event {source_event_id} already has a decision"
        )

    actor = _required_string(event, "actor")
    if actor not in {"orchestrator", "human"}:
        raise ProtocolError("Mutation decisions require orchestrator or human actor")

    if event_type == "workflow_mutation_rejected":
        _required_string(event, "reason")
        return

    applied_changes = event.get("applied_changes")
    if not isinstance(applied_changes, dict):
        raise ProtocolError(
            "workflow_mutation_accepted requires an applied_changes object"
        )
    _validate_applied_changes_subset(source_event, applied_changes)


def _validate_applied_changes_subset(
    source_event: dict[str, Any],
    applied_changes: dict[str, Any],
) -> None:
    proposal = source_event.get("mutation_proposal")
    if not isinstance(proposal, dict):
        raise ProtocolError("Mutation proposal event is missing mutation_proposal")
    proposed_changes = proposal.get("proposed_changes")
    if not isinstance(proposed_changes, dict):
        raise ProtocolError("Mutation proposal is missing proposed_changes")

    allowed_fields = {
        "add_nodes",
        "add_edges",
        "remove_edges",
        "supersede_assignments",
    }
    unknown = sorted(set(applied_changes) - allowed_fields)
    if unknown:
        raise ProtocolError(
            f"Accepted mutation contains unknown applied_changes: {', '.join(unknown)}"
        )

    applied_count = 0
    for field in allowed_fields:
        applied_items = applied_changes.get(field, [])
        proposed_items = proposed_changes.get(field, [])
        if not isinstance(applied_items, list):
            raise ProtocolError(f"applied_changes.{field} must be a list")
        if not isinstance(proposed_items, list):
            raise ProtocolError(f"Proposed mutation field {field} must be a list")
        applied_count += len(applied_items)
        for item in applied_items:
            if item not in proposed_items:
                raise ProtocolError(
                    f"applied_changes.{field} contains an operation not present "
                    "in the source proposal"
                )
    if applied_count == 0:
        raise ProtocolError("Accepted mutation must apply at least one proposed change")


def _validate_mutation_supersession_event(
    ledger: Ledger,
    event: dict[str, Any],
) -> None:
    mutation_event_id = event.get("mutation_event_id")
    if mutation_event_id is None:
        return
    if not isinstance(mutation_event_id, str) or not mutation_event_id:
        raise ProtocolError("assignment_superseded mutation_event_id must be a string")
    accepted = next(
        (
            candidate
            for candidate in ledger.event_log
            if candidate.get("event_id") == mutation_event_id
            and candidate.get("event_type") == "workflow_mutation_accepted"
        ),
        None,
    )
    if accepted is None:
        raise ProtocolError(
            "Mutation assignment_superseded event must reference an existing "
            "workflow_mutation_accepted event"
        )
    if event.get("source_event_id") != mutation_event_id:
        raise ProtocolError(
            "Mutation assignment_superseded source_event_id must match mutation_event_id"
        )
    if event.get("superseded_by") != mutation_event_id:
        raise ProtocolError(
            "Mutation assignment_superseded superseded_by must match mutation_event_id"
        )


def _validate_node_outcome_decision_event(event: dict[str, Any]) -> None:
    _required_string(event, "source_outcome_id")
    _required_string(event, "actor")
    disposition = _required_string(event, "disposition")
    if disposition not in {"accepted", "partially_accepted", "rejected"}:
        raise ProtocolError(
            "node_outcome_decided disposition must be accepted, partially_accepted, or rejected"
        )
    outcome_status = _required_string(event, "outcome_status")
    if outcome_status not in {
        "completed",
        "failed",
        "timed_out",
        "cancelled",
        "partial",
        "superseded",
        "stale",
        "needs_review",
    }:
        raise ProtocolError(
            "node_outcome_decided outcome_status must be a valid node outcome status"
        )
    accepted_event_types = event.get("accepted_event_types", [])
    if not isinstance(accepted_event_types, list) or not all(
        isinstance(item, str) and item for item in accepted_event_types
    ):
        raise ProtocolError(
            "node_outcome_decided accepted_event_types must be a list of strings"
        )
    for field in ("pre_state_ref", "post_state_ref"):
        value = event.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ProtocolError(
                f"node_outcome_decided {field} must be a non-empty string when present"
            )


def write_ledger(path: Path, ledger: Ledger) -> None:
    ledger = rebuild_ledger_projection(ledger)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(ledger_to_dict(ledger), handle, sort_keys=False)


def ledger_to_dict(ledger: Ledger) -> dict[str, Any]:
    return {
        "mission_id": ledger.mission_id,
        "ledger_version": ledger.ledger_version,
        "current_goal": ledger.current_goal,
        "current_plan_ref": ledger.current_plan_ref,
        "projection": ledger.projection,
        "public_findings": ledger.public_findings,
        "decisions": ledger.decisions,
        "risks": ledger.risks,
        "artifacts": ledger.artifacts,
        "broadcasts": ledger.broadcasts,
        "open_questions": ledger.open_questions,
        "event_log": ledger.event_log,
    }


def rebuild_ledger_projection(ledger: Ledger) -> Ledger:
    derived_projection = _derive_projection(ledger)
    persisted_cursor = _string_or_none(ledger.projection.get("through_event_id"))
    derived_cursor = _string_or_none(derived_projection.get("through_event_id"))
    has_persisted_projection = bool(ledger.projection)
    has_projected_state = any(
        (
            ledger.public_findings,
            ledger.decisions,
            ledger.risks,
            ledger.open_questions,
        )
    )

    if persisted_cursor != derived_cursor or (
        not has_persisted_projection and has_projected_state
    ):
        return replace(
            ledger,
            projection=derived_projection,
            public_findings=[],
            decisions=[],
            risks=[],
            open_questions=[],
        )
    return replace(ledger, projection=derived_projection)


def _derive_projection(ledger: Ledger) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    if ledger.event_log:
        last_event_id = _string_or_none(ledger.event_log[-1].get("event_id"))
        if last_event_id is not None:
            projection["through_event_id"] = last_event_id
    accepted_workspace_ref = _accepted_workspace_ref(ledger)
    if accepted_workspace_ref is not None:
        projection["accepted_workspace_ref"] = accepted_workspace_ref
    return projection


def _accepted_workspace_ref(ledger: Ledger) -> str | None:
    for event in reversed(ledger.event_log):
        if event.get("event_type") != "node_outcome_decided":
            continue
        if event.get("disposition") not in {"accepted", "partially_accepted"}:
            continue
        post_state_ref = _string_or_none(event.get("post_state_ref"))
        if post_state_ref is not None:
            return post_state_ref
    return None


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Ledger event field {key!r} must be a non-empty string")
    return value


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
