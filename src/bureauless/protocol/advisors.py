from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core import ProtocolError
from .harness import Ledger, Workflow
from .ledger import append_ledger_event


VALID_ADVISOR_OUTCOME_STATUSES = {"pending", "scored"}
VALID_ADVISOR_OUTCOME_CLASSIFICATIONS = {
    "good_call",
    "bad_call",
    "good_skip",
    "missed_call",
}
VALID_ADVISOR_SOURCE_DECISION_TYPES = {"routing_decision", "review_decision"}


@dataclass(frozen=True)
class AdvisorOutcome:
    outcome_id: str
    mission_id: str
    workflow_id: str | None
    status: str
    source_decision_type: str
    source_decision_ref: str
    advisor_decision_ref: str
    classification: str | None
    pending_reason: str | None
    actual_advisor_tokens: int | None
    actual_total_tokens: int | None
    rework_count: int | None
    broadcast_tokens: int | None
    duplicate_context_observed: bool | None
    price_snapshot_attribution: dict[str, Any] | None
    notes: str | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision_type": "advisor_outcome",
            "outcome_id": self.outcome_id,
            "mission_id": self.mission_id,
            "status": self.status,
            "source_decision_type": self.source_decision_type,
            "source_decision_ref": self.source_decision_ref,
            "advisor_decision_ref": self.advisor_decision_ref,
        }
        if self.workflow_id is not None:
            payload["workflow_id"] = self.workflow_id
        if self.classification is not None:
            payload["classification"] = self.classification
        if self.pending_reason is not None:
            payload["pending_reason"] = self.pending_reason
        for field in (
            "actual_advisor_tokens",
            "actual_total_tokens",
            "rework_count",
            "broadcast_tokens",
        ):
            value = getattr(self, field)
            if value is not None:
                payload[field] = value
        if self.duplicate_context_observed is not None:
            payload["duplicate_context_observed"] = self.duplicate_context_observed
        if self.price_snapshot_attribution is not None:
            payload["price_snapshot_attribution"] = self.price_snapshot_attribution
        if self.notes is not None:
            payload["notes"] = self.notes
        return payload


def load_advisor_outcome(data: dict[str, Any]) -> AdvisorOutcome:
    if _as_string(data, "decision_type") != "advisor_outcome":
        raise ProtocolError("Advisor outcome decision_type must be advisor_outcome")
    status = _as_string(data, "status")
    if status not in VALID_ADVISOR_OUTCOME_STATUSES:
        raise ProtocolError(
            "Advisor outcome status must be one of: pending, scored"
        )
    source_decision_type = _as_string(data, "source_decision_type")
    if source_decision_type not in VALID_ADVISOR_SOURCE_DECISION_TYPES:
        raise ProtocolError(
            "Advisor outcome source_decision_type must be routing_decision or review_decision"
        )
    classification = _as_optional_string(data.get("classification"))
    pending_reason = _as_optional_string(data.get("pending_reason"))
    if status == "pending":
        if pending_reason is None:
            raise ProtocolError("Pending advisor outcome requires pending_reason")
        if classification is not None:
            raise ProtocolError("Pending advisor outcome must not include classification")
    else:
        if classification not in VALID_ADVISOR_OUTCOME_CLASSIFICATIONS:
            raise ProtocolError(
                "Scored advisor outcome classification must be one of: "
                "bad_call, good_call, good_skip, missed_call"
            )
        if pending_reason is not None:
            raise ProtocolError("Scored advisor outcome must not include pending_reason")
    return AdvisorOutcome(
        outcome_id=_as_string(data, "outcome_id"),
        mission_id=_as_string(data, "mission_id"),
        workflow_id=_as_optional_string(data.get("workflow_id")),
        status=status,
        source_decision_type=source_decision_type,
        source_decision_ref=_as_string(data, "source_decision_ref"),
        advisor_decision_ref=_as_string(data, "advisor_decision_ref"),
        classification=classification,
        pending_reason=pending_reason,
        actual_advisor_tokens=_as_optional_int(data.get("actual_advisor_tokens")),
        actual_total_tokens=_as_optional_int(data.get("actual_total_tokens")),
        rework_count=_as_optional_int(data.get("rework_count")),
        broadcast_tokens=_as_optional_int(data.get("broadcast_tokens")),
        duplicate_context_observed=_as_optional_bool(data.get("duplicate_context_observed")),
        price_snapshot_attribution=_as_optional_mapping(data.get("price_snapshot_attribution")),
        notes=_as_optional_string(data.get("notes")),
    )


def apply_advisor_outcome(
    ledger: Ledger,
    outcome: AdvisorOutcome,
    *,
    workflow: Workflow | None = None,
    event_id: str | None = None,
    outcome_ref: str,
) -> Ledger:
    payload: dict[str, Any] = {
        "event_id": event_id or f"event-{outcome.outcome_id}",
        "event_type": "advisor_outcome_recorded",
        "mission_id": outcome.mission_id,
        "advisor_outcome_id": outcome.outcome_id,
        "status": outcome.status,
        "source_decision_type": outcome.source_decision_type,
        "source_decision_ref": outcome.source_decision_ref,
        "advisor_decision_ref": outcome.advisor_decision_ref,
        "outcome_ref": outcome_ref,
    }
    if outcome.workflow_id is not None:
        payload["workflow_id"] = outcome.workflow_id
    if outcome.classification is not None:
        payload["classification"] = outcome.classification
    if outcome.pending_reason is not None:
        payload["pending_reason"] = outcome.pending_reason
    for field in (
        "actual_advisor_tokens",
        "actual_total_tokens",
        "rework_count",
        "broadcast_tokens",
    ):
        value = getattr(outcome, field)
        if value is not None:
            payload[field] = value
    if outcome.duplicate_context_observed is not None:
        payload["duplicate_context_observed"] = outcome.duplicate_context_observed
    if outcome.price_snapshot_attribution is not None:
        payload["price_snapshot_attribution"] = outcome.price_snapshot_attribution
    if outcome.notes is not None:
        payload["notes"] = outcome.notes
    return append_ledger_event(ledger, payload, workflow)


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Advisor outcome field {key!r} must be a non-empty string")
    return value


def _as_optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ProtocolError("Advisor outcome numeric fields must be non-negative integers")
    return value


def _as_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ProtocolError("Advisor outcome duplicate_context_observed must be boolean")
    return value


def _as_optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProtocolError("Advisor outcome price_snapshot_attribution must be an object")
    return value
