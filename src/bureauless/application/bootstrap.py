from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from ..errors import ProtocolError
from ..protocol.bootstrap import (
    InitialControlPlaneProposal,
    accepts_initial_control_plane,
    collect_initial_control_plane_errors,
    load_initial_control_plane_proposal,
    validate_initial_control_plane_requirements,
    workflow_to_dict,
)
from ..protocol.harness import Ledger, Mission, Workflow
from ..protocol.ledger import append_ledger_event
from ..protocol.routing import RoutingDecision
from ..protocol.results import ResultProposal


@dataclass(frozen=True)
class BootstrapAcceptance:
    ledger: Ledger
    workflow: Workflow
    routing_decision: RoutingDecision
    worker_bindings: dict[str, dict[str, str]]
    proposal_path: Path
    workflow_path: Path


def accept_initial_control_plane(
    workspace: Path,
    mission: Mission,
    ledger: Ledger,
    result: ResultProposal,
    *,
    session_id: str,
    requirements: dict[str, Any] | None = None,
    allowed_agent_ids: set[str] | None = None,
    allowed_models: set[str] | None = None,
) -> BootstrapAcceptance:
    if result.status not in {"completed", "completed_with_proposal"}:
        raise ProtocolError("Bootstrap orchestrator result must be completed")
    if result.emitted_events != ["control_plane_complete"]:
        raise ProtocolError("Bootstrap orchestrator result must emit control_plane_complete only")
    intents = result.control_intents
    if len(intents) != 2:
        raise ProtocolError("Bootstrap requires proposal and explicit acceptance intents")
    errors = collect_initial_control_plane_errors(
        intents[0],
        mission,
        allowed_agent_ids=allowed_agent_ids,
        allowed_models=allowed_models,
    )
    if errors:
        raise ProtocolError("Initial control-plane proposal rejected:\n- " + "\n- ".join(errors))
    proposal = load_initial_control_plane_proposal(intents[0], mission)
    validate_initial_control_plane_requirements(proposal, requirements)
    if not accepts_initial_control_plane(intents[1], proposal.proposal_id):
        raise ProtocolError("Bootstrap acceptance must explicitly reference the proposal")

    root = workspace.resolve()
    proposal_path = root / "generated" / "control-plane" / f"{proposal.proposal_id}.yaml"
    accepted_path = root / "workflows" / f"{proposal.workflow.workflow_id}.accepted.yaml"
    _write_immutable_yaml(proposal_path, proposal.to_dict())
    proposal_event = {
        "event_id": f"event-{proposal.proposal_id}",
        "event_type": "initial_control_plane_proposed",
        "mission_id": mission.mission_id,
        "proposal_id": proposal.proposal_id,
        "source_session_id": session_id,
        "source_agent_id": result.agent_id,
        "source_model": result.effective_model,
        "source_provider": result.effective_provider,
        "acceptance_requirements": requirements or {},
        "proposal_path": proposal_path.relative_to(root).as_posix(),
        "proposal": proposal.to_dict(),
    }
    proposed = append_ledger_event(ledger, proposal_event)
    accepted_workflow = replace(proposal.workflow, status="accepted")
    _write_immutable_yaml(accepted_path, workflow_to_dict(accepted_workflow))
    accepted_event = {
        "event_id": f"event-{proposal.proposal_id}-accepted",
        "event_type": "initial_control_plane_accepted",
        "mission_id": mission.mission_id,
        "source_event_id": proposal_event["event_id"],
        "actor": "orchestrator",
        "source_session_id": session_id,
        "workflow_path": accepted_path.relative_to(root).as_posix(),
        "worker_bindings": [binding.to_dict() for binding in proposal.worker_bindings],
    }
    accepted = append_ledger_event(proposed, accepted_event)
    accepted = replace(accepted, current_plan_ref=accepted_event["workflow_path"])
    return BootstrapAcceptance(
        ledger=accepted,
        workflow=accepted_workflow,
        routing_decision=proposal.routing_decision,
        worker_bindings={
            binding.node_id: {
                "agent_id": binding.agent_id,
                "model": binding.model,
                "role": binding.role,
            }
            for binding in proposal.worker_bindings
        },
        proposal_path=proposal_path,
        workflow_path=accepted_path,
    )


def _write_immutable_yaml(path: Path, payload: dict[str, Any]) -> None:
    content = yaml.safe_dump(payload, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ProtocolError(f"Immutable bootstrap artifact differs: {path}")
    path.write_text(content, encoding="utf-8")
