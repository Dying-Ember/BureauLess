from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core import ProtocolError
from .harness import Mission, Workflow


VALID_ROUTING_MODES = {
    "single_agent",
    "single_agent_with_review",
    "small_dag",
    "parallel_swarm",
    "stop_and_ask_human",
}
VALID_BUDGET_CONFIDENCE = {"low", "medium", "high"}
MODE_PRECEDENCE = {
    "single_agent": 0,
    "single_agent_with_review": 1,
    "small_dag": 2,
    "parallel_swarm": 3,
    "stop_and_ask_human": 4,
}


@dataclass(frozen=True)
class RoutingDecision:
    mission_id: str
    workflow_id: str | None
    selected_mode: str
    selection_policy_version: str
    triggered_rules: list[str]
    rejected_modes: list[dict[str, str]]
    estimated_coordination_ratio: float
    budget_confidence: str
    reason: str
    budget_reason: str | None
    risk_reason: str | None
    advisor_gate_decision: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision_type": "routing_decision",
            "mission_id": self.mission_id,
            "selected_mode": self.selected_mode,
            "selection_policy_version": self.selection_policy_version,
            "triggered_rules": self.triggered_rules,
            "rejected_modes": self.rejected_modes,
            "estimated_coordination_ratio": self.estimated_coordination_ratio,
            "budget_confidence": self.budget_confidence,
            "reason": self.reason,
            "advisor_gate_decision": self.advisor_gate_decision,
        }
        if self.workflow_id is not None:
            payload["workflow_id"] = self.workflow_id
        if self.budget_reason is not None:
            payload["budget_reason"] = self.budget_reason
        if self.risk_reason is not None:
            payload["risk_reason"] = self.risk_reason
        return payload


def load_routing_decision(data: dict[str, Any]) -> RoutingDecision:
    if _as_string(data, "decision_type") != "routing_decision":
        raise ProtocolError("Routing decision decision_type must be routing_decision")
    selected_mode = _as_string(data, "selected_mode")
    if selected_mode not in VALID_ROUTING_MODES:
        raise ProtocolError(f"Routing decision selected_mode is invalid: {selected_mode}")
    budget_confidence = _as_string(data, "budget_confidence")
    if budget_confidence not in VALID_BUDGET_CONFIDENCE:
        raise ProtocolError("Routing decision budget_confidence must be low, medium, or high")
    rejected_modes = _as_rejected_modes(data.get("rejected_modes", []))
    advisor_gate_decision = _as_mapping(data, "advisor_gate_decision", default={})
    _validate_advisor_gate_decision(advisor_gate_decision)
    estimated_coordination_ratio = _as_float(data, "estimated_coordination_ratio")
    if estimated_coordination_ratio < 0:
        raise ProtocolError("Routing decision estimated_coordination_ratio must be >= 0")
    return RoutingDecision(
        mission_id=_as_string(data, "mission_id"),
        workflow_id=_as_optional_string(data.get("workflow_id")),
        selected_mode=selected_mode,
        selection_policy_version=_as_string(data, "selection_policy_version"),
        triggered_rules=_as_string_list(data, "triggered_rules", default=[]),
        rejected_modes=rejected_modes,
        estimated_coordination_ratio=estimated_coordination_ratio,
        budget_confidence=budget_confidence,
        reason=_as_string(data, "reason"),
        budget_reason=_as_optional_string(data.get("budget_reason")),
        risk_reason=_as_optional_string(data.get("risk_reason")),
        advisor_gate_decision=advisor_gate_decision,
    )


def validate_routing_decision(
    mission: Mission,
    decision: RoutingDecision,
    *,
    workflow: Workflow | None = None,
) -> None:
    if decision.mission_id != mission.mission_id:
        raise ProtocolError("Routing decision mission_id does not match mission")
    if decision.selected_mode not in mission.allowed_modes:
        raise ProtocolError("Routing decision selected_mode is not allowed by mission")
    if workflow is not None:
        if decision.workflow_id is not None and decision.workflow_id != workflow.workflow_id:
            raise ProtocolError("Routing decision workflow_id does not match workflow")
        if workflow.mode != decision.selected_mode:
            raise ProtocolError("Routing decision selected_mode does not match workflow mode")
    if decision.selected_mode in {"single_agent_with_review", "small_dag", "parallel_swarm"}:
        if not decision.rejected_modes:
            raise ProtocolError(
                "Complex routing requires rejected simpler modes with explicit rationale"
            )
        rejected_mode_names = {entry["mode"] for entry in decision.rejected_modes}
        simpler_modes = {
            mode
            for mode, precedence in MODE_PRECEDENCE.items()
            if precedence < MODE_PRECEDENCE[decision.selected_mode]
        }
        if not simpler_modes & rejected_mode_names:
            raise ProtocolError(
                "Complex routing must reject at least one simpler mode explicitly"
            )
    if decision.selected_mode == "parallel_swarm" and decision.estimated_coordination_ratio > 0.25:
        raise ProtocolError(
            "parallel_swarm routing decision must not exceed coordination ratio threshold"
        )


def _validate_advisor_gate_decision(data: dict[str, Any]) -> None:
    invoked = data.get("invoked")
    if not isinstance(invoked, bool):
        raise ProtocolError("Routing decision advisor_gate_decision.invoked must be boolean")
    _as_string(data, "policy_version")
    reason = data.get("reason", [])
    if not isinstance(reason, list) or not all(isinstance(item, str) and item for item in reason):
        raise ProtocolError("Routing decision advisor_gate_decision.reason must be a list of strings")
    _as_string(data, "decision_basis")


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Routing decision field {key!r} must be a non-empty string")
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
        raise ProtocolError(f"Routing decision field {key!r} must be a list of strings")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Routing decision field {key!r} must be an object")
    return value


def _as_rejected_modes(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ProtocolError("Routing decision rejected_modes must be a list")
    modes: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ProtocolError("Routing decision rejected_modes entries must be objects")
        mode = _as_string(item, "mode")
        rejected_because = _as_string(item, "rejected_because")
        modes.append({"mode": mode, "rejected_because": rejected_because})
    return modes


def _as_float(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)):
        raise ProtocolError(f"Routing decision field {key!r} must be numeric")
    return float(value)
