from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ..errors import ProtocolError
from ..protocol.advisors import (
    AdvisorGateDecision,
    AdvisorInvocationRecord,
    AdvisorOutcome,
    AdvisorRecommendation,
    load_advisor_invocation,
    load_advisor_outcome,
    load_advisor_recommendation,
)
from ..protocol.harness import Ledger, Workflow, load_workflow
from .replay import replay_workflow


@dataclass(frozen=True)
class AdvisorOutcomeScore:
    advisor_outcome_id: str
    score_status: str
    classification: str | None
    reasons: list[str]
    source_decision_type: str
    invoked: bool | None
    recommendation_applied: bool | None
    mission_complete: bool | None
    review_rejections: int
    rework_count: int | None
    duplicate_context_observed: bool | None
    budget_variance_usd: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisor_outcome_id": self.advisor_outcome_id,
            "score_status": self.score_status,
            "classification": self.classification,
            "reasons": self.reasons,
            "source_decision_type": self.source_decision_type,
            "invoked": self.invoked,
            "recommendation_applied": self.recommendation_applied,
            "mission_complete": self.mission_complete,
            "review_rejections": self.review_rejections,
            "rework_count": self.rework_count,
            "duplicate_context_observed": self.duplicate_context_observed,
            "budget_variance_usd": self.budget_variance_usd,
        }


AdvisorRunner = Callable[[AdvisorGateDecision, dict[str, Any]], dict[str, Any]]


def evaluate_advisor_policy(facts: dict[str, Any]) -> AdvisorGateDecision:
    triggers: list[str] = []
    if _fact_int(facts, "node_count") >= 5:
        triggers.append("node_count >= 5")
    if _fact_int(facts, "parallel_width") >= 3:
        triggers.append("parallel_width >= 3")
    if _fact_int(facts, "high_risk_node_count") >= 1:
        triggers.append("high_risk_node_count >= 1")
    if _fact_int(facts, "large_model_node_count") >= 2:
        triggers.append("large_model_node_count >= 2")
    if _fact_int(facts, "review_or_human_gate_count") >= 2:
        triggers.append("review_or_human_gate_count >= 2")
    if _fact_int(facts, "estimated_total_tokens") >= 80000:
        triggers.append("estimated_total_tokens >= 80000")
    if facts.get("broadcast_policy") == "full_ledger":
        triggers.append("broadcast_policy == full_ledger")
    if facts.get("touched_file_overlap") == "high":
        triggers.append("touched_file_overlap == high")
    if facts.get("unknown_model_prices") is True and _fact_int(facts, "model_count") >= 2:
        triggers.append("unknown_model_prices == true and model_count >= 2")
    if (
        facts.get("commit_or_merge_action") is True
        and facts.get("review_or_approval_gate_present") is not True
    ):
        triggers.append("commit_or_merge_action without review_or_approval_gate")

    if triggers:
        advisor_tokens = _fact_int(facts, "advisor_expected_tokens") or 3300
        estimated_savings = max(
            _fact_int(facts, "estimated_savings_tokens"),
            _fact_int(facts, "estimated_context_fanout_tokens"),
            advisor_tokens * 2 + 1,
        )
        return AdvisorGateDecision(
            invoked=True,
            advisor="cost_risk_analyst",
            policy_version="0.1",
            reason=triggers,
            estimated_advisor_tokens=advisor_tokens,
            estimated_savings_tokens=estimated_savings,
            confidence="low",
            decision_basis="first_run_heuristic",
        )

    skip_reasons = []
    if _fact_int(facts, "node_count") <= 2:
        skip_reasons.append("node_count <= 2")
    if facts.get("risk_level", "low") == "low":
        skip_reasons.append("risk_level == low")
    if _fact_int(facts, "parallel_width") <= 1:
        skip_reasons.append("parallel_width <= 1")
    if facts.get("commit_or_merge_action") is not True:
        skip_reasons.append("no_commit_or_merge_action == true")
    return AdvisorGateDecision(
        invoked=False,
        policy_version="0.1",
        reason=skip_reasons or ["no_advisor_trigger_matched"],
        decision_basis="first_run_heuristic",
    )


def run_advisor_invocation(
    decision: AdvisorGateDecision,
    facts: dict[str, Any],
    *,
    runner: AdvisorRunner,
    invocation_id: str,
    gate_decision_ref: str,
    recommendation_ref: str,
    started_at: str | None = None,
) -> tuple[AdvisorRecommendation, AdvisorInvocationRecord]:
    if not decision.invoked or decision.advisor is None:
        raise ProtocolError("Advisor invocation requires an invoked gate decision")
    started = started_at or datetime.now(timezone.utc).isoformat()
    result = runner(decision, dict(facts))
    if not isinstance(result, dict):
        raise ProtocolError("Advisor runner result must be an object")
    recommendation_data = result.get("recommendation")
    if not isinstance(recommendation_data, dict):
        raise ProtocolError("Advisor runner result requires recommendation")
    recommendation = load_advisor_recommendation(recommendation_data)
    if recommendation.advisor != decision.advisor:
        raise ProtocolError("Advisor recommendation advisor does not match gate decision")
    invocation = load_advisor_invocation(
        {
            "invocation_id": invocation_id,
            "advisor": decision.advisor,
            "status": "completed",
            "gate_decision_ref": gate_decision_ref,
            "recommendation_ref": recommendation_ref,
            "telemetry_mode": result.get("telemetry_mode"),
            "token_usage": result.get("token_usage"),
            "cost_usd": result.get("cost_usd"),
            "started_at": started,
            "finished_at": result.get("finished_at")
            or datetime.now(timezone.utc).isoformat(),
            "capability_scope": result.get("capability_scope"),
        }
    )
    return recommendation, invocation


def build_scored_advisor_outcome(
    decision: AdvisorGateDecision,
    *,
    outcome_id: str,
    mission_id: str,
    workflow_id: str,
    source_decision_ref: str,
    advisor_decision_ref: str,
    actual_total_tokens: int,
    rework_count: int,
    broadcast_tokens: int,
    duplicate_context_observed: bool,
    recommendation_applied: bool | None = None,
    advisor_recommendation_ref: str | None = None,
    advisor_invocation_ref: str | None = None,
    invocation: AdvisorInvocationRecord | None = None,
) -> AdvisorOutcome:
    negative_signals = rework_count > 0 or duplicate_context_observed
    if decision.invoked:
        if invocation is None:
            raise ProtocolError("Invoked advisor outcome requires invocation evidence")
        if advisor_recommendation_ref is None or advisor_invocation_ref is None:
            raise ProtocolError("Invoked advisor outcome requires recommendation and invocation refs")
        if recommendation_applied is None:
            raise ProtocolError("Invoked advisor outcome requires recommendation disposition")
        classification = (
            "good_call" if recommendation_applied and not negative_signals else "bad_call"
        )
        actual_advisor_tokens = invocation.total_tokens
        actual_advisor_cost_usd = invocation.cost_usd
    else:
        classification = "missed_call" if negative_signals else "good_skip"
        actual_advisor_tokens = 0
        actual_advisor_cost_usd = 0.0
    return load_advisor_outcome(
        {
            "decision_type": "advisor_outcome",
            "outcome_id": outcome_id,
            "mission_id": mission_id,
            "workflow_id": workflow_id,
            "status": "scored",
            "source_decision_type": "routing_decision",
            "source_decision_ref": source_decision_ref,
            "advisor_decision_ref": advisor_decision_ref,
            "advisor_recommendation_ref": advisor_recommendation_ref,
            "advisor_invocation_ref": advisor_invocation_ref,
            "recommendation_applied": recommendation_applied,
            "classification": classification,
            "actual_advisor_tokens": actual_advisor_tokens,
            "actual_advisor_cost_usd": actual_advisor_cost_usd,
            "actual_total_tokens": actual_total_tokens,
            "rework_count": rework_count,
            "broadcast_tokens": broadcast_tokens,
            "duplicate_context_observed": duplicate_context_observed,
            "notes": "Scored from deterministic advisor policy and observed run signals.",
        }
    )


def summarize_advisor_scores(
    ledger: Ledger,
    *,
    workflow: Workflow | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    mission_complete = _mission_complete(ledger, workflow, artifact_root)
    review_rejections = _review_rejection_count(ledger)
    latest_events = _latest_advisor_outcome_events(ledger)
    scores = [
        _score_advisor_outcome_event(
            event,
            mission_complete=mission_complete,
            review_rejections=review_rejections,
            artifact_root=artifact_root,
        )
        for _outcome_id, event in sorted(latest_events.items())
    ]
    classification_counts = {
        "good_call": 0,
        "bad_call": 0,
        "good_skip": 0,
        "missed_call": 0,
    }
    insufficient_evidence_count = 0
    for score in scores:
        if score.score_status == "scored" and score.classification is not None:
            classification_counts[score.classification] += 1
        else:
            insufficient_evidence_count += 1
    return {
        "scores": [score.to_dict() for score in scores],
        "classification_counts": classification_counts,
        "insufficient_evidence_count": insufficient_evidence_count,
    }


def _score_advisor_outcome_event(
    event: dict[str, Any],
    *,
    mission_complete: bool | None,
    review_rejections: int,
    artifact_root: Path | None,
) -> AdvisorOutcomeScore:
    advisor_outcome_id = _string_or_unknown(event.get("advisor_outcome_id"))
    source_decision_type = _string_or_unknown(event.get("source_decision_type"))
    reasons: list[str] = []
    if mission_complete is not True:
        reasons.append("mission_not_complete")
    invoked = _load_advisor_invoked(event.get("advisor_decision_ref"), artifact_root)
    if invoked is None:
        reasons.append("advisor_decision_unavailable")
    rework_count = _int_or_none(event.get("rework_count"))
    recommendation_applied = _bool_or_none(event.get("recommendation_applied"))
    actual_advisor_tokens = _int_or_none(event.get("actual_advisor_tokens"))
    actual_advisor_cost_usd = _float_or_none(event.get("actual_advisor_cost_usd"))
    if invoked is True and recommendation_applied is None:
        reasons.append("recommendation_disposition_missing")
    if invoked is True and (actual_advisor_tokens is None or actual_advisor_cost_usd is None):
        reasons.append("advisor_cost_evidence_missing")
    duplicate_context_observed = _bool_or_none(event.get("duplicate_context_observed"))
    price_snapshot = event.get("price_snapshot_attribution")
    budget_variance_usd = None
    if isinstance(price_snapshot, dict):
        budget_variance_usd = _float_or_none(price_snapshot.get("cost_delta_usd"))
    if rework_count is None and duplicate_context_observed is None and budget_variance_usd is None:
        reasons.append("post_run_signals_missing")

    if reasons:
        return AdvisorOutcomeScore(
            advisor_outcome_id=advisor_outcome_id,
            score_status="insufficient_evidence",
            classification=None,
            reasons=reasons,
            source_decision_type=source_decision_type,
            invoked=invoked,
            recommendation_applied=recommendation_applied,
            mission_complete=mission_complete,
            review_rejections=review_rejections,
            rework_count=rework_count,
            duplicate_context_observed=duplicate_context_observed,
            budget_variance_usd=budget_variance_usd,
        )

    negative_signals = (
        (rework_count or 0) > 0
        or duplicate_context_observed is True
        or review_rejections > 0
        or (budget_variance_usd is not None and budget_variance_usd > 0)
    )

    if invoked:
        useful = recommendation_applied is True and not negative_signals
        classification = "good_call" if useful else "bad_call"
        if useful:
            score_reasons = ["advisor_recommendation_applied_and_post_run_signals_are_clean"]
        elif recommendation_applied is not True:
            score_reasons = ["advisor_invoked_but_recommendation_not_applied"]
        else:
            score_reasons = ["advisor_invoked_and_post_run_overhead_observed"]
    else:
        classification = "missed_call" if negative_signals else "good_skip"
        score_reasons = (
            ["advisor_skipped_and_avoidable_waste_observed"]
            if negative_signals
            else ["advisor_skipped_and_no_avoidable_waste_observed"]
        )
    return AdvisorOutcomeScore(
        advisor_outcome_id=advisor_outcome_id,
        score_status="scored",
        classification=classification,
        reasons=score_reasons,
        source_decision_type=source_decision_type,
        invoked=invoked,
        recommendation_applied=recommendation_applied,
        mission_complete=mission_complete,
        review_rejections=review_rejections,
        rework_count=rework_count,
        duplicate_context_observed=duplicate_context_observed,
        budget_variance_usd=budget_variance_usd,
    )


def _latest_advisor_outcome_events(ledger: Ledger) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in ledger.event_log:
        if event.get("event_type") != "advisor_outcome_recorded":
            continue
        outcome_id = _string_or_none(event.get("advisor_outcome_id"))
        if outcome_id is None:
            continue
        latest[outcome_id] = event
    return latest


def _mission_complete(
    ledger: Ledger,
    workflow: Workflow | None,
    artifact_root: Path | None,
) -> bool | None:
    resolved_workflow = workflow
    if resolved_workflow is None:
        resolved_workflow = _load_workflow_from_ledger_ref(ledger, artifact_root)
    if resolved_workflow is None:
        return None
    return replay_workflow(resolved_workflow, ledger).terminal_complete


def _load_workflow_from_ledger_ref(
    ledger: Ledger,
    artifact_root: Path | None,
) -> Workflow | None:
    base = artifact_root
    if base is None:
        return None
    workflow_path = (base / ledger.current_plan_ref).resolve()
    if not workflow_path.exists():
        return None
    return load_workflow(workflow_path)


def _review_rejection_count(ledger: Ledger) -> int:
    return sum(
        1
        for event in ledger.event_log
        if event.get("event_type") == "review_decision_recorded"
        and event.get("verdict") in {"rejected", "changes_requested"}
    )


def _load_advisor_invoked(advisor_decision_ref: Any, artifact_root: Path | None) -> bool | None:
    if artifact_root is None or not isinstance(advisor_decision_ref, str) or not advisor_decision_ref:
        return None
    decision_path = (artifact_root / advisor_decision_ref).resolve()
    if not decision_path.exists():
        return None
    with decision_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        return None
    gate = data.get("advisor_gate_decision", data)
    if not isinstance(gate, dict):
        return None
    invoked = gate.get("invoked")
    return invoked if isinstance(invoked, bool) else None


def _string_or_unknown(value: Any) -> str:
    return value if isinstance(value, str) and value else "unknown"


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _fact_int(facts: dict[str, Any], field: str) -> int:
    value = facts.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
