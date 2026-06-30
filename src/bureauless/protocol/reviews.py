from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core import ProtocolError
from .harness import Ledger, Workflow
from .ledger import append_ledger_event


VALID_REVIEW_VERDICTS = {"approved", "rejected", "changes_requested"}
VALID_NEXT_ACTIONS = {"continue", "retry", "escalate", "stop"}


@dataclass(frozen=True)
class ReviewDecision:
    decision_id: str
    mission_id: str
    workflow_id: str | None
    reviewed_event: str
    actor: str
    verdict: str
    reason: str
    evidence_refs: list[str]
    accepted_findings: list[dict[str, Any]]
    rejected_findings: list[dict[str, Any]]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision_type": "review_decision",
            "decision_id": self.decision_id,
            "mission_id": self.mission_id,
            "reviewed_event": self.reviewed_event,
            "actor": self.actor,
            "verdict": self.verdict,
            "reason": self.reason,
            "evidence_refs": self.evidence_refs,
            "accepted_findings": self.accepted_findings,
            "rejected_findings": self.rejected_findings,
            "next_action": self.next_action,
        }
        if self.workflow_id is not None:
            payload["workflow_id"] = self.workflow_id
        return payload


def load_review_decision(data: dict[str, Any]) -> ReviewDecision:
    if _as_string(data, "decision_type") != "review_decision":
        raise ProtocolError("Review decision decision_type must be review_decision")
    actor = _as_string(data, "actor")
    if actor not in {"orchestrator", "human"}:
        raise ProtocolError("Review decision actor must be orchestrator or human")
    verdict = _as_string(data, "verdict")
    if verdict not in VALID_REVIEW_VERDICTS:
        raise ProtocolError(
            f"Review decision verdict must be one of: {', '.join(sorted(VALID_REVIEW_VERDICTS))}"
        )
    next_action = _as_string(data, "next_action")
    if next_action not in VALID_NEXT_ACTIONS:
        raise ProtocolError(
            f"Review decision next_action must be one of: {', '.join(sorted(VALID_NEXT_ACTIONS))}"
        )
    accepted_findings = _as_mapping_list(data, "accepted_findings", default=[])
    rejected_findings = _as_mapping_list(data, "rejected_findings", default=[])
    _validate_findings(accepted_findings, "accepted_findings")
    _validate_rejected_findings(rejected_findings)
    overlap = {
        finding["finding_id"]
        for finding in accepted_findings
        if isinstance(finding.get("finding_id"), str)
    } & {
        finding["finding_id"]
        for finding in rejected_findings
        if isinstance(finding.get("finding_id"), str)
    }
    if overlap:
        raise ProtocolError(
            "Review decision must not accept and reject the same finding_id"
        )
    return ReviewDecision(
        decision_id=_as_string(data, "decision_id"),
        mission_id=_as_string(data, "mission_id"),
        workflow_id=_as_optional_string(data.get("workflow_id")),
        reviewed_event=_as_string(data, "reviewed_event"),
        actor=actor,
        verdict=verdict,
        reason=_as_string(data, "reason"),
        evidence_refs=_as_string_list(data, "evidence_refs", default=[]),
        accepted_findings=accepted_findings,
        rejected_findings=rejected_findings,
        next_action=next_action,
    )


def apply_review_decision(
    ledger: Ledger,
    decision: ReviewDecision,
    *,
    workflow: Workflow | None = None,
    event_id: str | None = None,
    decision_ref: str,
) -> Ledger:
    payload = {
        "event_id": event_id or f"event-{decision.decision_id}",
        "event_type": "review_decision_recorded",
        "mission_id": decision.mission_id,
        "review_decision_id": decision.decision_id,
        "reviewed_event": decision.reviewed_event,
        "actor": decision.actor,
        "verdict": decision.verdict,
        "reason": decision.reason,
        "evidence_refs": decision.evidence_refs,
        "accepted_findings": decision.accepted_findings,
        "rejected_findings": decision.rejected_findings,
        "next_action": decision.next_action,
        "decision_ref": decision_ref,
    }
    if decision.workflow_id is not None:
        payload["workflow_id"] = decision.workflow_id
    return append_ledger_event(ledger, payload, workflow)


def _validate_findings(findings: list[dict[str, Any]], field_name: str) -> None:
    seen: set[str] = set()
    for finding in findings:
        finding_id = _as_string(finding, "finding_id")
        _as_string(finding, "content")
        if finding_id in seen:
            raise ProtocolError(f"Review decision {field_name} must not repeat finding_id")
        seen.add(finding_id)


def _validate_rejected_findings(findings: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for finding in findings:
        finding_id = _as_string(finding, "finding_id")
        _as_string(finding, "reason")
        if finding_id in seen:
            raise ProtocolError("Review decision rejected_findings must not repeat finding_id")
        seen.add(finding_id)


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Review decision field {key!r} must be a non-empty string")
    return value


def _as_optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_string_list(
    data: dict[str, Any],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProtocolError(f"Review decision field {key!r} must be a list of strings")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Review decision field {key!r} must be a list of objects")
    return value
