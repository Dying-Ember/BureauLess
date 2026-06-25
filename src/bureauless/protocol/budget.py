from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..core import ProtocolError


@dataclass(frozen=True)
class CostEstimate:
    cost_usd: float | None
    source: str
    confidence: str
    pricing_model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_usd": self.cost_usd,
            "source": self.source,
            "confidence": self.confidence,
            "pricing_model": self.pricing_model,
        }


@dataclass(frozen=True)
class PreDispatchPolicyDecision:
    decision: str
    selected_mode: str
    recommended_mode: str
    budget_state: str
    triggered_rules: list[str]
    reasons: list[str]
    observed_evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "selected_mode": self.selected_mode,
            "recommended_mode": self.recommended_mode,
            "budget_state": self.budget_state,
            "triggered_rules": self.triggered_rules,
            "reasons": self.reasons,
            "observed_evidence": self.observed_evidence,
        }


def load_price_snapshot(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ProtocolError("Price snapshot document must be an object")
    if "models" not in data or not isinstance(data["models"], dict):
        raise ProtocolError("Price snapshot must contain a models mapping")
    return data


def estimate_cost_from_snapshot(
    snapshot: dict[str, Any],
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> CostEstimate:
    model_data = snapshot["models"].get(model)
    if not isinstance(model_data, dict):
        return CostEstimate(
            cost_usd=None,
            source="price_snapshot_missing_model",
            confidence="none",
            pricing_model="unknown",
        )

    pricing_model = _string_or_unknown(model_data.get("pricing_model"))
    source = _string_or_unknown(model_data.get("source"), snapshot.get("source", "unknown"))
    confidence = _string_or_unknown(model_data.get("confidence"), "unknown")

    if pricing_model != "token":
        return CostEstimate(
            cost_usd=None,
            source=source,
            confidence=confidence,
            pricing_model=pricing_model,
        )

    if input_tokens is None or output_tokens is None:
        return CostEstimate(
            cost_usd=None,
            source=source,
            confidence="none",
            pricing_model=pricing_model,
        )

    input_per_million = _float_or_none(model_data.get("input_per_million"))
    output_per_million = _float_or_none(model_data.get("output_per_million"))
    if input_per_million is None or output_per_million is None:
        return CostEstimate(
            cost_usd=None,
            source=source,
            confidence="none",
            pricing_model=pricing_model,
        )

    cost_usd = (input_tokens / 1_000_000) * input_per_million + (
        output_tokens / 1_000_000
    ) * output_per_million
    return CostEstimate(
        cost_usd=round(cost_usd, 6),
        source=source,
        confidence=confidence,
        pricing_model=pricing_model,
    )


def evaluate_pre_dispatch_policy(
    mission_budget: dict[str, Any],
    routing_facts: dict[str, Any],
    observed_budget: dict[str, Any],
) -> PreDispatchPolicyDecision:
    selected_mode = _string_or_unknown(routing_facts.get("selected_mode"), "single_agent")
    recommended_mode = selected_mode
    triggered_rules: list[str] = []
    reasons: list[str] = []
    budget_state = _budget_state(mission_budget, routing_facts, observed_budget, triggered_rules, reasons)

    if _stop_and_ask_human(routing_facts, budget_state):
        triggered_rules.append("stop_and_ask_human_if")
        reasons.append("automatic dispatch must stop for human review")
        return PreDispatchPolicyDecision(
            decision="reject",
            selected_mode=selected_mode,
            recommended_mode="stop_and_ask_human",
            budget_state=budget_state,
            triggered_rules=_dedupe(triggered_rules),
            reasons=_dedupe(reasons),
            observed_evidence=_observed_evidence(mission_budget, routing_facts, observed_budget),
        )

    if selected_mode == "parallel_swarm" and _reject_parallel_swarm(routing_facts):
        triggered_rules.append("reject_parallel_swarm_if")
        recommended_mode = _fallback_mode(routing_facts)
        reasons.append(f"parallel_swarm is not justified; downgrade to {recommended_mode}")
    elif selected_mode == "small_dag" and _reject_small_dag(routing_facts):
        triggered_rules.append("reject_small_dag_if")
        recommended_mode = _fallback_mode(routing_facts)
        reasons.append(f"small_dag is not justified; downgrade to {recommended_mode}")
    elif selected_mode == "single_agent" and _upgrade_review(routing_facts):
        triggered_rules.append("upgrade_to_single_agent_with_review_if")
        recommended_mode = "single_agent_with_review"
        reasons.append("single_agent is below the required review floor")

    if budget_state == "soft_limit" and selected_mode in {"small_dag", "parallel_swarm"}:
        triggered_rules.append("budget_soft_limit_reached")
        recommended_mode = _fallback_mode(routing_facts)
        reasons.append(f"soft budget pressure favors simpler mode {recommended_mode}")

    decision = "allow"
    if budget_state == "hard_limit":
        decision = "reject"
        reasons.append("projected usage would exceed a hard budget limit")
    elif recommended_mode != selected_mode:
        decision = "adjust"

    return PreDispatchPolicyDecision(
        decision=decision,
        selected_mode=selected_mode,
        recommended_mode=recommended_mode,
        budget_state=budget_state,
        triggered_rules=_dedupe(triggered_rules),
        reasons=_dedupe(reasons),
        observed_evidence=_observed_evidence(mission_budget, routing_facts, observed_budget),
    )


def _string_or_unknown(value: Any, default: str = "unknown") -> str:
    return value if isinstance(value, str) and value else default


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _bool(value: Any) -> bool:
    return value is True


def _budget_state(
    mission_budget: dict[str, Any],
    routing_facts: dict[str, Any],
    observed_budget: dict[str, Any],
    triggered_rules: list[str],
    reasons: list[str],
) -> str:
    soft_limit_ratio = _float_or_none(mission_budget.get("soft_limit_ratio")) or 0.8
    observed_tokens = _int_or_none(observed_budget.get("total_tokens_used")) or 0
    predicted_tokens = _int_or_none(routing_facts.get("predicted_total_tokens"))
    observed_cost = _float_or_none(observed_budget.get("known_cost_usd_total")) or 0.0
    predicted_cost = _float_or_none(routing_facts.get("predicted_cost_usd"))

    max_total_tokens = _int_or_none(mission_budget.get("max_total_tokens"))
    if max_total_tokens is not None and predicted_tokens is not None:
        projected_tokens = observed_tokens + predicted_tokens
        if projected_tokens > max_total_tokens:
            triggered_rules.append("budget_hard_limit_tokens")
            reasons.append("projected tokens exceed max_total_tokens")
            return "hard_limit"
        if projected_tokens >= int(max_total_tokens * soft_limit_ratio):
            triggered_rules.append("budget_soft_limit_tokens")
            reasons.append("projected tokens approach max_total_tokens")
            return "soft_limit"

    max_usd = _float_or_none(mission_budget.get("max_usd"))
    if max_usd is not None and predicted_cost is not None:
        projected_cost = observed_cost + predicted_cost
        if projected_cost > max_usd:
            triggered_rules.append("budget_hard_limit_usd")
            reasons.append("projected cost exceeds max_usd")
            return "hard_limit"
        if projected_cost >= max_usd * soft_limit_ratio:
            triggered_rules.append("budget_soft_limit_usd")
            reasons.append("projected cost approaches max_usd")
            return "soft_limit"

    max_coordination_ratio = _float_or_none(mission_budget.get("max_coordination_ratio"))
    predicted_coordination_ratio = _float_or_none(routing_facts.get("coordination_ratio_prediction"))
    if (
        max_coordination_ratio is not None
        and predicted_coordination_ratio is not None
        and predicted_coordination_ratio > max_coordination_ratio
    ):
        triggered_rules.append("budget_coordination_ratio")
        reasons.append("predicted coordination ratio exceeds mission budget")
        return "soft_limit"

    return "within_limits"


def _stop_and_ask_human(routing_facts: dict[str, Any], budget_state: str) -> bool:
    return (
        _bool(routing_facts.get("user_intent_unclear_and_side_effectful"))
        or _bool(routing_facts.get("required_permission_missing"))
        or _bool(routing_facts.get("policy_conflict_detected"))
        or _bool(routing_facts.get("budget_hard_limit_would_be_exceeded"))
        or budget_state == "hard_limit"
    )


def _upgrade_review(routing_facts: dict[str, Any]) -> bool:
    risk_level = _string_or_unknown(routing_facts.get("risk_level"), "low")
    return (
        risk_level in {"medium", "high"}
        or _bool(routing_facts.get("touches_protected_files"))
        or _bool(routing_facts.get("external_side_effect"))
        or _bool(routing_facts.get("commit_or_merge_action"))
        or _bool(routing_facts.get("destructive_action_possible"))
    )


def _upgrade_small_dag(routing_facts: dict[str, Any]) -> bool:
    independent_subtasks = _int_or_none(routing_facts.get("independent_subtasks")) or 0
    shared_context_tokens = _int_or_none(routing_facts.get("shared_context_tokens")) or 0
    estimated_parallel_savings_tokens = (
        _int_or_none(routing_facts.get("estimated_parallel_savings_tokens")) or 0
    )
    merge_complexity = _string_or_unknown(routing_facts.get("merge_complexity"), "unknown")
    return (
        independent_subtasks >= 3
        and shared_context_tokens < estimated_parallel_savings_tokens
        and merge_complexity != "high"
        and (
            _bool(routing_facts.get("specialist_roles_reduce_risk"))
            or _bool(routing_facts.get("context_isolation_reduces_total_tokens"))
            or _bool(routing_facts.get("staged_review_required"))
        )
    )


def _reject_small_dag(routing_facts: dict[str, Any]) -> bool:
    node_count = _int_or_none(routing_facts.get("node_count")) or 0
    risk_level = _string_or_unknown(routing_facts.get("risk_level"), "low")
    coordination_ratio_prediction = _float_or_none(routing_facts.get("coordination_ratio_prediction")) or 0.0
    merge_complexity = _string_or_unknown(routing_facts.get("merge_complexity"), "unknown")
    shared_context_tokens = _int_or_none(routing_facts.get("shared_context_tokens")) or 0
    estimated_parallel_savings_tokens = (
        _int_or_none(routing_facts.get("estimated_parallel_savings_tokens")) or 0
    )
    return (
        (node_count <= 2 and risk_level == "low")
        or coordination_ratio_prediction > 0.25
        or merge_complexity == "high"
        or shared_context_tokens >= estimated_parallel_savings_tokens
    )


def _reject_parallel_swarm(routing_facts: dict[str, Any]) -> bool:
    shared_file_overlap = _string_or_unknown(routing_facts.get("shared_file_overlap"), "unknown")
    budget_confidence = _string_or_unknown(routing_facts.get("budget_confidence"), "unknown")
    coordination_ratio_prediction = _float_or_none(routing_facts.get("coordination_ratio_prediction")) or 0.0
    merge_complexity = _string_or_unknown(routing_facts.get("merge_complexity"), "unknown")
    expected_wall_clock_savings = _string_or_unknown(
        routing_facts.get("expected_wall_clock_savings"),
        "unknown",
    )
    return (
        shared_file_overlap == "high"
        or budget_confidence == "low"
        or coordination_ratio_prediction > 0.25
        or merge_complexity != "low"
        or expected_wall_clock_savings != "material"
    )


def _fallback_mode(routing_facts: dict[str, Any]) -> str:
    if _upgrade_small_dag(routing_facts) and not _reject_small_dag(routing_facts):
        return "small_dag"
    if _upgrade_review(routing_facts):
        return "single_agent_with_review"
    return "single_agent"


def _observed_evidence(
    mission_budget: dict[str, Any],
    routing_facts: dict[str, Any],
    observed_budget: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mission_budget": mission_budget,
        "routing_facts": routing_facts,
        "observed_budget": observed_budget,
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
