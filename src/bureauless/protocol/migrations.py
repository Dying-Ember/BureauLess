from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..errors import ProtocolError
from .harness import STRICT_ACCEPTANCE_LEDGER_VERSION, Ledger, Workflow
from .ledger import rebuild_ledger_projection


@dataclass(frozen=True)
class LedgerV2Migration:
    ledger: Ledger
    report: dict[str, Any]


def migrate_ledger_to_v2(workflow: Workflow, ledger: Ledger) -> LedgerV2Migration:
    if ledger.ledger_version != 1:
        raise ProtocolError("Ledger v2 migration requires ledger_version 1 input")
    decided_assignments = {
        event.get("assignment_id")
        for event in ledger.event_log
        if event.get("event_type") == "node_outcome_decided"
        and isinstance(event.get("assignment_id"), str)
    }
    quarantined: list[dict[str, Any]] = []
    preserved: list[str] = []
    for event in ledger.event_log:
        if event.get("event_type") != "result_submitted":
            continue
        assignment_id = event.get("assignment_id")
        if not isinstance(assignment_id, str) or not assignment_id:
            continue
        if assignment_id in decided_assignments:
            preserved.append(assignment_id)
            continue
        result = event.get("result")
        claimed = result.get("emitted_events", []) if isinstance(result, dict) else []
        quarantined.append(
            {
                "assignment_id": assignment_id,
                "result_event_id": event.get("event_id"),
                "claimed_event_types": [
                    item for item in claimed if isinstance(item, str) and item
                ],
                "reason": "requires_acceptance_review",
            }
        )

    migrated = rebuild_ledger_projection(
        replace(ledger, ledger_version=STRICT_ACCEPTANCE_LEDGER_VERSION)
    )
    return LedgerV2Migration(
        ledger=migrated,
        report={
            "from_version": 1,
            "to_version": STRICT_ACCEPTANCE_LEDGER_VERSION,
            "workflow_id": workflow.workflow_id,
            "source_event_count": len(ledger.event_log),
            "preserved_decision_assignments": sorted(set(preserved)),
            "quarantined_results": quarantined,
        },
    )
