from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from ..errors import ProtocolError
from .harness import STRICT_ACCEPTANCE_LEDGER_VERSION, Ledger, Workflow
from .mutations import (
    TrustedWorkflowMutationProposal,
    build_trusted_workflow_mutation_proposal,
    load_workflow_mutation_proposal,
    materialize_current_workflow,
    mutation_proposed_changes,
    workflow_content_hash,
    workflow_version_identity,
)


LIFECYCLE_EVENT_TYPES = {
    "assignment_created",
    "result_submitted",
    "review_approved",
    "review_rejected",
    "worker_timeout",
    "assignment_cancelled",
    "assignment_retry_requested",
    "assignment_retry_scheduled",
    "assignment_circuit_opened",
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
    "review_decision_recorded",
    "advisor_outcome_recorded",
    "context_requested",
    "context_resolved",
    "context_resumed",
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
    normalized = _with_workflow_version_transition(ledger, event, workflow)
    validate_ledger_event(ledger, normalized, workflow)
    return rebuild_ledger_projection(
        replace(ledger, event_log=[*ledger.event_log, normalized])
    )


def _with_workflow_version_transition(
    ledger: Ledger,
    event: dict[str, Any],
    workflow: Workflow | None,
) -> dict[str, Any]:
    if (
        ledger.ledger_version < 3
        or event.get("event_type") != "workflow_mutation_accepted"
        or workflow is None
    ):
        return event

    before = materialize_current_workflow(workflow, ledger)
    sequence = sum(
        item.get("event_type") == "workflow_mutation_accepted"
        and item.get("workflow_id") == workflow.workflow_id
        for item in ledger.event_log
    )
    provisional = replace(ledger, event_log=[*ledger.event_log, event])
    after = materialize_current_workflow(workflow, provisional)
    version_before = workflow_version_identity(before, sequence)
    version_after = workflow_version_identity(after, sequence + 1)
    expected = {
        "workflow_version_before": version_before,
        "workflow_version_after": version_after,
        "workflow_hash_before": workflow_content_hash(before),
        "workflow_hash_after": workflow_content_hash(after),
        "parent_workflow_version_id": version_before,
    }
    for field, value in expected.items():
        supplied = event.get(field)
        if supplied is not None and supplied != value:
            raise ProtocolError(
                f"workflow_mutation_accepted {field} does not match derived transition"
            )
    return {**event, **expected}


def require_strict_writable_ledger(ledger: Ledger, operation: str) -> None:
    if ledger.ledger_version < STRICT_ACCEPTANCE_LEDGER_VERSION:
        raise ProtocolError(
            f"{operation} requires ledger_version 2; migrate the legacy ledger first"
        )


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
    if (
        ledger.ledger_version >= STRICT_ACCEPTANCE_LEDGER_VERSION
        and workflow is not None
        and event_type in workflow.events
    ):
        raise ProtocolError(
            "Strict ledgers cannot append workflow completion events directly; "
            "use node_outcome_decided accepted_event_types"
        )

    if event_type == "workflow_mutation_proposed":
        _validate_mutation_proposed_event(ledger, event, workflow)
    elif event_type in MUTATION_DECISION_EVENT_TYPES:
        _validate_mutation_decision_event(ledger, event, event_type)
    elif event_type == "assignment_superseded":
        _validate_mutation_supersession_event(ledger, event)
    elif event_type == "node_outcome_decided":
        _validate_node_outcome_decision_event(ledger, event)
    elif event_type == "review_decision_recorded":
        _validate_review_decision_recorded_event(ledger, event)
    elif event_type == "advisor_outcome_recorded":
        _validate_advisor_outcome_recorded_event(event)
    elif event_type in {"assignment_retry_scheduled", "assignment_circuit_opened"}:
        _validate_retry_control_event(ledger, event, event_type)
    elif event_type in {"context_requested", "context_resolved", "context_resumed"}:
        _validate_context_lifecycle_event(ledger, event, event_type)

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


def _validate_context_lifecycle_event(
    ledger: Ledger,
    event: dict[str, Any],
    event_type: str,
) -> None:
    assignment_id = _required_string(event, "assignment_id")
    request_id = _required_string(event, "context_request_id")
    if event_type == "context_requested":
        from .context import load_context_request

        request_payload = event.get("request")
        if not isinstance(request_payload, dict):
            raise ProtocolError("context_requested requires a request object")
        request = load_context_request(request_payload)
        if request.assignment_id != assignment_id:
            raise ProtocolError("Context request assignment_id does not match event")
        if request.context_request_id != request_id:
            raise ProtocolError("Context request id does not match event")
        return

    source_event_id = _required_string(event, "source_event_id")
    source = next(
        (item for item in ledger.event_log if item.get("event_id") == source_event_id),
        None,
    )
    expected_type = "context_requested" if event_type == "context_resolved" else "context_resolved"
    if source is None or source.get("event_type") != expected_type:
        raise ProtocolError(f"{event_type} source_event_id must reference {expected_type}")
    if source.get("assignment_id") != assignment_id or source.get("context_request_id") != request_id:
        raise ProtocolError("Context lifecycle identity does not match source event")
    if event_type == "context_resolved":
        resolution = event.get("resolution")
        if not isinstance(resolution, dict):
            raise ProtocolError("context_resolved requires a resolution object")
        status = event.get("status")
        if status not in {
            "granted",
            "partially_granted",
            "denied",
            "unavailable",
            "expired",
            "budget_exceeded",
        }:
            raise ProtocolError("context_resolved status is invalid")
    elif source.get("status") not in {"granted", "partially_granted"}:
        raise ProtocolError("context_resumed requires a granted resolution")


def _validate_retry_control_event(
    ledger: Ledger,
    event: dict[str, Any],
    event_type: str,
) -> None:
    _required_string(event, "assignment_id")
    _required_string(event, "root_assignment_id")
    prior_attempt_id = _required_string(event, "prior_attempt_id")
    _required_string(event, "node_id")
    _required_string(event, "role")
    failure_class = _required_string(event, "failure_class")
    if failure_class not in {
        "transient_infrastructure",
        "malformed_output_contract",
        "verification_failure",
        "capability_mismatch",
        "deterministic_failure",
        "workflow_structure",
        "stale_or_superseded",
        "policy_rejection",
    }:
        raise ProtocolError("Retry control failure_class is invalid")
    fingerprint = _required_string(event, "failure_fingerprint")
    if len(fingerprint) != 64:
        raise ProtocolError("Retry control failure_fingerprint must be SHA-256")
    _required_string(event, "error_code")
    strategy_id = event.get("strategy_id")
    if not isinstance(strategy_id, str) or not strategy_id:
        raise ProtocolError("Retry control strategy_id must be a string")
    evidence = event.get("changed_evidence_refs")
    if not isinstance(evidence, list) or not all(
        isinstance(item, str) and item for item in evidence
    ):
        raise ProtocolError("Retry control changed_evidence_refs must be strings")
    budget = event.get("budget_snapshot")
    if not isinstance(budget, dict) or budget.get("policy_version") != "retry-v1":
        raise ProtocolError("Retry control requires retry-v1 budget_snapshot")
    for field in ("attempts_used", "attempts_allowed", "tokens_used", "token_budget"):
        if not isinstance(budget.get(field), int) or budget[field] < 0:
            raise ProtocolError(f"Retry control budget_snapshot.{field} must be an integer")
    prior_exists = any(
        candidate.get("assignment_id") == prior_attempt_id
        and candidate.get("event_type")
        in {"assignment_created", "assignment_retry_scheduled"}
        for candidate in ledger.event_log
    )
    if not prior_exists:
        raise ProtocolError("Retry control prior_attempt_id is unknown")
    if event_type == "assignment_retry_scheduled":
        attempt_id = _required_string(event, "attempt_id")
        if event.get("assignment_id") != attempt_id:
            raise ProtocolError("Scheduled retry assignment_id must match attempt_id")
        if event.get("retry_of") != prior_attempt_id:
            raise ProtocolError("Scheduled retry retry_of must match prior_attempt_id")
        _required_string(event, "retry_reason")
    else:
        terminal_state = _required_string(event, "terminal_state")
        if terminal_state not in {"needs_review", "needs_replan"}:
            raise ProtocolError("Circuit terminal_state is invalid")
        _required_string(event, "reason")


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
    if isinstance(proposal, TrustedWorkflowMutationProposal):
        _validate_trusted_mutation_proposed_event(ledger, event, proposal)
    for existing in ledger.event_log:
        existing_proposal = existing.get("mutation_proposal")
        if (
            isinstance(existing_proposal, dict)
            and existing_proposal.get("proposal_id") == proposal.proposal_id
        ):
            raise ProtocolError(
                f"Duplicate workflow mutation proposal id: {proposal.proposal_id}"
            )


def _validate_trusted_mutation_proposed_event(
    ledger: Ledger,
    event: dict[str, Any],
    proposal: TrustedWorkflowMutationProposal,
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
    if source_event is None or source_event.get("event_type") != "result_submitted":
        raise ProtocolError(
            "Trusted mutation source_event_id must reference result_submitted"
        )
    if source_event.get("workflow_version_id") != proposal.base_workflow_version_id:
        raise ProtocolError(
            "Trusted mutation base workflow version does not match source result"
        )
    if source_event.get("assignment_id") != proposal.source.assignment_id:
        raise ProtocolError("Trusted mutation assignment provenance mismatch")
    if source_event.get("agent_id") != proposal.source.agent_id:
        raise ProtocolError("Trusted mutation agent provenance mismatch")
    if event.get("assignment_id") != proposal.source.assignment_id:
        raise ProtocolError("Trusted mutation event assignment provenance mismatch")
    if event.get("session_id") != proposal.source.session_id:
        raise ProtocolError("Trusted mutation event session provenance mismatch")
    if event.get("agent_id") != proposal.source.agent_id:
        raise ProtocolError("Trusted mutation event agent provenance mismatch")
    assignment_event = next(
        (
            candidate
            for candidate in ledger.event_log
            if candidate.get("event_type") == "assignment_created"
            and candidate.get("assignment_id") == proposal.source.assignment_id
        ),
        None,
    )
    if assignment_event is None:
        raise ProtocolError("Trusted mutation requires assignment_created provenance")
    if (
        assignment_event.get("session_id") != proposal.source.session_id
        or assignment_event.get("agent_id") != proposal.source.agent_id
    ):
        raise ProtocolError("Trusted mutation assignment creation provenance mismatch")

    rebuilt = build_trusted_workflow_mutation_proposal(
        proposal.intent.to_dict(),
        workflow_id=proposal.workflow_id,
        assignment_id=proposal.source.assignment_id,
        session_id=proposal.source.session_id,
        agent_id=proposal.source.agent_id,
        source_result_event_id=source_event_id,
        assignment_workflow_version_id=proposal.base_workflow_version_id,
        current_workflow_version_id=proposal.base_workflow_version_id,
        requires_approval=proposal.requires_approval,
    )
    if rebuilt.proposal != proposal:
        raise ProtocolError("Trusted mutation proposal identity is not deterministic")
    if event.get("event_id") != f"event-{proposal.proposal_id}":
        raise ProtocolError("Trusted mutation event_id does not match proposal_id")

    artifact = event.get("proposal_artifact")
    if not isinstance(artifact, dict):
        raise ProtocolError("Trusted mutation event requires proposal_artifact")
    for field in ("artifact_id", "path", "sha256", "created_by", "source_event"):
        value = artifact.get(field)
        if not isinstance(value, str) or not value:
            raise ProtocolError(
                f"Trusted mutation proposal_artifact.{field} must be a string"
            )
    if artifact.get("mutable") is not False:
        raise ProtocolError("Trusted mutation proposal artifact must be immutable")
    if artifact.get("source_event") != source_event_id:
        raise ProtocolError("Trusted mutation proposal artifact source mismatch")


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
    proposed_changes = mutation_proposed_changes(proposal)
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


def _validate_node_outcome_decision_event(
    ledger: Ledger,
    event: dict[str, Any],
) -> None:
    source_outcome_id = _required_string(event, "source_outcome_id")
    if any(
        existing.get("event_type") == "node_outcome_decided"
        and existing.get("source_outcome_id") == source_outcome_id
        for existing in ledger.event_log
    ):
        raise ProtocolError(
            "node_outcome_decided source_outcome_id already has a terminal decision"
        )
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
    if len(accepted_event_types) != len(set(accepted_event_types)):
        raise ProtocolError(
            "node_outcome_decided accepted_event_types must not contain duplicates"
        )
    if disposition == "rejected" and accepted_event_types:
        raise ProtocolError(
            "node_outcome_decided rejected disposition cannot accept workflow events"
        )
    if outcome_status in {
        "failed",
        "timed_out",
        "cancelled",
        "superseded",
        "stale",
        "needs_review",
    } and accepted_event_types:
        raise ProtocolError(
            f"node_outcome_decided {outcome_status} outcome cannot accept workflow events"
        )
    if ledger.ledger_version >= STRICT_ACCEPTANCE_LEDGER_VERSION:
        _validate_strict_node_outcome_decision(ledger, event, accepted_event_types)
    for field in ("pre_state_ref", "post_state_ref"):
        value = event.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ProtocolError(
                f"node_outcome_decided {field} must be a non-empty string when present"
            )


def _validate_strict_node_outcome_decision(
    ledger: Ledger,
    event: dict[str, Any],
    accepted_event_types: list[str],
) -> None:
    result_event_id = _required_string(event, "source_result_event_id")
    _required_string(event, "acceptance_policy_version")
    _required_string(event, "verification_status")
    _required_string(event, "validation_rule")
    result_event = next(
        (
            existing
            for existing in ledger.event_log
            if existing.get("event_id") == result_event_id
            and existing.get("event_type") == "result_submitted"
        ),
        None,
    )
    if result_event is None:
        raise ProtocolError(
            "node_outcome_decided source_result_event_id must reference result_submitted"
        )
    for field in ("assignment_id", "node_id", "workflow_id", "role", "agent_id"):
        if event.get(field) != result_event.get(field):
            raise ProtocolError(
                f"node_outcome_decided {field} must match its result_submitted event"
            )
    result = result_event.get("result")
    if not isinstance(result, dict):
        raise ProtocolError("Strict result_submitted event must contain a result object")
    claimed = result.get("emitted_events", [])
    if not isinstance(claimed, list) or not all(
        isinstance(item, str) and item for item in claimed
    ):
        raise ProtocolError("Strict result emitted_events must be a list of strings")
    if not set(accepted_event_types) <= set(claimed):
        raise ProtocolError(
            "node_outcome_decided accepted events must be claimed by the staged result"
        )
    disposition = event.get("disposition")
    if disposition == "accepted" and set(accepted_event_types) != set(claimed):
        raise ProtocolError(
            "node_outcome_decided accepted disposition must accept all claimed events"
        )
    if disposition == "partially_accepted" and (
        not accepted_event_types or set(accepted_event_types) == set(claimed)
    ):
        raise ProtocolError(
            "node_outcome_decided partially_accepted requires a non-empty strict subset"
        )
    review_event_id = event.get("source_review_event_id")
    if review_event_id is None:
        return
    if not isinstance(review_event_id, str) or not review_event_id:
        raise ProtocolError(
            "node_outcome_decided source_review_event_id must be a non-empty string"
        )
    review_event = next(
        (
            existing
            for existing in ledger.event_log
            if existing.get("event_id") == review_event_id
            and existing.get("event_type") == "review_decision_recorded"
        ),
        None,
    )
    if review_event is None or review_event.get("reviewed_event") != result_event_id:
        raise ProtocolError(
            "node_outcome_decided review decision must reference its staged result"
        )
    if accepted_event_types and review_event.get("verdict") != "approved":
        raise ProtocolError(
            "node_outcome_decided cannot accept events from a non-approved review"
        )


def _validate_review_decision_recorded_event(
    ledger: Ledger,
    event: dict[str, Any],
) -> None:
    _required_string(event, "review_decision_id")
    reviewed_event = _required_string(event, "reviewed_event")
    actor = _required_string(event, "actor")
    if actor not in {"orchestrator", "human"}:
        raise ProtocolError(
            "review_decision_recorded actor must be orchestrator or human"
        )
    verdict = _required_string(event, "verdict")
    if verdict not in {"approved", "rejected", "changes_requested"}:
        raise ProtocolError(
            "review_decision_recorded verdict must be approved, rejected, or changes_requested"
        )
    next_action = _required_string(event, "next_action")
    if next_action not in {"continue", "retry", "escalate", "stop"}:
        raise ProtocolError(
            "review_decision_recorded next_action must be continue, retry, escalate, or stop"
        )
    _required_string(event, "decision_ref")
    if not any(existing.get("event_id") == reviewed_event for existing in ledger.event_log):
        raise ProtocolError(
            "review_decision_recorded reviewed_event must reference an existing ledger event"
        )
    accepted_findings = event.get("accepted_findings", [])
    rejected_findings = event.get("rejected_findings", [])
    if not isinstance(accepted_findings, list) or not all(
        isinstance(item, dict) for item in accepted_findings
    ):
        raise ProtocolError(
            "review_decision_recorded accepted_findings must be a list of objects"
        )
    if not isinstance(rejected_findings, list) or not all(
        isinstance(item, dict) for item in rejected_findings
    ):
        raise ProtocolError(
            "review_decision_recorded rejected_findings must be a list of objects"
        )
    for finding in accepted_findings:
        _required_string(finding, "finding_id")
        _required_string(finding, "content")
    for finding in rejected_findings:
        _required_string(finding, "finding_id")
        _required_string(finding, "reason")


def _validate_advisor_outcome_recorded_event(event: dict[str, Any]) -> None:
    _required_string(event, "advisor_outcome_id")
    status = _required_string(event, "status")
    if status not in {"pending", "scored"}:
        raise ProtocolError("advisor_outcome_recorded status must be pending or scored")
    source_decision_type = _required_string(event, "source_decision_type")
    if source_decision_type not in {"routing_decision", "review_decision"}:
        raise ProtocolError(
            "advisor_outcome_recorded source_decision_type must be routing_decision or review_decision"
        )
    _required_string(event, "source_decision_ref")
    _required_string(event, "advisor_decision_ref")
    _required_string(event, "outcome_ref")
    for field in ("advisor_recommendation_ref", "advisor_invocation_ref"):
        value = event.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ProtocolError(
                f"advisor_outcome_recorded {field} must be a non-empty string when present"
            )
    recommendation_applied = event.get("recommendation_applied")
    if recommendation_applied is not None and not isinstance(recommendation_applied, bool):
        raise ProtocolError(
            "advisor_outcome_recorded recommendation_applied must be boolean when present"
        )
    classification = _string_or_none(event.get("classification"))
    pending_reason = _string_or_none(event.get("pending_reason"))
    if status == "pending":
        if pending_reason is None:
            raise ProtocolError(
                "advisor_outcome_recorded pending status requires pending_reason"
            )
        if classification is not None:
            raise ProtocolError(
                "advisor_outcome_recorded pending status must not include classification"
            )
    else:
        if classification not in {"good_call", "bad_call", "good_skip", "missed_call"}:
            raise ProtocolError(
                "advisor_outcome_recorded scored status requires a valid classification"
            )
        if pending_reason is not None:
            raise ProtocolError(
                "advisor_outcome_recorded scored status must not include pending_reason"
            )
    for field in (
        "actual_advisor_tokens",
        "actual_total_tokens",
        "rework_count",
        "broadcast_tokens",
    ):
        value = event.get(field)
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ProtocolError(
                f"advisor_outcome_recorded {field} must be a non-negative integer when present"
            )
    duplicate_context_observed = event.get("duplicate_context_observed")
    if duplicate_context_observed is not None and not isinstance(
        duplicate_context_observed, bool
    ):
        raise ProtocolError(
            "advisor_outcome_recorded duplicate_context_observed must be boolean when present"
        )
    actual_advisor_cost_usd = event.get("actual_advisor_cost_usd")
    if actual_advisor_cost_usd is not None and (
        not isinstance(actual_advisor_cost_usd, (int, float))
        or isinstance(actual_advisor_cost_usd, bool)
        or actual_advisor_cost_usd < 0
    ):
        raise ProtocolError(
            "advisor_outcome_recorded actual_advisor_cost_usd must be non-negative when present"
        )
    price_snapshot_attribution = event.get("price_snapshot_attribution")
    if price_snapshot_attribution is not None and not isinstance(
        price_snapshot_attribution, dict
    ):
        raise ProtocolError(
            "advisor_outcome_recorded price_snapshot_attribution must be an object when present"
        )
    if classification in {"good_call", "bad_call"}:
        if not event.get("advisor_recommendation_ref") or not event.get(
            "advisor_invocation_ref"
        ):
            raise ProtocolError(
                "invoked advisor_outcome_recorded requires recommendation and invocation refs"
            )
        if recommendation_applied is None:
            raise ProtocolError(
                "invoked advisor_outcome_recorded requires recommendation disposition"
            )
        if event.get("actual_advisor_tokens") is None or actual_advisor_cost_usd is None:
            raise ProtocolError(
                "invoked advisor_outcome_recorded requires observed token and cost evidence"
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
    public_findings, decisions, risks, open_questions = _derive_projected_state(ledger)
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
            public_findings=public_findings,
            decisions=decisions,
            risks=risks,
            open_questions=open_questions,
        )
    return replace(
        ledger,
        projection=derived_projection,
        public_findings=public_findings,
        decisions=decisions,
        risks=risks,
        open_questions=open_questions,
    )


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


def _derive_projected_state(
    ledger: Ledger,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    public_findings: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    reviewed_events = {event.get("event_id"): event for event in ledger.event_log}
    for event in ledger.event_log:
        if event.get("event_type") != "review_decision_recorded":
            continue
        decision_id = _string_or_none(event.get("review_decision_id"))
        reviewed_event_id = _string_or_none(event.get("reviewed_event"))
        actor = _string_or_none(event.get("actor"))
        verdict = _string_or_none(event.get("verdict"))
        next_action = _string_or_none(event.get("next_action"))
        if None in {decision_id, reviewed_event_id, actor, verdict, next_action}:
            continue
        decisions.append(
            {
                "decision_id": decision_id,
                "decision_type": "review_decision",
                "reviewed_event": reviewed_event_id,
                "verdict": verdict,
                "next_action": next_action,
                "accepted_by": actor,
                "source_event": event.get("event_id"),
            }
        )
        reviewed_event = reviewed_events.get(reviewed_event_id, {})
        source_agent = _string_or_none(reviewed_event.get("agent_id")) or _string_or_none(
            reviewed_event.get("source_agent")
        ) or "unknown"
        accepted_findings = event.get("accepted_findings", [])
        if not isinstance(accepted_findings, list):
            continue
        for finding in accepted_findings:
            if not isinstance(finding, dict):
                continue
            finding_id = _string_or_none(finding.get("finding_id"))
            content = _string_or_none(finding.get("content"))
            if finding_id is None or content is None:
                continue
            public_findings.append(
                {
                    "finding_id": finding_id,
                    "content": content,
                    "source_event": reviewed_event_id,
                    "source_agent": source_agent,
                    "accepted_by": actor,
                    "review_decision_id": decision_id,
                }
            )
    return public_findings, decisions, [], []


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
