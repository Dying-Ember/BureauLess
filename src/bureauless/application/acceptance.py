from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import ProtocolError
from ..protocol.acceptance import AcceptancePolicy
from ..protocol.assignments import AssignmentPacket
from ..protocol.harness import STRICT_ACCEPTANCE_LEDGER_VERSION, Ledger, Workflow
from ..protocol.ledger import append_ledger_event
from ..protocol.outcomes import NodeOutcome, build_node_outcome_decision_event
from ..protocol.outcomes import node_outcome_from_session, reconcile_node_outcome_state
from ..protocol.results import ResultProposal, import_result_proposal
from ..runtime.sessions import SessionRecord, package_session_result


@dataclass(frozen=True)
class StagedResult:
    ledger: Ledger
    result_event_id: str
    outcome: NodeOutcome


@dataclass(frozen=True)
class AcceptanceResult:
    ledger: Ledger
    decision_event: dict[str, object]
    disposition: str
    accepted_event_types: list[str]


@dataclass(frozen=True)
class StagedSessionResult:
    ledger: Ledger
    result_event_id: str
    result: ResultProposal
    outcome: NodeOutcome


def stage_session_record(
    workflow: Workflow,
    ledger: Ledger,
    assignment: AssignmentPacket,
    record: SessionRecord,
    *,
    artifact_root: Path | None = None,
    result_id: str | None = None,
    outcome_id: str | None = None,
) -> StagedSessionResult:
    result = package_session_result(
        record,
        assignment,
        artifact_root=artifact_root,
        result_id=result_id,
    )
    outcome = reconcile_node_outcome_state(
        node_outcome_from_session(
            assignment,
            record.to_dict(),
            outcome_id=outcome_id,
        ),
        _accepted_workspace_ref_for_node(ledger, assignment.node_id),
    )
    updated = ledger
    context_events = record.extraction.get("context_events", [])
    if not isinstance(context_events, list) or not all(
        isinstance(event, dict) for event in context_events
    ):
        raise ProtocolError("Session context_events must be a list of objects")
    for event in context_events:
        updated = append_ledger_event(updated, event, workflow)
    staged = stage_result(workflow, updated, assignment, result, outcome)
    return StagedSessionResult(
        ledger=staged.ledger,
        result_event_id=staged.result_event_id,
        result=result,
        outcome=outcome,
    )


def stage_result(
    workflow: Workflow,
    ledger: Ledger,
    assignment: AssignmentPacket,
    result: ResultProposal,
    outcome: NodeOutcome,
) -> StagedResult:
    _require_strict_ledger(ledger)
    _validate_outcome_identity(assignment, result, outcome)
    updated = import_result_proposal(workflow, ledger, assignment, result)
    return StagedResult(
        ledger=updated,
        result_event_id=f"event-{result.result_id}",
        outcome=outcome,
    )


def decide_staged_result(
    workflow: Workflow,
    ledger: Ledger,
    assignment: AssignmentPacket,
    result: ResultProposal,
    outcome: NodeOutcome,
    *,
    policy: AcceptancePolicy,
    verification_status: str,
    review_event_id: str | None = None,
    accepted_event_types: list[str] | None = None,
    actor: str = "harness",
    event_id: str | None = None,
    validation_rule: str = "acceptance_policy_v1",
    created_at: str | None = None,
) -> AcceptanceResult:
    _require_strict_ledger(ledger)
    _validate_outcome_identity(assignment, result, outcome)
    result_event_id = f"event-{result.result_id}"
    result_event = _event_by_id(ledger, result_event_id)
    if result_event is None or result_event.get("event_type") != "result_submitted":
        raise ProtocolError("Outcome acceptance requires a staged result_submitted event")
    if result_event.get("result") != result.to_dict():
        raise ProtocolError("Outcome acceptance result does not match the staged result")
    if actor not in {"harness", "orchestrator", "human"}:
        raise ProtocolError("Outcome acceptance actor must be harness, orchestrator, or human")

    review_event = _validated_review_event(
        ledger,
        result_event_id=result_event_id,
        review_event_id=review_event_id,
        policy=policy,
    )
    eligible = (
        outcome.status == "completed"
        and verification_status in policy.required_verification_statuses
        and (review_event is None or review_event.get("verdict") == "approved")
    )
    requested = list(result.emitted_events if accepted_event_types is None else accepted_event_types)
    _validate_requested_events(result, requested)

    if eligible:
        disposition = _accepted_disposition(result, requested, policy)
        effective_events = requested
    else:
        disposition = "rejected"
        effective_events = []

    decision_event = build_node_outcome_decision_event(
        outcome,
        event_id=event_id or f"event-{outcome.outcome_id}-decision",
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        actor=actor,
        disposition=disposition,
        accepted_event_types=effective_events,
        validation_rule=validation_rule,
        created_at=created_at,
        source_result_event_id=result_event_id,
        source_review_event_id=review_event_id,
        acceptance_policy_version=policy.policy_version,
        verification_status=verification_status,
    )
    updated = append_ledger_event(ledger, decision_event, workflow)
    return AcceptanceResult(
        ledger=updated,
        decision_event=decision_event,
        disposition=disposition,
        accepted_event_types=effective_events,
    )


def _require_strict_ledger(ledger: Ledger) -> None:
    if ledger.ledger_version < STRICT_ACCEPTANCE_LEDGER_VERSION:
        raise ProtocolError(
            "Authoritative result acceptance requires ledger_version 2; "
            "migrate the legacy ledger first"
        )


def _validate_outcome_identity(
    assignment: AssignmentPacket,
    result: ResultProposal,
    outcome: NodeOutcome,
) -> None:
    if result.assignment_id != assignment.assignment_id:
        raise ProtocolError("Acceptance result assignment_id does not match assignment")
    if outcome.assignment_id != assignment.assignment_id:
        raise ProtocolError("Acceptance outcome assignment_id does not match assignment")
    if outcome.workflow_id != assignment.workflow_id:
        raise ProtocolError("Acceptance outcome workflow_id does not match assignment")
    if outcome.node_id != assignment.node_id or outcome.role != assignment.role:
        raise ProtocolError("Acceptance outcome node or role does not match assignment")
    if outcome.agent_id != result.agent_id:
        raise ProtocolError("Acceptance outcome agent_id does not match result")


def _validated_review_event(
    ledger: Ledger,
    *,
    result_event_id: str,
    review_event_id: str | None,
    policy: AcceptancePolicy,
) -> dict[str, object] | None:
    if review_event_id is None:
        if policy.review_required:
            raise ProtocolError("Acceptance policy requires a review decision")
        return None
    event = _event_by_id(ledger, review_event_id)
    if event is None or event.get("event_type") != "review_decision_recorded":
        raise ProtocolError("Acceptance review_event_id must reference a review decision")
    if event.get("reviewed_event") != result_event_id:
        raise ProtocolError("Acceptance review decision must review the staged result event")
    if event.get("actor") not in policy.allowed_review_actors:
        raise ProtocolError("Acceptance review actor is not allowed by policy")
    return event


def _validate_requested_events(result: ResultProposal, requested: list[str]) -> None:
    if len(requested) != len(set(requested)):
        raise ProtocolError("Acceptance event types must not contain duplicates")
    unknown = sorted(set(requested) - set(result.emitted_events))
    if unknown:
        raise ProtocolError(
            "Acceptance event types were not claimed by the result: "
            f"{', '.join(unknown)}"
        )


def _accepted_disposition(
    result: ResultProposal,
    requested: list[str],
    policy: AcceptancePolicy,
) -> str:
    if set(requested) == set(result.emitted_events):
        return "accepted"
    if not requested:
        raise ProtocolError("Accepted result must include at least one claimed event")
    if not policy.allow_partial_acceptance:
        raise ProtocolError("Acceptance policy does not allow partial acceptance")
    return "partially_accepted"


def _event_by_id(ledger: Ledger, event_id: str) -> dict[str, object] | None:
    for event in ledger.event_log:
        if event.get("event_id") == event_id:
            return event
    return None


def _accepted_workspace_ref_for_node(ledger: Ledger, node_id: str) -> str | None:
    for event in reversed(ledger.event_log):
        if event.get("event_type") != "node_outcome_decided":
            continue
        if event.get("node_id") != node_id:
            continue
        if event.get("disposition") not in {"accepted", "partially_accepted"}:
            continue
        post_state_ref = event.get("post_state_ref")
        if isinstance(post_state_ref, str) and post_state_ref:
            return post_state_ref
    return None
