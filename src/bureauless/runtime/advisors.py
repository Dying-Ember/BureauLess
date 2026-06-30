from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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
            "mission_complete": self.mission_complete,
            "review_rejections": self.review_rejections,
            "rework_count": self.rework_count,
            "duplicate_context_observed": self.duplicate_context_observed,
            "budget_variance_usd": self.budget_variance_usd,
        }


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
        classification = "bad_call" if negative_signals else "good_call"
        score_reasons = (
            ["advisor_invoked_and_post_run_overhead_observed"]
            if negative_signals
            else ["advisor_invoked_and_post_run_signals_are_clean"]
        )
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
