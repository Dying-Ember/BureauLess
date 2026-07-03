from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ProtocolError
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
VALID_ADVISOR_VERDICTS = {"approve", "revise", "reject"}
VALID_ADVISOR_CONFIDENCE = {"low", "medium", "high"}
VALID_ADVISOR_TELEMETRY_MODES = {"observed", "deterministic_fixture"}


@dataclass(frozen=True)
class AdvisorGateDecision:
    invoked: bool
    policy_version: str
    reason: list[str]
    decision_basis: str
    advisor: str | None = None
    estimated_advisor_tokens: int | None = None
    estimated_savings_tokens: int | None = None
    confidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "invoked": self.invoked,
            "policy_version": self.policy_version,
            "reason": self.reason,
            "decision_basis": self.decision_basis,
        }
        for field in (
            "advisor",
            "estimated_advisor_tokens",
            "estimated_savings_tokens",
            "confidence",
        ):
            value = getattr(self, field)
            if value is not None:
                payload[field] = value
        return payload


@dataclass(frozen=True)
class AdvisorRecommendation:
    advisor: str
    verdict: str
    confidence: str
    p50_tokens: int
    p90_tokens: int
    p50_cost_usd: float
    p90_cost_usd: float
    main_cost_drivers: list[str]
    main_risk_drivers: list[str]
    recommended_changes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisor": self.advisor,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "p50_tokens": self.p50_tokens,
            "p90_tokens": self.p90_tokens,
            "p50_cost_usd": self.p50_cost_usd,
            "p90_cost_usd": self.p90_cost_usd,
            "main_cost_drivers": self.main_cost_drivers,
            "main_risk_drivers": self.main_risk_drivers,
            "recommended_changes": self.recommended_changes,
        }


@dataclass(frozen=True)
class AdvisorInvocationRecord:
    invocation_id: str
    advisor: str
    status: str
    gate_decision_ref: str
    recommendation_ref: str
    telemetry_mode: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    started_at: str
    finished_at: str
    capability_scope: str = "recommendation_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "advisor": self.advisor,
            "status": self.status,
            "gate_decision_ref": self.gate_decision_ref,
            "recommendation_ref": self.recommendation_ref,
            "telemetry_mode": self.telemetry_mode,
            "token_usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            },
            "cost_usd": self.cost_usd,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "capability_scope": self.capability_scope,
        }


def load_advisor_gate_decision(data: dict[str, Any]) -> AdvisorGateDecision:
    gate = data.get("advisor_gate_decision", data)
    if not isinstance(gate, dict):
        raise ProtocolError("Advisor gate decision must be an object")
    invoked = gate.get("invoked")
    if not isinstance(invoked, bool):
        raise ProtocolError("Advisor gate decision invoked must be boolean")
    advisor = _as_optional_string(gate.get("advisor"))
    estimated_advisor_tokens = _as_optional_int(gate.get("estimated_advisor_tokens"))
    estimated_savings_tokens = _as_optional_int(gate.get("estimated_savings_tokens"))
    confidence = _as_optional_string(gate.get("confidence"))
    if invoked:
        if advisor is None:
            raise ProtocolError("Invoked advisor gate decision requires advisor")
        if estimated_advisor_tokens is None or estimated_savings_tokens is None:
            raise ProtocolError("Invoked advisor gate decision requires token estimates")
        if confidence not in VALID_ADVISOR_CONFIDENCE:
            raise ProtocolError("Invoked advisor gate decision confidence is invalid")
    return AdvisorGateDecision(
        invoked=invoked,
        policy_version=_as_string(gate, "policy_version", "Advisor gate decision"),
        reason=_as_string_list(gate.get("reason"), "Advisor gate decision reason"),
        decision_basis=_as_string(gate, "decision_basis", "Advisor gate decision"),
        advisor=advisor,
        estimated_advisor_tokens=estimated_advisor_tokens,
        estimated_savings_tokens=estimated_savings_tokens,
        confidence=confidence,
    )


def load_advisor_recommendation(data: dict[str, Any]) -> AdvisorRecommendation:
    allowed = {
        "advisor",
        "verdict",
        "confidence",
        "p50_tokens",
        "p90_tokens",
        "p50_cost_usd",
        "p90_cost_usd",
        "main_cost_drivers",
        "main_risk_drivers",
        "recommended_changes",
    }
    unexpected = sorted(data.keys() - allowed)
    if unexpected:
        raise ProtocolError(
            "Advisor recommendation exceeds recommendation-only scope: "
            + ", ".join(unexpected)
        )
    verdict = _as_string(data, "verdict", "Advisor recommendation")
    if verdict not in VALID_ADVISOR_VERDICTS:
        raise ProtocolError("Advisor recommendation verdict is invalid")
    confidence = _as_string(data, "confidence", "Advisor recommendation")
    if confidence not in VALID_ADVISOR_CONFIDENCE:
        raise ProtocolError("Advisor recommendation confidence is invalid")
    recommendation = AdvisorRecommendation(
        advisor=_as_string(data, "advisor", "Advisor recommendation"),
        verdict=verdict,
        confidence=confidence,
        p50_tokens=_as_non_negative_int(data.get("p50_tokens"), "p50_tokens"),
        p90_tokens=_as_non_negative_int(data.get("p90_tokens"), "p90_tokens"),
        p50_cost_usd=_as_non_negative_float(data.get("p50_cost_usd"), "p50_cost_usd"),
        p90_cost_usd=_as_non_negative_float(data.get("p90_cost_usd"), "p90_cost_usd"),
        main_cost_drivers=_as_string_list(
            data.get("main_cost_drivers"), "Advisor recommendation main_cost_drivers"
        ),
        main_risk_drivers=_as_string_list(
            data.get("main_risk_drivers"), "Advisor recommendation main_risk_drivers"
        ),
        recommended_changes=_as_string_list(
            data.get("recommended_changes"), "Advisor recommendation recommended_changes"
        ),
    )
    if recommendation.p90_tokens < recommendation.p50_tokens:
        raise ProtocolError("Advisor recommendation p90_tokens must be >= p50_tokens")
    if recommendation.p90_cost_usd < recommendation.p50_cost_usd:
        raise ProtocolError("Advisor recommendation p90_cost_usd must be >= p50_cost_usd")
    return recommendation


def load_advisor_invocation(data: dict[str, Any]) -> AdvisorInvocationRecord:
    if data.get("status") != "completed":
        raise ProtocolError("Advisor invocation status must be completed")
    if data.get("capability_scope") != "recommendation_only":
        raise ProtocolError("Advisor invocation capability_scope must be recommendation_only")
    telemetry_mode = _as_string(data, "telemetry_mode", "Advisor invocation")
    if telemetry_mode not in VALID_ADVISOR_TELEMETRY_MODES:
        raise ProtocolError("Advisor invocation telemetry_mode is invalid")
    usage = data.get("token_usage")
    if not isinstance(usage, dict):
        raise ProtocolError("Advisor invocation token_usage must be an object")
    input_tokens = _as_non_negative_int(usage.get("input_tokens"), "input_tokens")
    output_tokens = _as_non_negative_int(usage.get("output_tokens"), "output_tokens")
    total_tokens = _as_non_negative_int(usage.get("total_tokens"), "total_tokens")
    if total_tokens != input_tokens + output_tokens:
        raise ProtocolError("Advisor invocation total_tokens must equal input plus output")
    return AdvisorInvocationRecord(
        invocation_id=_as_string(data, "invocation_id", "Advisor invocation"),
        advisor=_as_string(data, "advisor", "Advisor invocation"),
        status="completed",
        gate_decision_ref=_as_string(data, "gate_decision_ref", "Advisor invocation"),
        recommendation_ref=_as_string(data, "recommendation_ref", "Advisor invocation"),
        telemetry_mode=telemetry_mode,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=_as_non_negative_float(data.get("cost_usd"), "cost_usd"),
        started_at=_as_string(data, "started_at", "Advisor invocation"),
        finished_at=_as_string(data, "finished_at", "Advisor invocation"),
    )


@dataclass(frozen=True)
class AdvisorOutcome:
    outcome_id: str
    mission_id: str
    workflow_id: str | None
    status: str
    source_decision_type: str
    source_decision_ref: str
    advisor_decision_ref: str
    advisor_recommendation_ref: str | None
    advisor_invocation_ref: str | None
    recommendation_applied: bool | None
    classification: str | None
    pending_reason: str | None
    actual_advisor_tokens: int | None
    actual_advisor_cost_usd: float | None
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
        for field in (
            "advisor_recommendation_ref",
            "advisor_invocation_ref",
            "recommendation_applied",
            "actual_advisor_cost_usd",
        ):
            value = getattr(self, field)
            if value is not None:
                payload[field] = value
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
    advisor_recommendation_ref = _as_optional_string(data.get("advisor_recommendation_ref"))
    advisor_invocation_ref = _as_optional_string(data.get("advisor_invocation_ref"))
    recommendation_applied = _as_optional_bool(data.get("recommendation_applied"))
    actual_advisor_tokens = _as_optional_int(data.get("actual_advisor_tokens"))
    actual_advisor_cost_usd = _as_optional_float(data.get("actual_advisor_cost_usd"))
    if classification in {"good_call", "bad_call"}:
        if advisor_recommendation_ref is None or advisor_invocation_ref is None:
            raise ProtocolError("Invoked advisor outcome requires recommendation and invocation refs")
        if recommendation_applied is None:
            raise ProtocolError("Invoked advisor outcome requires recommendation disposition")
        if actual_advisor_tokens is None or actual_advisor_cost_usd is None:
            raise ProtocolError("Invoked advisor outcome requires observed token and cost evidence")
    return AdvisorOutcome(
        outcome_id=_as_string(data, "outcome_id"),
        mission_id=_as_string(data, "mission_id"),
        workflow_id=_as_optional_string(data.get("workflow_id")),
        status=status,
        source_decision_type=source_decision_type,
        source_decision_ref=_as_string(data, "source_decision_ref"),
        advisor_decision_ref=_as_string(data, "advisor_decision_ref"),
        advisor_recommendation_ref=advisor_recommendation_ref,
        advisor_invocation_ref=advisor_invocation_ref,
        recommendation_applied=recommendation_applied,
        classification=classification,
        pending_reason=pending_reason,
        actual_advisor_tokens=actual_advisor_tokens,
        actual_advisor_cost_usd=actual_advisor_cost_usd,
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
    for field in (
        "advisor_recommendation_ref",
        "advisor_invocation_ref",
        "recommendation_applied",
        "actual_advisor_cost_usd",
    ):
        value = getattr(outcome, field)
        if value is not None:
            payload[field] = value
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


def _as_string(data: dict[str, Any], key: str, prefix: str = "Advisor outcome") -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{prefix} field {key!r} must be a non-empty string")
    return value


def _as_string_list(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProtocolError(f"{prefix} must be a list of non-empty strings")
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


def _as_non_negative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ProtocolError(f"Advisor field {field!r} must be a non-negative integer")
    return value


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return _as_non_negative_float(value, "actual_advisor_cost_usd")


def _as_non_negative_float(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ProtocolError(f"Advisor field {field!r} must be a non-negative number")
    return float(value)


def _as_optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProtocolError("Advisor outcome price_snapshot_attribution must be an object")
    return value
