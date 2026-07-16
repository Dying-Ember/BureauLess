from pathlib import Path
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import importlib
import os
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import pytest
import yaml

from bureauless.agents import (
    CommandOutput,
    assess_agent_compatibility,
    assess_dispatch_readiness,
    doctor_agent,
    list_agent_compatibility,
    list_agent_specs,
    resolve_agent_binding,
)
from bureauless.cli import main
from bureauless.cli.main import (
    _control_plane_result_example,
    prepare_demo_workspace,
    prepare_mutation_demo_workspace,
    run_advisor_policy_demo,
    run_live_demo,
)
from bureauless.application.mutation_retry_demo import run_mutation_retry_demo
from bureauless.core import ProtocolError
from bureauless.application.acceptance import (
    decide_staged_result,
    stage_result,
    stage_session_record,
)
from bureauless.application.bootstrap import accept_initial_control_plane
from bureauless.application.run_bundles import load_run_bundle
from bureauless.protocol import (
    append_ledger_event,
    apply_advisor_outcome,
    apply_review_decision,
    build_context_request,
    compile_context_capsule,
    compile_dispatch_packet,
    export_assignment,
    import_result_proposal,
    load_advisor_outcome,
    load_advisor_gate_decision,
    load_advisor_invocation,
    load_advisor_recommendation,
    load_context_request,
    load_context_request_intent,
    load_dispatch_packet,
    load_assignment,
    load_node_outcome,
    load_result_proposal,
    load_review_decision,
    load_routing_decision,
    load_turn_report,
    materialize_current_workflow,
    migrate_ledger_to_v2,
    node_outcome_from_session,
    render_assignment_prompt,
    resolve_context_request,
    sha256_file,
    validate_dispatch_packet,
    validate_routing_decision,
    verify_ledger_artifacts,
    write_ledger,
)
from bureauless.protocol.acceptance import DEFAULT_ACCEPTANCE_POLICY, AcceptancePolicy
from bureauless.protocol.artifacts import validate_artifact_record
from bureauless.protocol.bootstrap import collect_initial_control_plane_errors
from bureauless.protocol.budget import estimate_cost_from_snapshot, evaluate_pre_dispatch_policy, load_price_snapshot
from bureauless.protocol.harness import (
    Ledger,
    Workflow,
    compile_workflow,
    load_ledger,
    load_mission,
    load_workflow,
)
from bureauless.protocol.mutations import (
    build_trusted_workflow_mutation_proposal,
    validate_workflow_mutation_intent,
    validate_workflow_mutation_proposal,
)
from bureauless.protocol.results import intake_result_mutation_intent
from bureauless.protocol.results import ResultProposal
from bureauless.protocol.outcomes import build_node_outcome_decision_event
from bureauless.runtime import (
    build_mutation_supersession_events,
    evaluate_advisor_policy,
    evaluate_assignment_impacts,
    evaluate_gatekeeper,
    project_workflow_versions,
    replay_workflow,
    run_advisor_invocation,
    summarize_advisor_scores,
    summarize_metrics,
)
from bureauless.runtime.sessions import (
    ProviderUsageCapture,
    SessionRecord,
    apply_retry_policy,
    assess_workspace_isolation,
    build_assignment_created_event,
    build_session_terminal_event,
    cancel_session_record,
    classify_session_failure,
    create_session_spec,
    dispatch_session,
    import_session_record,
    load_session_record,
    package_session_result,
    reconstruct_dispatched_session,
    run_session,
    start_dispatch_session,
    supersede_session_record,
    load_provider_usage_capture,
    write_provider_usage_capture_artifact,
    _is_codex_native_progress_line,
    _run_live_process,
)


def _workflow(overrides: dict | None = None) -> Workflow:
    data = {
        "workflow_id": "test-workflow",
        "mission_id": "demo",
        "status": "accepted",
        "mode": "small_dag",
        "roles": {
            "coder": {
                "can_emit": ["patch_ready"],
                "can_consume": [],
            },
            "reviewer": {
                "can_emit": ["review_approved"],
                "can_consume": ["patch_ready"],
            },
            "committer": {
                "can_emit": ["commit_created"],
                "can_consume": ["patch_ready", "review_approved"],
            },
        },
        "events": {
            "patch_ready": {"producer_roles": ["coder"]},
            "review_approved": {"producer_roles": ["reviewer"]},
            "commit_created": {"producer_roles": ["committer"]},
        },
        "nodes": [
            {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
            {
                "id": "review",
                "role": "reviewer",
                "waits_for": {"all_of": ["patch_ready"]},
                "emits": ["review_approved"],
            },
            {
                "id": "commit",
                "role": "committer",
                "waits_for": {"all_of": ["patch_ready", "review_approved"]},
                "emits": ["commit_created"],
            },
        ],
        "terminal_events": ["commit_created"],
    }
    if overrides:
        data.update(overrides)
    return Workflow.from_dict(data)


def _dispatch_fixture(workflow, assignment, packet_id="packet-001"):
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    routing_decision = load_routing_decision(
        {
            "decision_type": "routing_decision",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "selected_mode": workflow.mode,
            "selection_policy_version": "test-v1",
            "triggered_rules": ["test_dispatch"],
            "rejected_modes": [
                {
                    "mode": "single_agent",
                    "rejected_because": "The test workflow preserves explicit staged nodes.",
                }
            ],
            "estimated_coordination_ratio": 0.1,
            "budget_confidence": "high",
            "reason": "Exercise the canonical dispatch bridge.",
            "advisor_gate_decision": {
                "invoked": False,
                "policy_version": "test-v1",
                "reason": ["fixture"],
                "decision_basis": "deterministic_fixture",
            },
        }
    )
    return mission, compile_dispatch_packet(
        mission,
        workflow,
        routing_decision,
        assignment,
        packet_id=packet_id,
    )


def _context_workflow() -> Workflow:
    return Workflow.from_dict(
        {
            "workflow_id": "context-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "inventory": {
                    "can_emit": ["inventory_ready"],
                    "can_consume": [],
                },
                "coder": {
                    "can_emit": ["patch_ready"],
                    "can_consume": [],
                },
                "reviewer": {
                    "can_emit": ["review_approved"],
                    "can_consume": ["patch_ready"],
                },
                "committer": {
                    "can_emit": ["commit_created"],
                    "can_consume": ["patch_ready", "review_approved"],
                },
            },
            "events": {
                "inventory_ready": {"producer_roles": ["inventory"]},
                "patch_ready": {"producer_roles": ["coder"]},
                "review_approved": {"producer_roles": ["reviewer"]},
                "commit_created": {"producer_roles": ["committer"]},
            },
            "nodes": [
                {"id": "inventory", "role": "inventory", "emits": ["inventory_ready"]},
                {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
                {
                    "id": "review",
                    "role": "reviewer",
                    "waits_for": {"all_of": ["patch_ready"]},
                    "emits": ["review_approved"],
                },
                {
                    "id": "commit",
                    "role": "committer",
                    "waits_for": {"all_of": ["patch_ready", "review_approved"]},
                    "emits": ["commit_created"],
                },
            ],
            "gates": [
                {
                    "id": "commit-gate",
                    "node_id": "commit",
                    "requires": {"all_of": ["patch_ready", "review_approved"]},
                }
            ],
            "terminal_events": ["commit_created"],
        }
    )


def _mutation_proposal(overrides: dict | None = None) -> dict:
    data = {
        "proposal_id": "mutation-001",
        "proposal_type": "workflow_mutation",
        "workflow_id": "test-workflow",
        "source": {
            "assignment_id": "assign-001",
            "session_id": "session-001",
            "actor": "worker",
        },
        "reason": "discovered_missing_dependency",
        "rationale": "Review needs a focused verification step before approval.",
        "proposed_changes": {
            "add_nodes": [
                {
                    "id": "verify",
                    "role": "reviewer",
                    "waits_for": {"all_of": ["implement.patch_ready"]},
                    "emits": ["review_approved"],
                }
            ],
            "add_edges": [
                {
                    "from_node": "verify",
                    "to_node": "commit",
                    "event": "review_approved",
                }
            ],
            "remove_edges": [],
            "supersede_assignments": ["assign-review-001"],
        },
        "evidence_refs": ["artifact-impact-report"],
        "requires_approval": "orchestrator",
    }
    if overrides:
        data.update(overrides)
    return data


def _mutation_intent(overrides: dict | None = None) -> dict:
    proposal = _mutation_proposal()
    data = {
        "intent_type": proposal["proposal_type"],
        "reason": proposal["reason"],
        "rationale": proposal["rationale"],
        "proposed_changes": proposal["proposed_changes"],
        "evidence_refs": proposal["evidence_refs"],
    }
    if overrides:
        data.update(overrides)
    return data


def _mutation_session_record(
    tmp_path: Path,
    assignment,
    intent: object,
    *,
    session_id: str = "session-001",
):
    workdir = tmp_path / session_id
    workdir.mkdir(parents=True)
    payload = yaml.safe_dump(
        {
            "status": "blocked",
            "emitted_events": [],
            "verification": {"status": "workflow_structure"},
            "control_intents": [intent],
        },
        sort_keys=False,
    ).strip()
    return run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=workdir,
            shell_command=f"cat <<'EOF'\n{payload}\nEOF",
            session_id=session_id,
        ),
        assignment,
    )


def _retry_record(
    assignment_id: str,
    *,
    status: str = "failed",
    reason: str = "deterministic_failure",
    verification_status: str | None = None,
    control_intents: list[dict] | None = None,
    extraction_status: str = "extracted",
    total_tokens: int = 1000,
) -> SessionRecord:
    result = None
    if verification_status is not None or control_intents:
        result = {
            "status": "blocked",
            "verification": {"status": verification_status or "not_run"},
            "control_intents": control_intents or [],
            "effective_model": "gpt-5",
            "effective_provider": "openai",
        }
    return SessionRecord(
        session_id=f"session-{assignment_id}",
        assignment_id=assignment_id,
        agent_id="codex-cli",
        status=status,
        started_at="2026-07-03T00:00:00+00:00",
        finished_at="2026-07-03T00:00:01+00:00",
        exit={"code": 1, "reason": reason},
        native_logs={"stdout": "", "stderr": reason},
        diff_refs=[],
        artifacts=[],
        workspace={},
        outcome_metrics={"total_tokens": total_tokens},
        extraction={"status": extraction_status, "warnings": []},
        result_proposal=result,
    )


def _empty_ledger() -> Ledger:
    return Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Test controlled workflow mutation.",
            "current_plan_ref": "test-workflow",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )


def _mutation_workflow() -> Workflow:
    return Workflow.from_dict(
        {
            "workflow_id": "test-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "producer": {
                    "can_emit": ["ready"],
                    "can_consume": ["done"],
                },
                "consumer": {
                    "can_emit": ["done"],
                    "can_consume": ["ready"],
                },
            },
            "events": {
                "ready": {"producer_roles": ["producer"]},
                "done": {"producer_roles": ["consumer"]},
            },
            "nodes": [
                {
                    "id": "start",
                    "role": "producer",
                    "waits_for": [],
                    "emits": ["ready"],
                },
                {
                    "id": "finish",
                    "role": "consumer",
                    "waits_for": [],
                    "emits": ["done"],
                },
            ],
            "gates": [],
            "terminal_events": ["done"],
        }
    )


def _impact_workflows() -> tuple[Workflow, Workflow]:
    base = {
        "workflow_id": "test-workflow",
        "mission_id": "demo",
        "mode": "small_dag",
        "roles": {
            "worker": {
                "can_emit": ["b_done", "c_done", "d_done", "x_done"],
                "can_consume": ["b_done", "c_done", "d_done", "x_done"],
            }
        },
        "events": {
            event: {"producer_roles": ["worker"]}
            for event in ("b_done", "c_done", "d_done", "x_done")
        },
        "gates": [],
        "terminal_events": ["d_done", "x_done"],
    }
    before = Workflow.from_dict(
        {
            **base,
            "nodes": [
                {"id": "B", "role": "worker", "waits_for": [], "emits": ["b_done"]},
                {
                    "id": "D",
                    "role": "worker",
                    "waits_for": ["B.b_done"],
                    "emits": ["d_done"],
                },
                {
                    "id": "E",
                    "role": "worker",
                    "waits_for": ["D.d_done"],
                    "emits": ["x_done"],
                },
                {"id": "X", "role": "worker", "waits_for": [], "emits": ["x_done"]},
            ],
        }
    )
    after = Workflow.from_dict(
        {
            **base,
            "nodes": [
                {"id": "B", "role": "worker", "waits_for": [], "emits": ["b_done"]},
                {
                    "id": "C",
                    "role": "worker",
                    "waits_for": ["B.b_done"],
                    "emits": ["c_done"],
                },
                {
                    "id": "D",
                    "role": "worker",
                    "waits_for": ["C.c_done"],
                    "emits": ["d_done"],
                },
                {
                    "id": "E",
                    "role": "worker",
                    "waits_for": ["D.d_done"],
                    "emits": ["x_done"],
                },
                {"id": "X", "role": "worker", "waits_for": [], "emits": ["x_done"]},
            ],
        }
    )
    return before, after


def _mutation_proposed_event() -> dict:
    return {
        "event_id": "event-mutation-001",
        "event_type": "workflow_mutation_proposed",
        "mission_id": "demo",
        "workflow_id": "test-workflow",
        "mutation_proposal": _mutation_proposal(),
    }


def _multi_version_replay_history() -> tuple[Workflow, Ledger, dict[str, str]]:
    initial = Workflow.from_dict(
        {
            "workflow_id": "test-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "worker": {
                    "can_emit": ["ready", "done"],
                    "can_consume": ["ready", "done"],
                },
            },
            "events": {
                "ready": {"producer_roles": ["worker"]},
                "done": {"producer_roles": ["worker"]},
            },
            "nodes": [
                {
                    "id": "start",
                    "role": "worker",
                    "waits_for": [],
                    "emits": ["ready"],
                },
                {
                    "id": "finish",
                    "role": "worker",
                    "waits_for": [],
                    "emits": ["done"],
                },
            ],
            "gates": [],
            "terminal_events": ["done"],
        }
    )
    ledger = replace(_empty_ledger(), ledger_version=3)
    cursors: dict[str, str] = {}

    finish_assignment = export_assignment(
        initial, ledger, "finish", assignment_id="assign-finish-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            initial,
            finish_assignment,
            "session-finish-001",
            "codex-cli",
        ),
        initial,
    )
    cursors["finish_assignment"] = ledger.event_log[-1]["event_id"]

    first_changes = {
        "add_nodes": [
            {
                "id": "verify",
                "role": "worker",
                "waits_for": [],
                "emits": ["ready"],
            }
        ],
        "add_edges": [{"from_node": "verify", "to_node": "finish", "event": "ready"}],
        "remove_edges": [],
        "supersede_assignments": [],
    }
    first_proposal = {
        **_mutation_proposed_event(),
        "mutation_proposal": _mutation_proposal(
            {
                "proposed_changes": first_changes,
                "evidence_refs": ["artifact-verify-gap"],
            }
        ),
    }
    ledger = append_ledger_event(ledger, first_proposal, initial)
    cursors["proposal_one"] = ledger.event_log[-1]["event_id"]
    first_acceptance = {
        "event_id": "event-mutation-accepted-001",
        "event_type": "workflow_mutation_accepted",
        "mission_id": initial.mission_id,
        "workflow_id": initial.workflow_id,
        "source_event_id": first_proposal["event_id"],
        "actor": "orchestrator",
        "applied_changes": first_changes,
    }
    ledger = append_ledger_event(ledger, first_acceptance, initial)
    cursors["acceptance_one"] = ledger.event_log[-1]["event_id"]

    first_workflow = materialize_current_workflow(initial, ledger)
    first_impacts = evaluate_assignment_impacts(
        initial, first_workflow, ledger, first_changes
    )
    for event in build_mutation_supersession_events(
        first_workflow, first_acceptance, first_impacts
    ):
        ledger = append_ledger_event(ledger, event, first_workflow)
    cursors["first_supersession"] = ledger.event_log[-1]["event_id"]

    rejected_changes = {
        "add_nodes": [
            {
                "id": "shadow",
                "role": "worker",
                "waits_for": [],
                "emits": ["ready"],
            }
        ],
        "add_edges": [{"from_node": "shadow", "to_node": "finish", "event": "ready"}],
        "remove_edges": [],
        "supersede_assignments": [],
    }
    rejected_proposal = {
        **_mutation_proposed_event(),
        "event_id": "event-mutation-002",
        "mutation_proposal": _mutation_proposal(
            {
                "proposal_id": "mutation-002",
                "proposed_changes": rejected_changes,
                "evidence_refs": ["artifact-shadow-rejected"],
            }
        ),
    }
    ledger = append_ledger_event(ledger, rejected_proposal, initial)
    cursors["proposal_two"] = ledger.event_log[-1]["event_id"]
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-rejected-002",
            "event_type": "workflow_mutation_rejected",
            "mission_id": initial.mission_id,
            "workflow_id": initial.workflow_id,
            "source_event_id": rejected_proposal["event_id"],
            "actor": "human",
            "reason": "No second structural change is needed.",
        },
        initial,
    )
    cursors["rejection_two"] = ledger.event_log[-1]["event_id"]

    verify_assignment = export_assignment(
        initial, ledger, "verify", assignment_id="assign-verify-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            first_workflow,
            verify_assignment,
            "session-verify-001",
            "codex-cli",
        ),
        first_workflow,
    )
    cursors["verify_assignment"] = ledger.event_log[-1]["event_id"]

    second_changes = {
        "add_nodes": [
            {
                "id": "audit",
                "role": "worker",
                "waits_for": [],
                "emits": ["ready"],
            }
        ],
        "add_edges": [{"from_node": "audit", "to_node": "verify", "event": "ready"}],
        "remove_edges": [],
        "supersede_assignments": [],
    }
    second_proposal = {
        **_mutation_proposed_event(),
        "event_id": "event-mutation-003",
        "mutation_proposal": _mutation_proposal(
            {
                "proposal_id": "mutation-003",
                "source": {
                    "assignment_id": "assign-verify-001",
                    "session_id": "session-verify-001",
                    "actor": "worker",
                },
                "proposed_changes": second_changes,
                "evidence_refs": ["artifact-audit-gap"],
            }
        ),
    }
    ledger = append_ledger_event(ledger, second_proposal, initial)
    cursors["proposal_three"] = ledger.event_log[-1]["event_id"]
    second_acceptance = {
        "event_id": "event-mutation-accepted-003",
        "event_type": "workflow_mutation_accepted",
        "mission_id": initial.mission_id,
        "workflow_id": initial.workflow_id,
        "source_event_id": second_proposal["event_id"],
        "actor": "orchestrator",
        "applied_changes": second_changes,
    }
    ledger = append_ledger_event(ledger, second_acceptance, initial)
    cursors["acceptance_three"] = ledger.event_log[-1]["event_id"]

    second_workflow = materialize_current_workflow(initial, ledger)
    second_impacts = evaluate_assignment_impacts(
        first_workflow, second_workflow, ledger, second_changes
    )
    for event in build_mutation_supersession_events(
        second_workflow, second_acceptance, second_impacts
    ):
        ledger = append_ledger_event(ledger, event, second_workflow)
    cursors["second_supersession"] = ledger.event_log[-1]["event_id"]
    return initial, ledger, cursors


def test_accepts_initial_control_plane_with_replayable_worker_bindings(tmp_path) -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    workflow = {
        "workflow_id": "bootstrap-workflow",
        "mission_id": "demo",
        "status": "proposed",
        "proposed_by": "orchestrator",
        "mode": "single_agent",
        "reason": "One bounded implementation assignment is sufficient.",
        "roles": {"coder": {"can_emit": ["patch_ready"], "can_consume": []}},
        "events": {"patch_ready": {"producer_roles": ["coder"]}},
        "nodes": [{"id": "implement", "role": "coder", "emits": ["patch_ready"]}],
        "gates": [],
        "terminal_events": ["patch_ready"],
        "broadcast_policy": {"default": "filtered_delta"},
        "budget_policy": {},
    }
    result = ResultProposal(
        result_id="result-bootstrap",
        assignment_id="assign-bootstrap",
        agent_id="codex-cli",
        status="completed",
        effective_model="gpt-5.5",
        effective_provider="openai-compatible",
        emitted_events=["control_plane_complete"],
        artifacts=[],
        outcome_metrics={},
        verification={"status": "passed"},
        native_log_refs=[],
        mutation_proposal_refs=[],
        review_status=None,
        control_intents=[
            {
                "intent_type": "initial_control_plane",
                "proposal_id": "proposal-bootstrap",
                "workflow": workflow,
                "routing_decision": {
                    "decision_type": "routing_decision",
                    "mission_id": "demo",
                    "workflow_id": "bootstrap-workflow",
                    "selected_mode": "single_agent",
                    "selection_policy_version": "0.1",
                    "triggered_rules": ["bounded_implementation"],
                    "rejected_modes": [],
                    "estimated_coordination_ratio": 0.0,
                    "budget_confidence": "high",
                    "reason": "One bounded implementation assignment is sufficient.",
                    "advisor_gate_decision": {
                        "invoked": False,
                        "policy_version": "0.1",
                        "reason": ["first_run_heuristic"],
                        "decision_basis": "first_run_heuristic",
                    },
                },
                "worker_bindings": [
                    {"node_id": "implement", "role": "coder", "agent_id": "codex-cli", "model": "gpt-5-mini"}
                ],
            },
            {"intent_type": "accept_initial_control_plane", "proposal_id": "proposal-bootstrap"},
        ],
    )

    accepted = accept_initial_control_plane(
        tmp_path, mission, _empty_ledger(), result, session_id="session-bootstrap"
    )

    assert accepted.workflow.status == "accepted"
    assert accepted.routing_decision.workflow_id == "bootstrap-workflow"
    assert accepted.worker_bindings["implement"]["model"] == "gpt-5-mini"
    assert [event["event_type"] for event in accepted.ledger.event_log] == [
        "initial_control_plane_proposed",
        "initial_control_plane_accepted",
    ]
    assert accepted.workflow_path.is_file()

    with pytest.raises(ProtocolError, match="independent verification"):
        accept_initial_control_plane(
            tmp_path / "requires-verification",
            mission,
            _empty_ledger(),
            result,
            session_id="session-bootstrap-verification",
            requirements={"independent_verification": True},
        )

    placeholder_intent = dict(result.control_intents[0])
    placeholder_intent["worker_bindings"] = [
        {
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "model": "chosen-by-orchestrator",
        }
    ]
    placeholder_result = replace(
        result,
        control_intents=[placeholder_intent, result.control_intents[1]],
    )
    with pytest.raises(ProtocolError, match="concrete provider model"):
        accept_initial_control_plane(
            tmp_path / "placeholder-model",
            mission,
            _empty_ledger(),
            placeholder_result,
            session_id="session-bootstrap-placeholder",
        )

    unsupported_agent_intent = dict(result.control_intents[0])
    unsupported_agent_intent["worker_bindings"] = [
        {
            "node_id": "implement",
            "role": "coder",
            "agent_id": "not-a-runtime-adapter",
            "model": "gpt-5-mini",
        }
    ]
    unsupported_agent_result = replace(
        result,
        control_intents=[unsupported_agent_intent, result.control_intents[1]],
    )
    with pytest.raises(ProtocolError, match="unsupported agent"):
        accept_initial_control_plane(
            tmp_path / "unsupported-agent",
            mission,
            _empty_ledger(),
            unsupported_agent_result,
            session_id="session-bootstrap-agent",
            allowed_agent_ids={"codex-cli"},
        )


def test_collects_control_plane_contract_errors_before_rejection() -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    intent = {
        "intent_type": "initial_control_plane",
        "proposal_id": "invalid-bootstrap",
        "workflow": {
            "workflow_id": "invalid-workflow",
            "mission_id": "bootstrap-assignment",
            "mode": "single_agent",
            "status": "proposed",
            "reason": "Invalid fixture.",
            "proposed_by": "orchestrator",
            "roles": {"coder": {"can_emit": ["patch_ready"], "can_consume": []}},
            "events": {"patch_ready": {"producer_roles": ["coder"]}},
            "nodes": [{"id": "implement", "role": "coder", "emits": ["patch_ready"]}],
            "gates": [{"id": "invalid-gate"}],
            "terminal_events": ["patch_ready"],
            "broadcast_policy": {"default": "filtered_delta"},
            "budget_policy": {},
        },
        "routing_decision": {
            "decision_type": "initial_routing",
            "mission_id": "bootstrap-assignment",
            "workflow_id": "invalid-workflow",
            "selected_mode": "single_agent",
            "selection_policy_version": "0.1",
            "triggered_rules": [],
            "rejected_modes": ["single_agent_with_review"],
            "estimated_coordination_ratio": 0.0,
            "budget_confidence": "high",
            "reason": "Invalid fixture.",
            "advisor_gate_decision": {},
        },
        "worker_bindings": [
            {"node_id": "implement", "role": "coder", "agent_id": "coder-01", "model": "gpt-4.1-mini"}
        ],
    }

    errors = collect_initial_control_plane_errors(
        intent,
        mission,
        allowed_agent_ids={"codex-cli"},
        allowed_models={"gpt-5"},
    )

    assert any("node_id" in error for error in errors)
    assert any("workflow mission_id" in error for error in errors)
    assert any("decision_type" in error for error in errors)
    assert any("Routing decision mission_id" in error for error in errors)
    assert any("unsupported agent" in error for error in errors)
    assert any("outside approved policy" in error for error in errors)


def test_control_plane_result_example_uses_existing_loaders() -> None:
    payload = _control_plane_result_example("demo", "codex-cli", "gpt-5")
    proposal = payload["control_intents"][0]

    workflow = Workflow.from_dict(proposal["workflow"])
    routing = load_routing_decision(proposal["routing_decision"])

    assert compile_workflow(workflow).ok
    validate_routing_decision(load_mission(Path("examples/missions/demo/mission.yaml")), routing, workflow=workflow)


def test_validates_inert_workflow_mutation_proposal() -> None:
    workflow = _workflow()
    original_nodes = list(workflow.nodes)

    result = validate_workflow_mutation_proposal(_mutation_proposal())

    assert result.ok
    assert result.errors == []
    assert result.proposal is not None
    assert result.proposal.proposed_changes.add_edges[0].event_ref == (
        "verify.review_approved"
    )
    assert result.proposal.to_dict()["proposed_changes"]["add_nodes"][0][
        "waits_for"
    ] == ["implement.patch_ready"]
    assert list(workflow.nodes) == original_nodes


def test_validates_minimal_worker_mutation_intent() -> None:
    result = validate_workflow_mutation_intent(_mutation_intent())

    assert result.ok
    assert result.intent is not None
    assert result.intent.intent_type == "workflow_mutation"
    assert result.intent.proposed_changes.add_edges[0].event_ref == (
        "verify.review_approved"
    )


def test_rejects_worker_spoofing_trusted_mutation_fields() -> None:
    intent = _mutation_intent(
        {
            "proposal_id": "proposal-worker-chosen",
            "workflow_id": "workflow-worker-chosen",
            "base_workflow_version_id": "workflow:v9999",
            "requires_approval": "worker",
            "source": {"agent_id": "forged-agent"},
        }
    )

    result = validate_workflow_mutation_intent(intent)

    assert not result.ok
    assert result.intent is None
    assert {error.path for error in result.errors} == {
        "intent.base_workflow_version_id",
        "intent.proposal_id",
        "intent.requires_approval",
        "intent.source",
        "intent.workflow_id",
    }


def test_rejects_semantically_invalid_mutation_intent_with_structured_errors() -> None:
    intent = _mutation_intent(
        {
            "reason": "worker_chosen_reason",
            "proposed_changes": {
                "add_nodes": [],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            },
        }
    )

    result = validate_workflow_mutation_intent(intent)

    assert not result.ok
    assert {(error.code, error.path) for error in result.errors} == {
        ("empty_mutation", "proposed_changes"),
        ("invalid_mutation_reason", "reason"),
    }


def test_builds_deterministic_runtime_owned_mutation_envelope() -> None:
    kwargs = {
        "workflow_id": "test-workflow",
        "assignment_id": "assign-001",
        "session_id": "session-001",
        "agent_id": "codex-cli",
        "source_result_event_id": "event-result-001",
        "assignment_workflow_version_id": "test-workflow:v0002-abc123",
        "current_workflow_version_id": "test-workflow:v0002-abc123",
        "requires_approval": "orchestrator",
    }

    first = build_trusted_workflow_mutation_proposal(_mutation_intent(), **kwargs)
    second = build_trusted_workflow_mutation_proposal(_mutation_intent(), **kwargs)

    assert first.ok
    assert first.proposal == second.proposal
    assert first.proposal is not None
    assert first.proposal.proposal_id.startswith("proposal-")
    assert first.proposal.base_workflow_version_id == (
        "test-workflow:v0002-abc123"
    )
    assert first.proposal.source.to_dict() == {
        "assignment_id": "assign-001",
        "session_id": "session-001",
        "agent_id": "codex-cli",
        "actor": "worker",
    }
    changed_source = build_trusted_workflow_mutation_proposal(
        _mutation_intent(),
        **{**kwargs, "source_result_event_id": "event-result-002"},
    )
    assert changed_source.proposal is not None
    assert changed_source.proposal.proposal_id != first.proposal.proposal_id


def test_rejects_stale_mutation_envelope_without_ledger_side_effects() -> None:
    ledger = _empty_ledger()
    original_events = list(ledger.event_log)

    result = build_trusted_workflow_mutation_proposal(
        _mutation_intent(),
        workflow_id="test-workflow",
        assignment_id="assign-001",
        session_id="session-001",
        agent_id="codex-cli",
        source_result_event_id="event-result-001",
        assignment_workflow_version_id="test-workflow:v0001-old",
        current_workflow_version_id="test-workflow:v0002-current",
        requires_approval="orchestrator",
    )

    assert result.status == "stale"
    assert result.proposal is None
    assert [error.code for error in result.errors] == ["stale_workflow_version"]
    assert ledger.event_log == original_events


def test_prepares_isolated_mutation_e2e_demo(tmp_path) -> None:
    paths = prepare_mutation_demo_workspace(tmp_path / "mutation-demo")
    mission = load_mission(paths["mission"])
    workflow = load_workflow(paths["workflow"])
    ledger = load_ledger(paths["ledger"])
    replay = replay_workflow(workflow, ledger)
    artifacts = verify_ledger_artifacts(ledger, tmp_path / "mutation-demo")

    assert mission.mission_id == "mutation-e2e-demo"
    assert compile_workflow(workflow).ok
    assert artifacts[0].status == "valid"
    assert replay.mutation_proposals["event-mutation-proposed"].state == "pending"
    assert replay.mutation_proposals[
        "event-mutation-proposed"
    ].affected_node_ids == ["review"]
    assert replay.nodes["prepare"].state == "completed"


def test_rejects_forbidden_workflow_mutation_operations_with_structured_errors() -> None:
    proposal = _mutation_proposal()
    proposal["proposed_changes"]["ledger_events"] = [
        {"event_id": "rewrite-history"}
    ]
    proposal["proposed_changes"]["create_assignments"] = [
        {"assignment_id": "assign-forged"}
    ]

    result = validate_workflow_mutation_proposal(proposal)

    assert not result.ok
    assert result.proposal is None
    assert {
        error.path for error in result.errors if error.code == "forbidden_mutation_operation"
    } == {
        "proposed_changes.create_assignments",
        "proposed_changes.ledger_events",
    }


def test_rejects_empty_or_ambiguous_workflow_mutation() -> None:
    empty = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    ambiguous = _mutation_proposal()
    ambiguous["proposed_changes"]["add_edges"] = [
        {"from_node": "verify", "to_node": "commit"}
    ]

    empty_result = validate_workflow_mutation_proposal(empty)
    ambiguous_result = validate_workflow_mutation_proposal(ambiguous)

    assert {error.code for error in empty_result.errors} == {"empty_mutation"}
    assert {error.code for error in ambiguous_result.errors} == {"invalid_schema"}


def test_rejects_conflicting_workflow_mutation_edges() -> None:
    proposal = _mutation_proposal()
    proposal["proposed_changes"]["remove_edges"] = [
        {
            "from_node": "verify",
            "to_node": "commit",
            "event": "review_approved",
        }
    ]

    result = validate_workflow_mutation_proposal(proposal)

    assert not result.ok
    assert {error.code for error in result.errors} == {"conflicting_edge_change"}


def test_records_workflow_mutation_proposal_and_partial_acceptance() -> None:
    workflow = _workflow()
    proposed = append_ledger_event(
        _empty_ledger(), _mutation_proposed_event(), workflow
    )

    accepted = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "mission_id": "demo",
            "workflow_id": "test-workflow",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": {
                "supersede_assignments": ["assign-review-001"],
            },
        },
        workflow,
    )

    assert [event["event_type"] for event in accepted.event_log] == [
        "workflow_mutation_proposed",
        "workflow_mutation_accepted",
    ]
    assert replay_workflow(workflow, accepted).mutation_proposals[
        "event-mutation-001"
    ].affected_node_ids == []


def test_records_workflow_mutation_rejection() -> None:
    workflow = _workflow()
    proposed = append_ledger_event(
        _empty_ledger(), _mutation_proposed_event(), workflow
    )

    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "human",
            "reason": "The evidence does not justify changing the workflow.",
        },
        workflow,
    )

    assert rejected.event_log[-1]["source_event_id"] == "event-mutation-001"


def test_rejects_mutation_decision_without_valid_proposal_reference() -> None:
    with pytest.raises(ProtocolError, match="must reference an existing"):
        append_ledger_event(
            _empty_ledger(),
            {
                "event_id": "event-mutation-accepted-001",
                "event_type": "workflow_mutation_accepted",
                "source_event_id": "missing-proposal-event",
                "actor": "orchestrator",
                "applied_changes": {"supersede_assignments": ["assign-001"]},
            },
            _workflow(),
        )


def test_rejects_unproposed_mutation_change_and_second_decision() -> None:
    workflow = _workflow()
    proposed = append_ledger_event(
        _empty_ledger(), _mutation_proposed_event(), workflow
    )
    with pytest.raises(ProtocolError, match="not present in the source proposal"):
        append_ledger_event(
            proposed,
            {
                "event_id": "event-mutation-accepted-001",
                "event_type": "workflow_mutation_accepted",
                "source_event_id": "event-mutation-001",
                "actor": "orchestrator",
                "applied_changes": {
                    "supersede_assignments": ["assign-not-proposed"]
                },
            },
            workflow,
        )

    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "reason": "Rejected once.",
        },
        workflow,
    )
    with pytest.raises(ProtocolError, match="already has a decision"):
        append_ledger_event(
            rejected,
            {
                "event_id": "event-mutation-rejected-002",
                "event_type": "workflow_mutation_rejected",
                "source_event_id": "event-mutation-001",
                "actor": "human",
                "reason": "Cannot decide twice.",
            },
            workflow,
        )


def test_imports_completed_result_with_mutation_proposal_ref_without_applying_it() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "worker-001",
            "status": "completed_with_proposal",
            "emitted_events": [],
            "artifacts": [
                {
                    "artifact_id": "artifact-mutation-001",
                    "path": "artifacts/mutation-001.yaml",
                    "sha256": "a" * 64,
                    "created_by": "worker-001",
                    "source_event": "event-result-001",
                    "mutable": False,
                }
            ],
            "mutation_proposal_refs": ["artifact-mutation-001"],
            "outcome_metrics": {
                "wall_time_ms": 10,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)

    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted"
    ]
    assert updated.event_log[0]["result"]["mutation_proposal_refs"] == [
        "artifact-mutation-001"
    ]
    assert workflow.nodes.keys() == _workflow().nodes.keys()


@pytest.mark.parametrize("status", ["completed", "blocked"])
def test_imports_result_with_independent_mutation_control_intent(status: str) -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    result = load_result_proposal(
        {
            "result_id": f"result-{status}",
            "assignment_id": "assign-001",
            "agent_id": "worker-001",
            "status": status,
            "emitted_events": [],
            "artifacts": [],
            "control_intents": [_mutation_intent()],
            "outcome_metrics": {
                "wall_time_ms": 10,
                "changed_files_count": 0,
            },
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)

    assert updated.event_log[0]["event_type"] == "result_submitted"
    assert updated.event_log[0]["result"]["status"] == status
    assert updated.event_log[0]["result"]["control_intents"] == [
        _mutation_intent()
    ]
    assert "mutation_proposal_refs" in updated.event_log[0]["result"]


def test_preserves_valid_execution_result_with_malformed_control_intent() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    malformed_intent = {"intent_type": "workflow_mutation", "proposal_id": "forged"}
    result = load_result_proposal(
        {
            "result_id": "result-malformed-intent",
            "assignment_id": "assign-001",
            "agent_id": "worker-001",
            "status": "completed",
            "emitted_events": [],
            "control_intents": [malformed_intent],
            "outcome_metrics": {
                "wall_time_ms": 10,
                "changed_files_count": 0,
            },
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)
    intent_result = validate_workflow_mutation_intent(result.control_intents[0])

    assert updated.event_log[0]["result"]["control_intents"] == [malformed_intent]
    assert not intent_result.ok
    assert not any(
        event["event_type"] == "workflow_mutation_proposed"
        for event in updated.event_log
    )


def test_rejects_multiple_or_mixed_result_control_intents() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    multiple = load_result_proposal(
        {
            "result_id": "result-multiple-intents",
            "assignment_id": "assign-001",
            "agent_id": "worker-001",
            "status": "completed",
            "control_intents": [_mutation_intent(), _mutation_intent()],
            "outcome_metrics": {
                "wall_time_ms": 10,
                "changed_files_count": 0,
            },
        }
    )
    mixed = replace(
        multiple,
        result_id="result-mixed-intents",
        status="completed_with_proposal",
        control_intents=[_mutation_intent()],
        mutation_proposal_refs=["artifact-mutation-001"],
    )

    with pytest.raises(ProtocolError, match="at most one control intent"):
        import_result_proposal(workflow, ledger, assignment, multiple)
    with pytest.raises(ProtocolError, match="completed or blocked"):
        import_result_proposal(workflow, ledger, assignment, mixed)


def test_registers_idempotent_session_mutation_intake_and_recovers_orphan(
    tmp_path,
) -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "shell-dummy"
        ),
        workflow,
    )
    record = _mutation_session_record(tmp_path, assignment, _mutation_intent())

    staged = stage_session_record(
        workflow, ledger, assignment, record, artifact_root=tmp_path
    )

    assert [event["event_type"] for event in staged.ledger.event_log] == [
        "assignment_created",
        "result_submitted",
        "workflow_mutation_proposed",
    ]
    assert staged.mutation_intake_disposition is not None
    assert staged.mutation_intake_disposition["status"] == "registered"
    proposal_event = staged.ledger.event_log[-1]
    assert proposal_event["source_event_id"] == staged.result_event_id
    canonical_intent = validate_workflow_mutation_intent(_mutation_intent()).intent
    assert canonical_intent is not None
    assert proposal_event["mutation_proposal"]["intent"] == canonical_intent.to_dict()
    proposal_path = tmp_path / proposal_event["proposal_artifact"]["path"]
    assert sha256_file(proposal_path) == proposal_event["proposal_artifact"]["sha256"]
    assert replay_workflow(workflow, staged.ledger).mutation_proposals[
        proposal_event["event_id"]
    ].state == "pending"
    assert materialize_current_workflow(workflow, staged.ledger) == workflow

    accepted = append_ledger_event(
        staged.ledger,
        {
            "event_id": "event-accept-runtime-proposal",
            "event_type": "workflow_mutation_accepted",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "source_event_id": proposal_event["event_id"],
            "actor": "orchestrator",
            "applied_changes": canonical_intent.proposed_changes.to_dict(),
        },
        workflow,
    )
    assert "verify" in materialize_current_workflow(workflow, accepted).nodes

    duplicate = intake_result_mutation_intent(
        workflow,
        staged.ledger,
        assignment,
        staged.result,
        session_id=record.session_id,
        artifact_root=tmp_path,
    )
    assert duplicate is not None
    assert duplicate.disposition["status"] == "duplicate"
    assert duplicate.ledger.event_log == staged.ledger.event_log

    orphaned = replace(staged.ledger, event_log=staged.ledger.event_log[:-1])
    recovered = intake_result_mutation_intent(
        workflow,
        orphaned,
        assignment,
        staged.result,
        session_id=record.session_id,
        artifact_root=tmp_path,
    )
    assert recovered is not None
    assert recovered.disposition["status"] == "registered"
    assert recovered.ledger.event_log[-1]["event_id"] == proposal_event["event_id"]

    proposal_path.unlink()
    with pytest.raises(ProtocolError, match="artifact is missing"):
        intake_result_mutation_intent(
            workflow,
            staged.ledger,
            assignment,
            staged.result,
            session_id=record.session_id,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("intent", "expected_status"),
    [
        ({"intent_type": "workflow_mutation", "proposal_id": "forged"}, "invalid"),
        (
            _mutation_intent(
                {
                    "proposed_changes": {
                        "remove_nodes": ["review"],
                    }
                }
            ),
            "unsupported",
        ),
    ],
)
def test_records_failed_mutation_intake_without_proposal_event(
    tmp_path, intent, expected_status
) -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "shell-dummy"
        ),
        workflow,
    )
    record = _mutation_session_record(tmp_path, assignment, intent)

    staged = stage_session_record(
        workflow, ledger, assignment, record, artifact_root=tmp_path
    )

    assert [event["event_type"] for event in staged.ledger.event_log] == [
        "assignment_created",
        "result_submitted"
    ]
    assert staged.mutation_intake_disposition is not None
    assert staged.mutation_intake_disposition["status"] == expected_status
    disposition_path = tmp_path / staged.mutation_intake_disposition["artifact_path"]
    assert disposition_path.is_file()


def test_records_stale_mutation_intake_without_proposal_event(tmp_path) -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "shell-dummy"
        ),
        workflow,
    )
    proposed = append_ledger_event(ledger, _mutation_proposed_event(), workflow)
    changed = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": {
                "supersede_assignments": ["assign-review-001"]
            },
        },
        workflow,
    )
    record = _mutation_session_record(tmp_path, assignment, _mutation_intent())

    staged = stage_session_record(
        workflow, changed, assignment, record, artifact_root=tmp_path
    )

    assert staged.mutation_intake_disposition is not None
    assert staged.mutation_intake_disposition["status"] == "stale"
    assert staged.ledger.event_log[-1]["event_type"] == "result_submitted"
    assert sum(
        event["event_type"] == "workflow_mutation_proposed"
        for event in staged.ledger.event_log
    ) == 1


def test_rejects_invalid_result_mutation_proposal_ref_contract() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "worker-001",
            "status": "completed_with_proposal",
            "emitted_events": [],
            "artifacts": [],
            "mutation_proposal_refs": ["artifact-missing"],
            "outcome_metrics": {
                "wall_time_ms": 10,
                "changed_files_count": 0,
            },
        }
    )

    with pytest.raises(ProtocolError, match="does not match a result artifact"):
        import_result_proposal(workflow, ledger, assignment, result)


def test_pending_mutation_blocks_only_affected_workflow_branch() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "left", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
                {"id": "right", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
            ],
            "gates": [],
            "terminal_events": ["patch_ready"],
        }
    )
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "coder",
                        "waits_for": [],
                        "emits": ["patch_ready"],
                    }
                ],
                "add_edges": [
                    {
                        "from_node": "verify",
                        "to_node": "left",
                        "event": "patch_ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(_empty_ledger(), proposed_event, workflow)

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    mutation = replay.mutation_proposals["event-mutation-001"]
    assert mutation.state == "pending"
    assert mutation.affected_node_ids == ["left"]
    assert gatekeeper.ready == ["right"]
    assert gatekeeper.decisions["left"].blocked_reasons[0].code == (
        "mutation_pending"
    )


def test_rejected_mutation_releases_affected_workflow_branch() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "left", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
                {"id": "right", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
            ],
            "gates": [],
            "terminal_events": ["patch_ready"],
        }
    )
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [],
                "add_edges": [
                    {
                        "from_node": "right",
                        "to_node": "left",
                        "event": "patch_ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    proposed = append_ledger_event(_empty_ledger(), proposed_event, workflow)
    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "reason": "Keep the branches independent.",
        },
        workflow,
    )

    replay = replay_workflow(workflow, rejected)
    gatekeeper = evaluate_gatekeeper(workflow, rejected)

    assert replay.mutation_proposals["event-mutation-001"].state == "rejected"
    assert gatekeeper.ready == ["left", "right"]


def test_materializes_current_workflow_from_accepted_mutation() -> None:
    initial = _mutation_workflow()
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [
                    {
                        "from_node": "verify",
                        "to_node": "finish",
                        "event": "ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    proposed = append_ledger_event(_empty_ledger(), proposed_event, initial)
    accepted = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    current = materialize_current_workflow(initial, accepted)
    current_again = materialize_current_workflow(initial, accepted)
    replay = replay_workflow(initial, accepted)

    assert list(initial.nodes) == ["start", "finish"]
    assert list(current.nodes) == ["start", "finish", "verify"]
    assert current.nodes["finish"].waits_for_all == ["verify.ready"]
    assert current == current_again
    assert list(replay.nodes) == ["start", "finish", "verify"]
    assert replay.nodes["finish"].state == "blocked"


def test_projects_deterministic_workflow_versions_across_ledger_events() -> None:
    initial = _mutation_workflow()
    changes = {
        "add_nodes": [
            {
                "id": "verify",
                "role": "producer",
                "waits_for": [],
                "emits": ["ready"],
            }
        ],
        "add_edges": [],
        "remove_edges": [],
        "supersede_assignments": [],
    }
    proposal = _mutation_proposal({"proposed_changes": changes})
    proposal_event = _mutation_proposed_event()
    proposal_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(
        replace(_empty_ledger(), ledger_version=3), proposal_event, initial
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": proposal_event["event_id"],
            "actor": "orchestrator",
            "applied_changes": changes,
        },
        initial,
    )
    rejected_proposal = _mutation_proposed_event()
    rejected_proposal["event_id"] = "event-mutation-002"
    rejected_proposal["mutation_proposal"] = {
        **proposal,
        "proposal_id": "mutation-002",
    }
    ledger = append_ledger_event(ledger, rejected_proposal, initial)
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-rejected-002",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": rejected_proposal["event_id"],
            "actor": "human",
            "reason": "No second structural change is needed.",
        },
        initial,
    )

    projection = project_workflow_versions(initial, ledger)
    repeated = project_workflow_versions(initial, ledger)
    accepted_event = ledger.event_log[1]

    assert projection == repeated
    assert len(projection.versions) == 2
    assert projection.initial_version_id.endswith(
        projection.versions[0].content_hash[:12]
    )
    assert accepted_event["workflow_version_before"] == projection.initial_version_id
    assert accepted_event["workflow_version_after"] == projection.current_version_id
    assert accepted_event["parent_workflow_version_id"] == projection.initial_version_id
    assert accepted_event["workflow_hash_before"] == projection.versions[0].content_hash
    assert accepted_event["workflow_hash_after"] == projection.versions[1].content_hash
    assert [event.workflow_version_id for event in projection.events] == [
        projection.initial_version_id,
        projection.current_version_id,
        projection.current_version_id,
        projection.current_version_id,
    ]
    assert projection.events[1].workflow_version_before == projection.initial_version_id
    assert projection.events[1].workflow_version_after == projection.current_version_id


def test_rejects_forged_native_v3_workflow_version_transition() -> None:
    initial = _mutation_workflow()
    changes = {
        "add_nodes": [
            {
                "id": "verify",
                "role": "producer",
                "waits_for": [],
                "emits": ["ready"],
            }
        ],
        "add_edges": [],
        "remove_edges": [],
        "supersede_assignments": [],
    }
    proposal_event = _mutation_proposed_event()
    proposal_event["mutation_proposal"] = _mutation_proposal(
        {"proposed_changes": changes}
    )
    ledger = append_ledger_event(
        replace(_empty_ledger(), ledger_version=3), proposal_event, initial
    )

    with pytest.raises(ProtocolError, match="does not match derived transition"):
        append_ledger_event(
            ledger,
            {
                "event_id": "event-mutation-accepted-forged",
                "event_type": "workflow_mutation_accepted",
                "source_event_id": proposal_event["event_id"],
                "actor": "orchestrator",
                "applied_changes": changes,
                "workflow_version_before": "test-workflow:v9999:forged",
            },
            initial,
        )


def test_replays_inclusive_event_prefix_without_future_state_leakage() -> None:
    initial = _mutation_workflow()
    changes = {
        "add_nodes": [
            {
                "id": "verify",
                "role": "producer",
                "waits_for": [],
                "emits": ["ready"],
            }
        ],
        "add_edges": [],
        "remove_edges": [],
        "supersede_assignments": [],
    }
    proposal_event = _mutation_proposed_event()
    proposal_event["mutation_proposal"] = _mutation_proposal(
        {"proposed_changes": changes}
    )
    ledger = append_ledger_event(
        replace(_empty_ledger(), ledger_version=3), proposal_event, initial
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": proposal_event["event_id"],
            "actor": "orchestrator",
            "applied_changes": changes,
        },
        initial,
    )
    current_workflow = materialize_current_workflow(initial, ledger)
    assignment = export_assignment(
        initial, ledger, "verify", assignment_id="assign-verify-history"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            current_workflow,
            assignment,
            "session-verify-history",
            "codex-cli",
        ),
        current_workflow,
    )

    at_proposal = replay_workflow(
        initial, ledger, through_event_id=proposal_event["event_id"]
    )
    at_acceptance = replay_workflow(
        initial, ledger, through_event_id="event-mutation-accepted-001"
    )
    at_acceptance_by_ordinal = replay_workflow(
        initial, ledger, through_event_ordinal=1
    )
    current = replay_workflow(initial, ledger)
    at_final = replay_workflow(
        initial, ledger, through_event_id=ledger.event_log[-1]["event_id"]
    )
    gatekeeper_at_acceptance = evaluate_gatekeeper(
        initial, ledger, through_event_ordinal=1
    )

    assert "verify" not in at_proposal.nodes
    assert at_proposal.mutation_proposals[proposal_event["event_id"]].state == "pending"
    assert at_acceptance == at_acceptance_by_ordinal
    assert at_acceptance.workflow_version_id != at_proposal.workflow_version_id
    assert at_acceptance.nodes["verify"].state == "runnable"
    assert at_acceptance.nodes["verify"].assignment_attempts == []
    assert gatekeeper_at_acceptance.decisions["verify"].state == "runnable"
    assert current.nodes["verify"].state == "blocked"
    assert current.nodes["verify"].assignment_attempts[0].state == "in_flight"
    assert at_final == current


def test_rejects_unknown_or_ambiguous_historical_cursor() -> None:
    ledger = append_ledger_event(
        _empty_ledger(), _mutation_proposed_event(), _workflow()
    )

    with pytest.raises(ProtocolError, match="Unknown through_event_id"):
        replay_workflow(_workflow(), ledger, through_event_id="event-missing")
    with pytest.raises(ProtocolError, match="Unknown through_event_ordinal"):
        replay_workflow(_workflow(), ledger, through_event_ordinal=4)
    with pytest.raises(ProtocolError, match="either through_event_id"):
        replay_workflow(
            _workflow(),
            ledger,
            through_event_id="event-mutation-001",
            through_event_ordinal=0,
        )


def test_rejected_mutation_does_not_change_current_workflow() -> None:
    initial = _mutation_workflow()
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed = append_ledger_event(_empty_ledger(), proposed_event, initial)
    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "human",
            "reason": "Not needed.",
        },
        initial,
    )

    assert materialize_current_workflow(initial, rejected) == initial


def test_exports_and_imports_assignment_for_mutation_added_node() -> None:
    initial = _mutation_workflow()
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(_empty_ledger(), proposed_event, initial)
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    assignment = export_assignment(
        initial, ledger, "verify", assignment_id="assign-verify"
    )
    result = load_result_proposal(
        {
            "result_id": "result-verify",
            "assignment_id": "assign-verify",
            "agent_id": "worker-verify",
            "status": "completed",
            "emitted_events": ["ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 5,
                "changed_files_count": 0,
            },
        }
    )
    updated = import_result_proposal(initial, ledger, assignment, result)

    assert assignment.node_id == "verify"
    assert updated.event_log[-1]["node_id"] == "verify"
    assert replay_workflow(initial, updated).nodes["verify"].state == "completed"


def test_rejects_accepted_mutation_that_produces_invalid_workflow() -> None:
    initial = _mutation_workflow()
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [],
                "add_edges": [
                    {
                        "from_node": "missing",
                        "to_node": "finish",
                        "event": "ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    proposed = append_ledger_event(_empty_ledger(), proposed_event, initial)
    accepted = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    with pytest.raises(ProtocolError, match="unknown source"):
        materialize_current_workflow(initial, accepted)


def test_classifies_changed_dependency_chain_and_unchanged_sibling() -> None:
    before, after = _impact_workflows()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-D",
            "event_type": "assignment_created",
            "assignment_id": "assign-D",
            "node_id": "D",
        },
        before,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-assign-X",
            "event_type": "assignment_created",
            "assignment_id": "assign-X",
            "node_id": "X",
        },
        before,
    )

    impacts = evaluate_assignment_impacts(before, after, ledger)

    assert impacts["assign-D"].classification == "affected"
    assert impacts["assign-D"].reasons == [
        "node_contract_changed",
        "dependency_closure_changed",
    ]
    assert impacts["assign-X"].classification == "unaffected"
    assert impacts["assign-X"].reasons == ["execution_context_unchanged"]


def test_assignment_impact_honors_explicit_supersession_and_ambiguity() -> None:
    before, after = _impact_workflows()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-X",
            "event_type": "assignment_created",
            "assignment_id": "assign-X",
            "node_id": "X",
        },
        before,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-assign-unknown",
            "event_type": "assignment_created",
            "assignment_id": "assign-unknown",
        },
        before,
    )

    impacts = evaluate_assignment_impacts(
        before,
        after,
        ledger,
        {"supersede_assignments": ["assign-X"]},
    )

    assert impacts["assign-X"].classification == "affected"
    assert impacts["assign-X"].reasons == ["explicitly_superseded"]
    assert impacts["assign-unknown"].classification == "needs_review"
    assert impacts["assign-unknown"].reasons == ["assignment_node_missing"]


def test_mutation_supersession_preserves_history_but_revokes_old_success() -> None:
    before, _ = _impact_workflows()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-D",
            "event_type": "assignment_created",
            "assignment_id": "assign-D",
            "node_id": "D",
        },
        before,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-assign-X",
            "event_type": "assignment_created",
            "assignment_id": "assign-X",
            "node_id": "X",
        },
        before,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-D-done",
            "event_type": "d_done",
            "assignment_id": "assign-D",
            "node_id": "D",
            "role": "worker",
        },
        before,
    )
    assert replay_workflow(before, ledger).nodes["D"].state == "completed"

    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "C",
                        "role": "worker",
                        "waits_for": ["B.b_done"],
                        "emits": ["c_done"],
                    }
                ],
                "add_edges": [
                    {"from_node": "C", "to_node": "D", "event": "c_done"}
                ],
                "remove_edges": [
                    {"from_node": "B", "to_node": "D", "event": "b_done"}
                ],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(ledger, proposed_event, before)
    accepted_event = {
        "event_id": "event-mutation-accepted-001",
        "event_type": "workflow_mutation_accepted",
        "source_event_id": "event-mutation-001",
        "actor": "orchestrator",
        "applied_changes": proposal["proposed_changes"],
    }
    ledger = append_ledger_event(ledger, accepted_event, before)
    current = materialize_current_workflow(before, ledger)
    impacts = evaluate_assignment_impacts(
        before, current, ledger, accepted_event["applied_changes"]
    )
    supersession_events = build_mutation_supersession_events(
        current, accepted_event, impacts
    )
    before_mutation = replay_workflow(
        before, ledger, through_event_id="event-D-done"
    )
    at_acceptance = replay_workflow(
        before, ledger, through_event_id="event-mutation-accepted-001"
    )
    gatekeeper_at_acceptance = evaluate_gatekeeper(
        before, ledger, through_event_id="event-mutation-accepted-001"
    )

    assert len(supersession_events) == 1
    assert supersession_events[0]["assignment_id"] == "assign-D"
    assert supersession_events[0]["mutation_event_id"] == (
        "event-mutation-accepted-001"
    )
    assert before_mutation.assignment_validity["assign-D"].status == "unaffected"
    assert at_acceptance.assignment_validity["assign-D"].status == "affected"
    assert at_acceptance.assignment_validity["assign-D"].transition_event_id == (
        "event-mutation-accepted-001"
    )
    assert at_acceptance.assignment_validity["assign-X"].status == "unaffected"
    assert gatekeeper_at_acceptance.decisions["D"].blocked_reasons[0].code == (
        "superseded"
    )
    assert gatekeeper_at_acceptance.decisions["D"].blocked_reasons[0].assignment_id == (
        "assign-D"
    )
    ledger = append_ledger_event(ledger, supersession_events[0], current)
    replay = replay_workflow(before, ledger)

    assert any(event["event_id"] == "event-D-done" for event in ledger.event_log)
    assert replay.nodes["D"].state == "blocked"
    assert replay.nodes["D"].emitted_events == []
    assert replay.nodes["D"].assignment_attempts[0].state == "superseded"
    assert replay.nodes["D"].assignment_attempts[0].superseded_by == (
        "event-mutation-accepted-001"
    )
    assert replay.nodes["E"].blocked_reasons[0].code == "superseded"
    assert replay.nodes["E"].blocked_reasons[0].assignment_id == "assign-D"


def test_gatekeeper_blocks_assignment_that_needs_mutation_review() -> None:
    initial = _mutation_workflow()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-verify",
            "event_type": "assignment_created",
            "assignment_id": "assign-verify",
            "node_id": "verify",
        },
    )
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(ledger, proposed_event, initial)
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    gatekeeper = evaluate_gatekeeper(initial, ledger)

    assert gatekeeper.decisions["verify"].state == "blocked"
    assert any(
        reason.code == "needs_review"
        and reason.assignment_id == "assign-verify"
        for reason in gatekeeper.decisions["verify"].blocked_reasons
    )


def test_loads_demo_mission_and_ledger() -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    ledger = load_ledger(Path("examples/missions/demo/ledger.yaml"))

    assert mission.mission_id == "demo"
    assert mission.default_mode == "single_agent"
    assert ledger.current_plan_ref == "workflows/coder_reviewer_committer.yaml"


def test_compiles_valid_workflow() -> None:
    workflow = load_workflow(Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml"))
    result = compile_workflow(workflow)

    assert result.ok
    assert result.errors == []


def test_compiler_requires_terminal_events() -> None:
    result = compile_workflow(_workflow({"terminal_events": []}))

    assert not result.ok
    assert any(error.code == "missing_terminal_events" for error in result.errors)


def test_compiler_rejects_unauthorized_emit() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "implement", "role": "coder", "emits": ["review_approved"]},
            ],
            "terminal_events": ["review_approved"],
        }
    )
    result = compile_workflow(workflow)

    assert not result.ok
    assert any(error.code == "unauthorized_emit" for error in result.errors)


def test_compiler_rejects_committer_without_review_gate() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
                {
                    "id": "commit",
                    "role": "committer",
                    "waits_for": {"all_of": ["patch_ready"]},
                    "emits": ["commit_created"],
                },
            ],
            "terminal_events": ["commit_created"],
        }
    )
    result = compile_workflow(workflow)

    assert not result.ok
    assert any(error.code == "missing_commit_gate" for error in result.errors)


def test_compiler_supports_node_qualified_event_refs() -> None:
    workflow = Workflow.from_dict(
        {
            "workflow_id": "parallel-inventory",
            "mission_id": "demo",
            "mode": "parallel_swarm",
            "roles": {
                "docs_inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "tests_inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "ledger_acceptor": {
                    "can_emit": ["ledger_updated"],
                    "can_consume": ["inventory_complete"],
                },
            },
            "events": {
                "inventory_complete": {
                    "producer_roles": ["docs_inventory", "tests_inventory"],
                },
                "ledger_updated": {"producer_roles": ["ledger_acceptor"]},
            },
            "nodes": [
                {
                    "id": "docs_inventory",
                    "role": "docs_inventory",
                    "emits": ["inventory_complete"],
                },
                {
                    "id": "tests_inventory",
                    "role": "tests_inventory",
                    "emits": ["inventory_complete"],
                },
                {
                    "id": "merge_inventory",
                    "role": "ledger_acceptor",
                    "waits_for": {
                        "all_of": [
                            "docs_inventory.inventory_complete",
                            "tests_inventory.inventory_complete",
                        ]
                    },
                    "emits": ["ledger_updated"],
                },
            ],
            "terminal_events": ["ledger_updated"],
        }
    )
    result = compile_workflow(workflow)

    assert result.ok


def test_ledger_findings_require_provenance() -> None:
    data = {
        "mission_id": "demo",
        "ledger_version": 1,
        "current_goal": "Goal",
        "current_plan_ref": "workflow.yaml",
        "public_findings": [{"finding_id": "finding-001", "content": "Fact"}],
        "decisions": [],
        "risks": [],
        "artifacts": [],
        "broadcasts": [],
        "open_questions": [],
        "event_log": [],
    }
    try:
        Ledger.from_dict(data)
    except ProtocolError as exc:
        assert "missing provenance" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_load_review_decision_validates_independently() -> None:
    decision = load_review_decision(
        {
            "decision_type": "review_decision",
            "decision_id": "review-001",
            "mission_id": "demo",
            "workflow_id": "test-workflow",
            "reviewed_event": "event-result-001",
            "actor": "human",
            "verdict": "approved",
            "reason": "Verification passed.",
            "evidence_refs": ["artifact-report-001"],
            "accepted_findings": [
                {"finding_id": "finding-001", "content": "Patch is safe to land."}
            ],
            "rejected_findings": [
                {"finding_id": "finding-002", "reason": "Claim not supported."}
            ],
            "next_action": "continue",
        }
    )

    assert decision.decision_id == "review-001"
    assert decision.accepted_findings[0]["finding_id"] == "finding-001"


def test_load_review_decision_rejects_overlapping_findings() -> None:
    with pytest.raises(
        ProtocolError,
        match="must not accept and reject the same finding_id",
    ):
        load_review_decision(
            {
                "decision_type": "review_decision",
                "decision_id": "review-001",
                "mission_id": "demo",
                "workflow_id": "test-workflow",
                "reviewed_event": "event-result-001",
                "actor": "human",
                "verdict": "approved",
                "reason": "Verification passed.",
                "evidence_refs": [],
                "accepted_findings": [
                    {"finding_id": "finding-001", "content": "Patch is safe to land."}
                ],
                "rejected_findings": [
                    {"finding_id": "finding-001", "reason": "Actually unsupported."}
                ],
                "next_action": "continue",
            }
        )


def test_load_advisor_outcome_validates_pending_and_scored_states() -> None:
    pending = load_advisor_outcome(
        {
            "decision_type": "advisor_outcome",
            "outcome_id": "advisor-outcome-001",
            "mission_id": "demo",
            "workflow_id": "test-workflow",
            "status": "pending",
            "source_decision_type": "routing_decision",
            "source_decision_ref": "artifacts/decisions/routing-001.yaml",
            "advisor_decision_ref": "artifacts/decisions/advisor-gate-001.yaml",
            "pending_reason": "The mission has not completed yet.",
        }
    )
    scored = load_advisor_outcome(
        {
            "decision_type": "advisor_outcome",
            "outcome_id": "advisor-outcome-002",
            "mission_id": "demo",
            "workflow_id": "test-workflow",
            "status": "scored",
            "source_decision_type": "review_decision",
            "source_decision_ref": "artifacts/reviews/review-001.yaml",
            "advisor_decision_ref": "artifacts/decisions/advisor-gate-002.yaml",
            "classification": "good_skip",
            "actual_advisor_tokens": 0,
            "actual_total_tokens": 18400,
            "rework_count": 0,
            "broadcast_tokens": 1200,
            "duplicate_context_observed": False,
        }
    )

    assert pending.status == "pending"
    assert pending.pending_reason == "The mission has not completed yet."
    assert scored.classification == "good_skip"
    assert scored.actual_total_tokens == 18400


def test_load_advisor_outcome_rejects_missing_pending_reason() -> None:
    with pytest.raises(ProtocolError, match="pending_reason"):
        load_advisor_outcome(
            {
                "decision_type": "advisor_outcome",
                "outcome_id": "advisor-outcome-001",
                "mission_id": "demo",
                "status": "pending",
                "source_decision_type": "routing_decision",
                "source_decision_ref": "artifacts/decisions/routing-001.yaml",
                "advisor_decision_ref": "artifacts/decisions/advisor-gate-001.yaml",
            }
        )


def test_advisor_policy_proves_skip_and_invocation_paths() -> None:
    skipped = evaluate_advisor_policy(
        {
            "node_count": 1,
            "parallel_width": 1,
            "risk_level": "low",
            "estimated_total_tokens": 12000,
            "commit_or_merge_action": False,
        }
    )
    invoked = evaluate_advisor_policy(
        {
            "node_count": 5,
            "parallel_width": 3,
            "risk_level": "high",
            "high_risk_node_count": 1,
            "broadcast_policy": "full_ledger",
            "estimated_context_fanout_tokens": 9200,
        }
    )

    assert skipped.invoked is False
    assert "node_count <= 2" in skipped.reason
    assert invoked.invoked is True
    assert invoked.advisor == "cost_risk_analyst"
    assert invoked.estimated_advisor_tokens == 3300
    assert invoked.estimated_savings_tokens == 9200
    assert "parallel_width >= 3" in invoked.reason


def test_advisor_invocation_rejects_skip_and_execution_authority() -> None:
    skipped = evaluate_advisor_policy({"node_count": 1, "risk_level": "low"})
    with pytest.raises(ProtocolError, match="invoked gate decision"):
        run_advisor_invocation(
            skipped,
            {},
            runner=lambda _decision, _facts: {},
            invocation_id="advisor-invocation-skipped",
            gate_decision_ref="gate.yaml",
            recommendation_ref="recommendation.yaml",
        )

    invoked = evaluate_advisor_policy({"parallel_width": 3})
    with pytest.raises(ProtocolError, match="recommendation-only scope"):
        run_advisor_invocation(
            invoked,
            {},
            runner=lambda decision, _facts: {
                "recommendation": {
                    "advisor": decision.advisor,
                    "verdict": "revise",
                    "confidence": "medium",
                    "p50_tokens": 100,
                    "p90_tokens": 200,
                    "p50_cost_usd": 0.01,
                    "p90_cost_usd": 0.02,
                    "main_cost_drivers": [],
                    "main_risk_drivers": [],
                    "recommended_changes": ["Keep review explicit."],
                    "dispatch": {"agent": "codex-cli"},
                },
                "telemetry_mode": "deterministic_fixture",
                "token_usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
                "cost_usd": 0.001,
                "capability_scope": "recommendation_only",
            },
            invocation_id="advisor-invocation-overreach",
            gate_decision_ref="gate.yaml",
            recommendation_ref="recommendation.yaml",
        )


def test_advisor_policy_demo_links_invocation_cost_and_outcome_without_gate_bypass(
    tmp_path,
) -> None:
    invoked = run_advisor_policy_demo(tmp_path / "invoked", scenario="invoke")
    skipped = run_advisor_policy_demo(tmp_path / "skipped", scenario="skip")

    gate = load_advisor_gate_decision(
        yaml.safe_load(
            Path(invoked["advisor_gate_decision_path"]).read_text(encoding="utf-8")
        )
    )
    recommendation = load_advisor_recommendation(
        yaml.safe_load(
            Path(invoked["advisor_recommendation_path"]).read_text(encoding="utf-8")
        )
    )
    invocation = load_advisor_invocation(
        yaml.safe_load(
            Path(invoked["advisor_invocation_path"]).read_text(encoding="utf-8")
        )
    )
    outcome = load_advisor_outcome(
        yaml.safe_load(Path(invoked["advisor_outcome_path"]).read_text(encoding="utf-8"))
    )
    workflow = load_workflow(Path(invoked["workflow_path"]))
    ledger = load_ledger(Path(invoked["ledger_path"]))
    replay = replay_workflow(workflow, ledger)

    assert gate.invoked is True
    assert recommendation.verdict == "revise"
    assert invocation.capability_scope == "recommendation_only"
    assert invocation.total_tokens == 1480
    assert invocation.cost_usd == 0.0064
    assert outcome.classification == "good_call"
    assert outcome.recommendation_applied is True
    assert outcome.actual_advisor_tokens == invocation.total_tokens
    assert outcome.actual_advisor_cost_usd == invocation.cost_usd
    assert outcome.advisor_recommendation_ref == invocation.recommendation_ref
    assert workflow.broadcast_policy == {"default": "filtered_delta"}
    assert replay.nodes["implement"].state == "runnable"
    assert all(node.state != "completed" for node in replay.nodes.values())
    assert ledger.event_log[-1]["event_type"] == "advisor_outcome_recorded"

    scored_ledger = append_ledger_event(
        replace(ledger, ledger_version=1),
        {
            "event_id": "event-advisor-demo-terminal",
            "event_type": "commit_created",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-advisor-demo",
            "node_id": "commit",
            "role": "committer",
            "agent_id": "fixture",
        },
        workflow,
    )
    score_summary = summarize_advisor_scores(
        scored_ledger,
        workflow=workflow,
        artifact_root=tmp_path / "invoked",
    )
    assert score_summary["classification_counts"]["good_call"] == 1
    assert score_summary["scores"][0]["recommendation_applied"] is True

    skipped_outcome = load_advisor_outcome(
        yaml.safe_load(Path(skipped["advisor_outcome_path"]).read_text(encoding="utf-8"))
    )
    assert skipped["invoked"] is False
    assert skipped["advisor_invocation_path"] is None
    assert skipped_outcome.classification == "good_skip"
    assert skipped_outcome.actual_advisor_tokens == 0
    assert skipped_outcome.actual_advisor_cost_usd == 0.0


def test_cli_advisor_demo_exposes_maintained_invocation_path(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "mission",
            "advisor-demo",
            str(tmp_path / "cli-advisor-demo"),
            "--scenario",
            "invoke",
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["invoked"] is True
    assert payload["classification"] == "good_call"
    assert Path(payload["advisor_invocation_path"]).is_file()


def test_apply_advisor_outcome_appends_replayable_event() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    outcome = load_advisor_outcome(
        {
            "decision_type": "advisor_outcome",
            "outcome_id": "advisor-outcome-002",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "status": "scored",
            "source_decision_type": "routing_decision",
            "source_decision_ref": "artifacts/decisions/routing-001.yaml",
            "advisor_decision_ref": "artifacts/decisions/advisor-gate-002.yaml",
            "advisor_recommendation_ref": None,
            "advisor_invocation_ref": None,
            "recommendation_applied": None,
            "classification": "good_skip",
            "actual_advisor_tokens": 0,
            "actual_advisor_cost_usd": None,
            "actual_total_tokens": 18400,
            "rework_count": 0,
            "broadcast_tokens": 1200,
            "duplicate_context_observed": False,
            "price_snapshot_attribution": {
                "snapshot_id": "price-snapshot-2026-06-20",
                "snapshot_source": "manual",
                "model": "gpt-5-mini",
                "pricing_model": "token",
                "predicted_cost_usd": 0.02,
                "predicted_cost_basis": "recorded_cost",
                "actual_cost_usd": 0.018,
                "actual_cost_basis": "recorded_cost",
                "cost_delta_usd": -0.002,
            },
        }
    )

    updated = apply_advisor_outcome(
        ledger,
        outcome,
        workflow=workflow,
        outcome_ref="artifacts/outcomes/advisor-outcome-002.yaml",
    )

    assert updated.event_log[-1] == {
        "event_id": "event-advisor-outcome-002",
        "event_type": "advisor_outcome_recorded",
        "mission_id": "demo",
        "advisor_outcome_id": "advisor-outcome-002",
        "workflow_id": "test-workflow",
        "status": "scored",
        "source_decision_type": "routing_decision",
        "source_decision_ref": "artifacts/decisions/routing-001.yaml",
        "advisor_decision_ref": "artifacts/decisions/advisor-gate-002.yaml",
        "outcome_ref": "artifacts/outcomes/advisor-outcome-002.yaml",
        "classification": "good_skip",
        "actual_advisor_tokens": 0,
        "actual_total_tokens": 18400,
        "rework_count": 0,
        "broadcast_tokens": 1200,
        "duplicate_context_observed": False,
        "price_snapshot_attribution": {
            "snapshot_id": "price-snapshot-2026-06-20",
            "snapshot_source": "manual",
            "model": "gpt-5-mini",
            "pricing_model": "token",
            "predicted_cost_usd": 0.02,
            "predicted_cost_basis": "recorded_cost",
            "actual_cost_usd": 0.018,
            "actual_cost_basis": "recorded_cost",
            "cost_delta_usd": -0.002,
        },
    }


def test_cli_import_advisor_outcome_updates_ledger(tmp_path, capsys) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    ledger_path = tmp_path / "ledger.yaml"
    outcome_path = tmp_path / "advisor_outcome.yaml"
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "test-workflow",
                "mission_id": "demo",
                "mode": "small_dag",
                "roles": {
                    "coder": {"can_emit": ["patch_ready"], "can_consume": []},
                    "reviewer": {"can_emit": ["review_approved"], "can_consume": ["patch_ready"]},
                    "committer": {
                        "can_emit": ["commit_created"],
                        "can_consume": ["patch_ready", "review_approved"],
                    },
                },
                "events": {
                    "patch_ready": {"producer_roles": ["coder"]},
                    "review_approved": {"producer_roles": ["reviewer"]},
                    "commit_created": {"producer_roles": ["committer"]},
                },
                "nodes": [
                    {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
                    {
                        "id": "review",
                        "role": "reviewer",
                        "waits_for": {"all_of": ["patch_ready"]},
                        "emits": ["review_approved"],
                    },
                    {
                        "id": "commit",
                        "role": "committer",
                        "waits_for": {"all_of": ["patch_ready", "review_approved"]},
                        "emits": ["commit_created"],
                    },
                ],
                "terminal_events": ["commit_created"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_ledger(
        ledger_path,
        Ledger.from_dict(
            {
                "mission_id": "demo",
                "ledger_version": 2,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            }
        ),
    )
    outcome_path.write_text(
        yaml.safe_dump(
            {
                "decision_type": "advisor_outcome",
                "outcome_id": "advisor-outcome-002",
                "mission_id": "demo",
                "workflow_id": "test-workflow",
                "status": "scored",
                "source_decision_type": "routing_decision",
                "source_decision_ref": "artifacts/decisions/routing-001.yaml",
                "advisor_decision_ref": "artifacts/decisions/advisor-gate-002.yaml",
                "classification": "good_skip",
                "actual_advisor_tokens": 0,
                "actual_total_tokens": 18400,
                "rework_count": 0,
                "broadcast_tokens": 1200,
                "duplicate_context_observed": False,
                "price_snapshot_attribution": {
                    "snapshot_id": "price-snapshot-2026-06-20",
                    "snapshot_source": "manual",
                    "model": "gpt-5-mini",
                    "pricing_model": "token",
                    "predicted_cost_usd": 0.02,
                    "predicted_cost_basis": "recorded_cost",
                    "actual_cost_usd": 0.018,
                    "actual_cost_basis": "recorded_cost",
                    "cost_delta_usd": -0.002,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "decision",
            "import-advisor-outcome",
            str(workflow_path),
            str(ledger_path),
            str(outcome_path),
            "--outcome-ref",
            "artifacts/outcomes/advisor-outcome-002.yaml",
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)
    updated = load_ledger(ledger_path)

    assert exit_code == 0
    assert payload["event_type"] == "advisor_outcome_recorded"
    assert payload["classification"] == "good_skip"
    assert updated.event_log[-1]["advisor_outcome_id"] == "advisor-outcome-002"
    assert updated.event_log[-1]["price_snapshot_attribution"]["snapshot_id"] == "price-snapshot-2026-06-20"


def test_summarize_advisor_scores_classifies_good_skip(tmp_path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    decision_path = tmp_path / "advisor_gate_decision.yaml"
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "test-workflow",
                "mission_id": "demo",
                "mode": "small_dag",
                "roles": {
                    "coder": {"can_emit": ["patch_ready"], "can_consume": []},
                    "reviewer": {"can_emit": ["review_approved"], "can_consume": ["patch_ready"]},
                    "committer": {
                        "can_emit": ["commit_created"],
                        "can_consume": ["patch_ready", "review_approved"],
                    },
                },
                "events": {
                    "patch_ready": {"producer_roles": ["coder"]},
                    "review_approved": {"producer_roles": ["reviewer"]},
                    "commit_created": {"producer_roles": ["committer"]},
                },
                "nodes": [
                    {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
                    {
                        "id": "review",
                        "role": "reviewer",
                        "waits_for": {"all_of": ["patch_ready"]},
                        "emits": ["review_approved"],
                    },
                    {
                        "id": "commit",
                        "role": "committer",
                        "waits_for": {"all_of": ["patch_ready", "review_approved"]},
                        "emits": ["commit_created"],
                    },
                ],
                "gates": [
                    {
                        "id": "commit_gate",
                        "node_id": "commit",
                        "requires": {"all_of": ["patch_ready", "review_approved"]},
                    }
                ],
                "terminal_events": ["commit_created"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    decision_path.write_text(
        yaml.safe_dump(
            {
                "advisor_gate_decision": {
                    "invoked": False,
                    "policy_version": "0.1",
                    "reason": ["parallel_width < 3"],
                    "decision_basis": "first_run_heuristic",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-terminal",
                    "event_type": "commit_created",
                    "mission_id": "demo",
                    "workflow_id": "test-workflow",
                    "assignment_id": "assign-commit",
                    "node_id": "commit",
                    "role": "committer",
                    "agent_id": "codex-cli",
                },
                {
                    "event_id": "event-advisor-outcome-001",
                    "event_type": "advisor_outcome_recorded",
                    "mission_id": "demo",
                    "advisor_outcome_id": "advisor-outcome-001",
                    "workflow_id": "test-workflow",
                    "status": "pending",
                    "source_decision_type": "routing_decision",
                    "source_decision_ref": "artifacts/decisions/routing-001.yaml",
                    "advisor_decision_ref": "advisor_gate_decision.yaml",
                    "outcome_ref": "artifacts/outcomes/advisor-outcome-001.yaml",
                    "actual_advisor_tokens": 0,
                    "actual_total_tokens": 18400,
                    "rework_count": 0,
                    "broadcast_tokens": 1200,
                    "duplicate_context_observed": False,
                    "price_snapshot_attribution": {
                        "cost_delta_usd": -0.002,
                    },
                    "pending_reason": "Awaiting post-run scoring.",
                },
            ],
        }
    )

    summary = summarize_advisor_scores(
        ledger,
        artifact_root=tmp_path,
    )

    assert summary["classification_counts"]["good_skip"] == 1
    assert summary["scores"][0]["classification"] == "good_skip"
    assert summary["scores"][0]["score_status"] == "scored"


def test_summarize_advisor_scores_classifies_missed_call_from_negative_signals(tmp_path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    decision_path = tmp_path / "advisor_gate_decision.yaml"
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "test-workflow",
                "mission_id": "demo",
                "mode": "small_dag",
                "roles": {"coder": {"can_emit": ["done"], "can_consume": []}},
                "events": {"done": {"producer_roles": ["coder"]}},
                "nodes": [{"id": "implement", "role": "coder", "emits": ["done"]}],
                "terminal_events": ["done"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    decision_path.write_text(
        yaml.safe_dump(
            {
                "advisor_gate_decision": {
                    "invoked": False,
                    "policy_version": "0.1",
                    "reason": ["estimated_total_tokens < 30000"],
                    "decision_basis": "first_run_heuristic",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-terminal",
                    "event_type": "done",
                    "mission_id": "demo",
                    "workflow_id": "test-workflow",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                    "agent_id": "codex-cli",
                },
                {
                    "event_id": "event-advisor-outcome-002",
                    "event_type": "advisor_outcome_recorded",
                    "mission_id": "demo",
                    "advisor_outcome_id": "advisor-outcome-002",
                    "workflow_id": "test-workflow",
                    "status": "pending",
                    "source_decision_type": "routing_decision",
                    "source_decision_ref": "artifacts/decisions/routing-001.yaml",
                    "advisor_decision_ref": "advisor_gate_decision.yaml",
                    "outcome_ref": "artifacts/outcomes/advisor-outcome-002.yaml",
                    "actual_advisor_tokens": 0,
                    "actual_total_tokens": 18400,
                    "rework_count": 1,
                    "broadcast_tokens": 1200,
                    "duplicate_context_observed": True,
                    "pending_reason": "Awaiting post-run scoring.",
                },
            ],
        }
    )

    summary = summarize_advisor_scores(
        ledger,
        artifact_root=tmp_path,
    )

    assert summary["classification_counts"]["missed_call"] == 1
    assert summary["scores"][0]["classification"] == "missed_call"


def test_summarize_advisor_scores_reports_insufficient_evidence_without_decision_artifact(
    tmp_path,
) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "test-workflow",
                "mission_id": "demo",
                "mode": "single_agent",
                "roles": {"coder": {"can_emit": ["done"], "can_consume": []}},
                "events": {"done": {"producer_roles": ["coder"]}},
                "nodes": [{"id": "implement", "role": "coder", "emits": ["done"]}],
                "terminal_events": ["done"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-terminal",
                    "event_type": "done",
                    "mission_id": "demo",
                    "workflow_id": "test-workflow",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                    "agent_id": "codex-cli",
                },
                {
                    "event_id": "event-advisor-outcome-003",
                    "event_type": "advisor_outcome_recorded",
                    "mission_id": "demo",
                    "advisor_outcome_id": "advisor-outcome-003",
                    "workflow_id": "test-workflow",
                    "status": "pending",
                    "source_decision_type": "routing_decision",
                    "source_decision_ref": "artifacts/decisions/routing-001.yaml",
                    "advisor_decision_ref": "missing.yaml",
                    "outcome_ref": "artifacts/outcomes/advisor-outcome-003.yaml",
                    "pending_reason": "Awaiting post-run scoring.",
                },
            ],
        }
    )

    summary = summarize_advisor_scores(
        ledger,
        artifact_root=tmp_path,
    )

    assert summary["insufficient_evidence_count"] == 1
    assert summary["scores"][0]["score_status"] == "insufficient_evidence"
    assert "advisor_decision_unavailable" in summary["scores"][0]["reasons"]


def test_load_routing_decision_validates_complex_mode_rationale() -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    workflow = load_workflow(Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml"))
    decision = load_routing_decision(
        {
            "decision_type": "routing_decision",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "selected_mode": "small_dag",
            "selection_policy_version": "0.1",
            "triggered_rules": ["staged_review_required"],
            "rejected_modes": [
                {
                    "mode": "single_agent_with_review",
                    "rejected_because": "A separate commit node keeps the final gate inspectable.",
                }
            ],
            "estimated_coordination_ratio": 0.18,
            "budget_confidence": "high",
            "reason": "The workflow separates implementation, review, and commit.",
            "budget_reason": "The graph stays within the coordination ratio target.",
            "risk_reason": "The commit step remains explicitly gated.",
            "advisor_gate_decision": {
                "invoked": False,
                "policy_version": "0.1",
                "reason": [
                    "parallel_width < 3",
                    "review_or_human_gate_count == 1",
                ],
                "decision_basis": "first_run_heuristic",
            },
        }
    )

    validate_routing_decision(mission, decision, workflow=workflow)

    assert decision.selected_mode == "small_dag"
    assert decision.rejected_modes[0]["mode"] == "single_agent_with_review"


def test_validate_routing_decision_rejects_complex_mode_without_simpler_rejection() -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    decision = load_routing_decision(
        {
            "decision_type": "routing_decision",
            "mission_id": "demo",
            "selected_mode": "parallel_swarm",
            "selection_policy_version": "0.1",
            "triggered_rules": ["independent_subtasks >= 4"],
            "rejected_modes": [],
            "estimated_coordination_ratio": 0.2,
            "budget_confidence": "high",
            "reason": "Use many workers.",
            "advisor_gate_decision": {
                "invoked": True,
                "advisor": "cost_risk_analyst",
                "policy_version": "0.1",
                "reason": ["parallel_width >= 3"],
                "estimated_advisor_tokens": 3300,
                "estimated_savings_tokens": 9200,
                "confidence": "low",
                "decision_basis": "first_run_heuristic",
            },
        }
    )

    with pytest.raises(
        ProtocolError,
        match="Complex routing requires rejected simpler modes",
    ):
        validate_routing_decision(mission, decision)


def test_cli_validate_routing_decision(tmp_path, capsys) -> None:
    mission_path = tmp_path / "mission.yaml"
    workflow_path = tmp_path / "workflow.yaml"
    decision_path = tmp_path / "routing_decision.yaml"
    shutil.copy2("examples/missions/demo/mission.yaml", mission_path)
    shutil.copy2("examples/missions/demo/workflows/coder_reviewer_committer.yaml", workflow_path)
    decision_path.write_text(
        yaml.safe_dump(
            {
                "decision_type": "routing_decision",
                "mission_id": "demo",
                "workflow_id": "coder-reviewer-committer-001",
                "selected_mode": "small_dag",
                "selection_policy_version": "0.1",
                "triggered_rules": ["staged_review_required"],
                "rejected_modes": [
                    {
                        "mode": "single_agent_with_review",
                        "rejected_because": "A separate commit node keeps the gate explicit.",
                    }
                ],
                "estimated_coordination_ratio": 0.18,
                "budget_confidence": "high",
                "reason": "The workflow separates implementation, review, and commit.",
                "budget_reason": "The graph stays within the coordination ratio target.",
                "risk_reason": "The commit step remains explicitly gated.",
                "advisor_gate_decision": {
                    "invoked": False,
                    "policy_version": "0.1",
                    "reason": [
                        "parallel_width < 3",
                        "review_or_human_gate_count == 1",
                    ],
                    "decision_basis": "first_run_heuristic",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "decision",
            "validate-routing",
            str(mission_path),
            str(decision_path),
            "--workflow",
            str(workflow_path),
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["decision_type"] == "routing_decision"
    assert payload["selected_mode"] == "small_dag"


def test_load_turn_report_validates_bounded_progress_packet() -> None:
    report = load_turn_report(
        {
            "report_id": "report-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "in_progress",
            "tool_calls_since_last_report": 1,
            "summary": "Inspected the implementation entry point.",
            "new_findings": [],
            "artifact_refs": [],
            "blockers": [],
            "suggested_ledger_updates": [],
            "token_usage": {
                "input_tokens": 100,
                "output_tokens": 20,
            },
        }
    )

    assert report.status == "in_progress"
    assert report.token_usage["input_tokens"] == 100


def test_compile_dispatch_packet_produces_canonical_handoff() -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    workflow = load_workflow(Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml"))
    ledger = load_ledger(Path("examples/missions/demo/ledger.yaml"))
    assignment = export_assignment(
        workflow,
        ledger,
        "review",
        assignment_id="assign-review",
        force=True,
    )
    routing_decision = load_routing_decision(
        {
            "decision_type": "routing_decision",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "selected_mode": "small_dag",
            "selection_policy_version": "0.1",
            "triggered_rules": ["staged_review_required"],
            "rejected_modes": [
                {
                    "mode": "single_agent_with_review",
                    "rejected_because": "A separate commit node keeps the gate explicit.",
                }
            ],
            "estimated_coordination_ratio": 0.18,
            "budget_confidence": "high",
            "reason": "The workflow separates implementation, review, and commit.",
            "budget_reason": "The graph stays within the coordination ratio target.",
            "risk_reason": "The commit step remains explicitly gated.",
            "advisor_gate_decision": {
                "invoked": False,
                "policy_version": "0.1",
                "reason": [
                    "parallel_width < 3",
                    "review_or_human_gate_count == 1",
                ],
                "decision_basis": "first_run_heuristic",
            },
        }
    )

    packet = compile_dispatch_packet(
        mission,
        workflow,
        routing_decision,
        assignment,
        packet_id="packet-001",
    )
    validate_dispatch_packet(mission, workflow, load_dispatch_packet(packet.to_dict()))

    assert packet.packet_id == "packet-001"
    assert packet.assignment.assignment_id == "assign-review"
    assert packet.turn_report_policy == {
        "after_each_tool_call": True,
        "max_report_tokens": 600,
    }


def test_compile_dispatch_packet_rejects_commit_without_review_constraint() -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    workflow = load_workflow(Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml"))
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-result-implement",
                    "event_type": "patch_ready",
                    "mission_id": "demo",
                    "workflow_id": workflow.workflow_id,
                    "assignment_id": "assign-implement",
                    "node_id": "implement",
                    "role": "coder",
                    "agent_id": "codex-cli",
                },
                {
                    "event_id": "event-result-review",
                    "event_type": "review_approved",
                    "mission_id": "demo",
                    "workflow_id": workflow.workflow_id,
                    "assignment_id": "assign-review",
                    "node_id": "review",
                    "role": "reviewer",
                    "agent_id": "codex-cli",
                },
            ],
        }
    )
    assignment = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-commit",
    )
    routing_decision = load_routing_decision(
        {
            "decision_type": "routing_decision",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "selected_mode": "small_dag",
            "selection_policy_version": "0.1",
            "triggered_rules": ["staged_review_required"],
            "rejected_modes": [
                {
                    "mode": "single_agent_with_review",
                    "rejected_because": "A separate commit node keeps the gate explicit.",
                }
            ],
            "estimated_coordination_ratio": 0.18,
            "budget_confidence": "high",
            "reason": "The workflow separates implementation, review, and commit.",
            "advisor_gate_decision": {
                "invoked": False,
                "policy_version": "0.1",
                "reason": [
                    "parallel_width < 3",
                    "review_or_human_gate_count == 1",
                ],
                "decision_basis": "first_run_heuristic",
            },
        }
    )

    with pytest.raises(
        ProtocolError,
        match="Commit-like dispatch packets must require an explicit review decision",
    ):
        compile_dispatch_packet(
            mission,
            workflow,
            routing_decision,
            assignment,
            packet_id="packet-commit",
            review_constraints={
                "required_gate_ids": ["commit_gate"],
                "requires_review_decision": False,
                "forbid_scope_expansion": True,
                "forbid_new_agents": True,
            },
        )


def test_cli_compile_dispatch_packet(tmp_path, capsys) -> None:
    mission_path = tmp_path / "mission.yaml"
    workflow_path = tmp_path / "workflow.yaml"
    ledger_path = tmp_path / "ledger.yaml"
    assignment_path = tmp_path / "assignment.yaml"
    decision_path = tmp_path / "routing_decision.yaml"
    packet_path = tmp_path / "dispatch_packet.yaml"
    shutil.copy2("examples/missions/demo/mission.yaml", mission_path)
    shutil.copy2("examples/missions/demo/workflows/coder_reviewer_committer.yaml", workflow_path)
    shutil.copy2("examples/missions/demo/ledger.yaml", ledger_path)

    workflow = load_workflow(workflow_path)
    ledger = load_ledger(ledger_path)
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-implement",
    )
    assignment_path.write_text(
        yaml.safe_dump(assignment.to_dict(), sort_keys=False),
        encoding="utf-8",
    )
    decision_path.write_text(
        yaml.safe_dump(
            {
                "decision_type": "routing_decision",
                "mission_id": "demo",
                "workflow_id": workflow.workflow_id,
                "selected_mode": "small_dag",
                "selection_policy_version": "0.1",
                "triggered_rules": ["staged_review_required"],
                "rejected_modes": [
                    {
                        "mode": "single_agent_with_review",
                        "rejected_because": "A separate commit node keeps the gate explicit.",
                    }
                ],
                "estimated_coordination_ratio": 0.18,
                "budget_confidence": "high",
                "reason": "The workflow separates implementation, review, and commit.",
                "advisor_gate_decision": {
                    "invoked": False,
                    "policy_version": "0.1",
                    "reason": [
                        "parallel_width < 3",
                        "review_or_human_gate_count == 1",
                    ],
                    "decision_basis": "first_run_heuristic",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "decision",
            "compile-dispatch",
            str(mission_path),
            str(workflow_path),
            str(decision_path),
            str(assignment_path),
            "--packet-id",
            "packet-001",
            "--dispatch-packet",
            str(packet_path),
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)
    persisted = yaml.safe_load(packet_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["packet_id"] == "packet-001"
    assert payload["assignment"]["assignment_id"] == "assign-implement"
    assert persisted["packet_id"] == "packet-001"


def test_apply_review_decision_projects_public_findings_with_review_provenance() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-result-001",
            "event_type": "result_submitted",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "result": {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "emitted_events": [],
                "artifacts": [],
                "outcome_metrics": {},
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        },
        workflow,
    )
    decision = load_review_decision(
        {
            "decision_type": "review_decision",
            "decision_id": "review-001",
            "mission_id": "demo",
            "workflow_id": "test-workflow",
            "reviewed_event": "event-result-001",
            "actor": "human",
            "verdict": "approved",
            "reason": "Verification passed.",
            "evidence_refs": ["artifact-report-001"],
            "accepted_findings": [
                {"finding_id": "finding-001", "content": "Patch is safe to land."}
            ],
            "rejected_findings": [],
            "next_action": "continue",
        }
    )

    updated = apply_review_decision(
        ledger,
        decision,
        workflow=workflow,
        decision_ref="artifacts/reviews/review-001.yaml",
    )

    assert updated.event_log[-1]["event_type"] == "review_decision_recorded"
    assert updated.event_log[-1]["decision_ref"] == "artifacts/reviews/review-001.yaml"
    assert updated.public_findings == [
        {
            "finding_id": "finding-001",
            "content": "Patch is safe to land.",
            "source_event": "event-result-001",
            "source_agent": "codex-cli",
            "accepted_by": "human",
            "review_decision_id": "review-001",
        }
    ]
    assert updated.decisions[0]["decision_id"] == "review-001"


def test_cli_import_review_decision_updates_ledger_projection(tmp_path, capsys) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    ledger_path = tmp_path / "ledger.yaml"
    decision_path = tmp_path / "review-decision.yaml"
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "test-workflow",
                "mission_id": "demo",
                "mode": "small_dag",
                "roles": {
                    "coder": {"can_emit": ["patch_ready"], "can_consume": []},
                    "reviewer": {
                        "can_emit": ["review_approved"],
                        "can_consume": ["patch_ready"],
                    },
                    "committer": {
                        "can_emit": ["commit_created"],
                        "can_consume": ["patch_ready", "review_approved"],
                    },
                },
                "events": {
                    "patch_ready": {"producer_roles": ["coder"]},
                    "review_approved": {"producer_roles": ["reviewer"]},
                    "commit_created": {"producer_roles": ["committer"]},
                },
                "nodes": [
                    {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
                    {
                        "id": "review",
                        "role": "reviewer",
                        "waits_for": {"all_of": ["patch_ready"]},
                        "emits": ["review_approved"],
                    },
                    {
                        "id": "commit",
                        "role": "committer",
                        "waits_for": {"all_of": ["patch_ready", "review_approved"]},
                        "emits": ["commit_created"],
                    },
                ],
                "terminal_events": ["commit_created"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ledger = replace(_empty_ledger(), ledger_version=2)
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-result-001",
            "event_type": "result_submitted",
            "mission_id": "demo",
            "workflow_id": "test-workflow",
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "result": {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "emitted_events": [],
                "artifacts": [],
                "outcome_metrics": {},
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        },
        _workflow(),
    )
    write_ledger(ledger_path, ledger)
    decision_path.write_text(
        yaml.safe_dump(
            {
                "decision_type": "review_decision",
                "decision_id": "review-001",
                "mission_id": "demo",
                "workflow_id": "test-workflow",
                "reviewed_event": "event-result-001",
                "actor": "human",
                "verdict": "approved",
                "reason": "Verification passed.",
                "evidence_refs": ["artifact-report-001"],
                "accepted_findings": [
                    {"finding_id": "finding-001", "content": "Patch is safe to land."}
                ],
                "rejected_findings": [],
                "next_action": "continue",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "decision",
            "import-review",
            str(workflow_path),
            str(ledger_path),
            str(decision_path),
            "--decision-ref",
            "artifacts/reviews/review-001.yaml",
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)
    updated = load_ledger(ledger_path)

    assert exit_code == 0
    assert payload["event_type"] == "review_decision_recorded"
    assert updated.public_findings[0]["review_decision_id"] == "review-001"
    assert updated.decisions[0]["decision_type"] == "review_decision"


def test_load_ledger_rebuilds_projection_when_cursor_missing(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [
                        {
                            "finding_id": "finding-001",
                            "content": "obsolete",
                            "source_event": "event-001",
                            "source_agent": "worker",
                            "accepted_by": "harness",
                            "review_decision_id": "review-001",
                        }
                    ],
                "decisions": [{"decision_id": "decision-001"}],
                "risks": [{"risk_id": "risk-001"}],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [{"question_id": "question-001"}],
                "event_log": [
                    {
                        "event_id": "event-001",
                        "event_type": "node_outcome_decided",
                        "mission_id": "demo",
                        "workflow_id": "test-workflow",
                        "assignment_id": "assign-001",
                        "node_id": "implement",
                        "role": "coder",
                        "agent_id": "codex-cli",
                        "session_id": "session-001",
                        "source_outcome_id": "outcome-001",
                        "outcome_status": "completed",
                        "actor": "harness",
                        "disposition": "accepted",
                        "accepted_event_types": ["patch_ready"],
                        "post_state_ref": "workspace:abc123",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loaded = load_ledger(ledger_path)

    assert loaded.public_findings == []
    assert loaded.decisions == []
    assert loaded.risks == []
    assert loaded.open_questions == []
    assert loaded.projection["through_event_id"] == "event-001"
    assert loaded.projection["accepted_workspace_ref"] == "workspace:abc123"


def test_loads_writable_runtime_m4_ledger_v3(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    write_ledger(ledger_path, replace(_empty_ledger(), ledger_version=3))

    loaded = load_ledger(ledger_path)

    assert loaded.ledger_version == 3


def test_ledger_writer_rejects_a_stale_loaded_ledger(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    write_ledger(ledger_path, replace(_empty_ledger(), ledger_version=2))
    first = load_ledger(ledger_path)
    stale = load_ledger(ledger_path)
    first = append_ledger_event(
        first,
        {"event_id": "event-first", "event_type": "assignment_created"},
    )
    write_ledger(ledger_path, first)
    stale = append_ledger_event(
        stale,
        {"event_id": "event-stale", "event_type": "assignment_created"},
    )

    with pytest.raises(ProtocolError, match="Ledger write conflict"):
        write_ledger(ledger_path, stale)

    assert [event["event_id"] for event in load_ledger(ledger_path).event_log] == [
        "event-first"
    ]


def test_runs_maintained_mutation_and_retry_demo(tmp_path) -> None:
    report = run_mutation_retry_demo(tmp_path / "rm4-demo")
    ledger = load_ledger(Path(report["artifacts"]["ledger_path"]))

    assert report["status"] == "passed"
    assert report["mode"] == "deterministic-fixture"
    assert all(check["passed"] for check in report["checks"].values())
    assert report["checks"]["deterministic_circuit"]["agent_turns_spent"] == 0
    assert any(
        event.get("event_type") == "workflow_mutation_accepted"
        for event in ledger.event_log
    )
    assert any(
        event.get("event_type") == "assignment_circuit_opened"
        for event in ledger.event_log
    )


def test_real_agent_mutation_demo_requires_explicit_binding(tmp_path) -> None:
    with pytest.raises(ProtocolError, match="requires --target-model"):
        run_mutation_retry_demo(tmp_path / "rm4-real-demo", real_agent=True)


def test_appends_valid_workflow_event() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "projection": {},
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    event = {
        "event_id": "event-001",
        "event_type": "patch_ready",
        "mission_id": "demo",
        "workflow_id": "test-workflow",
        "node_id": "implement",
        "role": "coder",
    }

    updated = append_ledger_event(ledger, event, workflow)

    assert updated.event_log == [event]


def test_cli_appends_ledger_event(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    event_path = tmp_path / "event.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 2,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    event_path.write_text(
        yaml.safe_dump(
            {
                "event_id": "event-001",
                "event_type": "assignment_created",
                "mission_id": "demo",
                "workflow_id": "coder-reviewer-committer-001",
                "assignment_id": "assign-001",
                "node_id": "implement",
                "role": "coder",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "ledger",
            "append",
            str(ledger_path),
            str(event_path),
            "--workflow",
            "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ]
    )
    ledger = load_ledger(ledger_path)

    assert exit_code == 0
    assert ledger.event_log[0]["event_id"] == "event-001"
    assert ledger.event_log[0]["event_type"] == "assignment_created"


def test_rejects_duplicate_or_unknown_ledger_events() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-001",
                    "event_type": "patch_ready",
                    "node_id": "implement",
                    "role": "coder",
                }
            ],
        }
    )

    try:
        append_ledger_event(
            ledger,
            {
                "event_id": "event-001",
                "event_type": "review_approved",
                "node_id": "review",
                "role": "reviewer",
            },
            workflow,
        )
    except ProtocolError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    try:
        append_ledger_event(
            ledger,
            {
                "event_id": "event-002",
                "event_type": "made_up_event",
            },
            workflow,
        )
    except ProtocolError as exc:
        assert "Unknown ledger event type" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_replay_and_gatekeeper_derive_workflow_state() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )

    initial = evaluate_gatekeeper(workflow, ledger)
    assert initial.ready == ["implement"]
    assert initial.decisions["review"].state == "blocked"

    with_patch = append_ledger_event(
        ledger,
        {
            "event_id": "event-001",
            "event_type": "patch_ready",
            "node_id": "implement",
            "role": "coder",
        },
        workflow,
    )
    patch_state = evaluate_gatekeeper(workflow, with_patch)
    assert patch_state.ready == ["review"]
    assert patch_state.decisions["implement"].state == "completed"
    assert patch_state.decisions["commit"].state == "blocked"

    with_review = append_ledger_event(
        with_patch,
        {
            "event_id": "event-002",
            "event_type": "review_approved",
            "node_id": "review",
            "role": "reviewer",
        },
        workflow,
    )
    review_state = evaluate_gatekeeper(workflow, with_review)
    assert review_state.ready == ["commit"]

    with_commit = append_ledger_event(
        with_review,
        {
            "event_id": "event-003",
            "event_type": "commit_created",
            "node_id": "commit",
            "role": "committer",
        },
        workflow,
    )
    replay = replay_workflow(workflow, with_commit)
    assert replay.terminal_complete
    assert replay.nodes["commit"].state == "completed"


def test_replay_is_deterministic_and_explains_expired_gate() -> None:
    workflow = _workflow(
        {
            "gates": [
                {
                    "id": "commit_gate",
                    "node_id": "commit",
                    "requires": {"all_of": ["patch_ready", "review_approved"]},
                }
            ]
        }
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-001",
                    "event_type": "patch_ready",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-002",
                    "event_type": "review_approved",
                    "node_id": "review",
                    "role": "reviewer",
                },
                {
                    "event_id": "event-003",
                    "event_type": "gate_expired",
                    "gate_id": "commit_gate",
                },
            ],
        }
    )

    first = replay_workflow(workflow, ledger).to_dict()
    second = replay_workflow(workflow, ledger).to_dict()

    assert first == second
    assert first["nodes"]["commit"]["state"] == "blocked"
    assert first["nodes"]["commit"]["blocked_reasons"] == [
        {
            "code": "gate_expired",
            "message": "Gate commit_gate has expired",
            "gate_id": "commit_gate",
        }
    ]


def test_replay_tracks_multi_version_history_across_accept_reject_and_supersession() -> None:
    initial, ledger, cursors = _multi_version_replay_history()

    at_first_proposal = replay_workflow(
        initial, ledger, through_event_id=cursors["proposal_one"]
    )
    at_first_acceptance = replay_workflow(
        initial, ledger, through_event_id=cursors["acceptance_one"]
    )
    at_second_rejection = replay_workflow(
        initial, ledger, through_event_id=cursors["rejection_two"]
    )
    at_second_acceptance = replay_workflow(
        initial, ledger, through_event_id=cursors["acceptance_three"]
    )
    current = replay_workflow(initial, ledger)
    current_again = replay_workflow(initial, ledger)
    at_final = replay_workflow(
        initial, ledger, through_event_id=ledger.event_log[-1]["event_id"]
    )

    assert at_first_proposal.workflow_version_id == at_first_proposal.assignment_validity[
        "assign-finish-001"
    ].active_version_id
    assert "verify" not in at_first_proposal.nodes
    assert at_first_proposal.mutation_proposals[cursors["proposal_one"]].state == "pending"

    assert set(at_first_acceptance.nodes) == {"start", "finish", "verify"}
    assert at_first_acceptance.nodes["verify"].state == "runnable"
    assert at_first_acceptance.assignment_validity["assign-finish-001"].status == (
        "affected"
    )

    assert at_second_rejection.workflow_version_id == at_first_acceptance.workflow_version_id
    assert at_second_rejection.mutation_proposals[cursors["proposal_two"]].state == (
        "rejected"
    )
    assert set(at_second_rejection.nodes) == {"start", "finish", "verify"}

    assert set(at_second_acceptance.nodes) == {"start", "finish", "verify", "audit"}
    assert at_second_acceptance.workflow_version_id != at_second_rejection.workflow_version_id
    assert at_second_acceptance.assignment_validity["assign-verify-001"].status == (
        "affected"
    )
    assert at_second_acceptance.assignment_validity["assign-verify-001"].transition_event_id == (
        cursors["acceptance_three"]
    )
    assert at_second_acceptance.nodes["audit"].state == "runnable"

    assert current == current_again
    assert at_final == current
    assert current.nodes["verify"].assignment_attempts[0].state == "superseded"
    assert current.nodes["finish"].blocked_reasons[0].code == "superseded"


def test_stale_mutation_intake_preserves_workflow_version_projection(tmp_path) -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "shell-dummy"
        ),
        workflow,
    )
    proposed = append_ledger_event(ledger, _mutation_proposed_event(), workflow)
    changed = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": {
                "supersede_assignments": ["assign-review-001"]
            },
        },
        workflow,
    )
    record = _mutation_session_record(tmp_path, assignment, _mutation_intent())

    before = replay_workflow(workflow, changed)
    before_projection = project_workflow_versions(workflow, changed)
    staged = stage_session_record(
        workflow, changed, assignment, record, artifact_root=tmp_path
    )
    after = replay_workflow(workflow, staged.ledger)
    after_projection = project_workflow_versions(workflow, staged.ledger)
    at_result_submission = replay_workflow(
        workflow,
        staged.ledger,
        through_event_id=staged.ledger.event_log[-1]["event_id"],
    )

    assert staged.mutation_intake_disposition is not None
    assert staged.mutation_intake_disposition["status"] == "stale"
    assert staged.ledger.event_log[-1]["event_type"] == "result_submitted"
    assert sum(
        event["event_type"] == "workflow_mutation_proposed"
        for event in staged.ledger.event_log
    ) == 1
    assert before.workflow_version_id == after.workflow_version_id
    assert before_projection.versions == after_projection.versions
    assert before_projection.current_version_id == after_projection.current_version_id
    assert [event.workflow_version_id for event in after_projection.events[:-1]] == [
        event.workflow_version_id for event in before_projection.events
    ]
    assert after_projection.events[-1].workflow_version_id == (
        before_projection.current_version_id
    )
    assert after == at_result_submission


def test_prefix_replay_synthetic_ledger_baseline_is_deterministic() -> None:
    initial, ledger, _ = _multi_version_replay_history()
    current_workflow = materialize_current_workflow(initial, ledger)
    for index in range(24):
        assignment_id = f"assign-audit-{index:03d}"
        assignment = export_assignment(
            initial,
            ledger,
            "audit",
            assignment_id=assignment_id,
            force=True,
        )
        ledger = append_ledger_event(
            ledger,
            build_assignment_created_event(
                current_workflow,
                assignment,
                f"session-audit-{index:03d}",
                "codex-cli",
            ),
            current_workflow,
        )
        ledger = append_ledger_event(
            ledger,
                {
                    "event_id": f"event-audit-timeout-{index:03d}",
                    "event_type": "worker_timeout",
                    "assignment_id": assignment_id,
                    "node_id": "audit",
                    "role": "worker",
                },
                current_workflow,
            )

    sample_ordinals = list(range(0, len(ledger.event_log), 5))
    started = time.perf_counter()
    first_pass = [
        replay_workflow(initial, ledger, through_event_ordinal=ordinal).to_dict()
        for ordinal in sample_ordinals
    ]
    second_pass = [
        replay_workflow(initial, ledger, through_event_ordinal=ordinal).to_dict()
        for ordinal in sample_ordinals
    ]
    elapsed_ms = (time.perf_counter() - started) * 1000
    current = replay_workflow(initial, ledger).to_dict()
    at_final = replay_workflow(
        initial,
        ledger,
        through_event_id=ledger.event_log[-1]["event_id"],
    ).to_dict()

    assert len(ledger.event_log) == 59
    assert first_pass == second_pass
    assert current == at_final
    assert elapsed_ms < 250.0


def test_gatekeeper_supports_any_of_waits() -> None:
    workflow = Workflow.from_dict(
        {
            "workflow_id": "any-of-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "merge": {
                    "can_emit": ["merge_ready"],
                    "can_consume": ["inventory_complete"],
                },
            },
            "events": {
                "inventory_complete": {"producer_roles": ["inventory"]},
                "merge_ready": {"producer_roles": ["merge"]},
            },
            "nodes": [
                {"id": "docs", "role": "inventory", "emits": ["inventory_complete"]},
                {"id": "tests", "role": "inventory", "emits": ["inventory_complete"]},
                {
                    "id": "merge",
                    "role": "merge",
                    "waits_for": {
                        "any_of": [
                            "docs.inventory_complete",
                            "tests.inventory_complete",
                        ]
                    },
                    "emits": ["merge_ready"],
                },
            ],
            "terminal_events": ["merge_ready"],
        }
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )

    initial = evaluate_gatekeeper(workflow, ledger)
    assert initial.ready == ["docs", "tests"]
    assert initial.decisions["merge"].state == "blocked"
    assert {
        reason.missing_ref for reason in initial.decisions["merge"].blocked_reasons
    } == {"docs.inventory_complete", "tests.inventory_complete"}

    with_docs = append_ledger_event(
        ledger,
        {
            "event_id": "event-001",
            "event_type": "inventory_complete",
            "node_id": "docs",
            "role": "inventory",
        },
        workflow,
    )
    result = evaluate_gatekeeper(workflow, with_docs)

    assert result.ready == ["merge", "tests"]
    assert result.decisions["merge"].blocked_reasons == []


def test_gatekeeper_respects_node_qualified_refs() -> None:
    workflow = Workflow.from_dict(
        {
            "workflow_id": "qualified-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "merge": {
                    "can_emit": ["merge_ready"],
                    "can_consume": ["inventory_complete"],
                },
            },
            "events": {
                "inventory_complete": {"producer_roles": ["inventory"]},
                "merge_ready": {"producer_roles": ["merge"]},
            },
            "nodes": [
                {"id": "docs", "role": "inventory", "emits": ["inventory_complete"]},
                {"id": "tests", "role": "inventory", "emits": ["inventory_complete"]},
                {
                    "id": "merge",
                    "role": "merge",
                    "waits_for": {
                        "all_of": [
                            "docs.inventory_complete",
                            "tests.inventory_complete",
                        ]
                    },
                    "emits": ["merge_ready"],
                },
            ],
            "terminal_events": ["merge_ready"],
        }
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-001",
                    "event_type": "inventory_complete",
                    "node_id": "docs",
                    "role": "inventory",
                }
            ],
        }
    )

    partial = evaluate_gatekeeper(workflow, ledger)
    assert partial.decisions["merge"].state == "blocked"
    assert partial.decisions["merge"].blocked_reasons[0].missing_ref == (
        "tests.inventory_complete"
    )

    complete = append_ledger_event(
        ledger,
        {
            "event_id": "event-002",
            "event_type": "inventory_complete",
            "node_id": "tests",
            "role": "inventory",
        },
        workflow,
    )
    assert evaluate_gatekeeper(workflow, complete).ready == ["merge"]


def test_artifact_hash_validation(tmp_path) -> None:
    artifact_path = tmp_path / "artifacts" / "report.md"
    artifact_path.parent.mkdir()
    artifact_path.write_text("result", encoding="utf-8")
    digest = sha256_file(artifact_path)

    result = validate_artifact_record(
        {
            "artifact_id": "artifact-001",
            "path": "artifacts/report.md",
            "sha256": digest,
            "created_by": "coder",
            "source_event": "event-001",
            "mutable": False,
        },
        tmp_path,
    )

    assert result.status == "valid"

    artifact_path.write_text("changed", encoding="utf-8")
    changed = validate_artifact_record(
        {
            "artifact_id": "artifact-001",
            "path": "artifacts/report.md",
            "sha256": digest,
            "created_by": "coder",
            "source_event": "event-001",
            "mutable": False,
        },
        tmp_path,
    )
    assert changed.status == "invalid"


def test_artifact_missing_and_mutable_validation(tmp_path) -> None:
    missing = validate_artifact_record(
        {
            "artifact_id": "artifact-001",
            "path": "artifacts/missing.md",
            "sha256": "0" * 64,
            "created_by": "coder",
            "source_event": "event-001",
            "mutable": False,
        },
        tmp_path,
    )
    assert missing.status == "missing"

    try:
        validate_artifact_record(
            {
                "artifact_id": "artifact-002",
                "path": "artifacts/draft.md",
                "sha256": "0" * 64,
                "created_by": "coder",
                "source_event": "event-001",
                "mutable": True,
            },
            tmp_path,
        )
    except ProtocolError as exc:
        assert "mutable: false" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_artifact_path_cannot_escape_root(tmp_path) -> None:
    try:
        validate_artifact_record(
            {
                "artifact_id": "artifact-001",
                "path": "../outside.md",
                "sha256": "0" * 64,
                "created_by": "coder",
                "source_event": "event-001",
                "mutable": False,
            },
            tmp_path,
        )
    except ProtocolError as exc:
        assert "escapes artifact root" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_cli_artifact_verify(tmp_path) -> None:
    artifact_path = tmp_path / "artifacts" / "report.md"
    artifact_path.parent.mkdir()
    artifact_path.write_text("result", encoding="utf-8")
    digest = sha256_file(artifact_path)
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [
                    {
                        "artifact_id": "artifact-001",
                        "path": "artifacts/report.md",
                        "sha256": digest,
                        "created_by": "coder",
                        "source_event": "event-001",
                        "mutable": False,
                    }
                ],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ledger = load_ledger(ledger_path)

    assert main(["artifact", "verify", str(ledger_path), "--root", str(tmp_path)]) == 0
    assert verify_ledger_artifacts(ledger, tmp_path)[0].status == "valid"


def test_exports_assignment_only_for_runnable_node() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )

    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")

    assert assignment.assignment_id == "assign-001"
    assert assignment.expected_events == ["patch_ready"]
    assert "update_canonical_ledger" in assignment.forbidden_actions
    assert assignment.visible_context["workflow_version_id"].startswith(
        "test-workflow:v0000:"
    )
    structure = assignment.visible_context["workflow_structure"]
    assert structure["events"] == [
        "commit_created",
        "patch_ready",
        "review_approved",
    ]
    assert structure["active_assignments"] == [
        {"assignment_id": "assign-001", "node_id": "implement"}
    ]
    prompt = render_assignment_prompt(assignment)
    assert "patch_ready" in prompt
    assert "## Structural Escape Hatch" in prompt
    assert "intent_type: workflow_mutation" in prompt
    assert "Do not choose proposal IDs" in prompt
    assert "mutation_proposal_refs" not in prompt
    assert load_assignment(assignment.to_dict()) == assignment

    try:
        export_assignment(workflow, ledger, "commit")
    except ProtocolError as exc:
        assert "not runnable" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    forced = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-forced",
        force=True,
    )
    assert forced.node_id == "commit"
    assert forced.expected_events == ["commit_created"]


def test_cli_assignment_export(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "assignment",
            "export",
            "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
            "examples/missions/demo/ledger.yaml",
            "implement",
            "--assignment-id",
            "assign-demo",
        ]
    )
    captured = capsys.readouterr()
    payload = yaml.safe_load(captured.out)

    assert exit_code == 0
    assert payload["assignment_id"] == "assign-demo"
    assert payload["node_id"] == "implement"
    assert "visible_context" in payload
    assert "update_canonical_ledger" in payload["forbidden_actions"]


def test_compile_context_capsule_scopes_dependency_closure_deterministically() -> None:
    workflow = _context_workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Ship the reviewed patch",
            "current_plan_ref": "workflow.yaml",
            "projection": {},
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-001",
            "event_type": "node_outcome_decided",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "implement",
            "source_outcome_id": "outcome-001",
            "actor": "harness",
            "disposition": "accepted",
            "outcome_status": "completed",
            "accepted_event_types": ["patch_ready"],
            "pre_state_ref": "workspace:abc123",
            "post_state_ref": "workspace:def456",
        },
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-inventory",
            "event_type": "inventory_ready",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "inventory",
            "role": "inventory",
            "agent_id": "inventory-agent",
        },
        workflow,
    )
    ledger = apply_review_decision(
        ledger,
        load_review_decision(
            {
                "decision_type": "review_decision",
                "decision_id": "review-inventory",
                "mission_id": "demo",
                "workflow_id": workflow.workflow_id,
                "reviewed_event": "event-inventory",
                "actor": "orchestrator",
                "verdict": "approved",
                "reason": "Inventory fact accepted.",
                "evidence_refs": ["artifact-inventory-report"],
                "accepted_findings": [
                    {
                        "finding_id": "finding-inventory",
                        "content": "Inventory branch found a separate issue.",
                    }
                ],
                "rejected_findings": [],
                "next_action": "continue",
            }
        ),
        workflow=workflow,
        decision_ref="artifacts/reviews/review-inventory.yaml",
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-patch",
            "event_type": "patch_ready",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "implement",
            "role": "coder",
            "agent_id": "coder-agent",
        },
        workflow,
    )
    ledger = apply_review_decision(
        ledger,
        load_review_decision(
            {
                "decision_type": "review_decision",
                "decision_id": "review-implement",
                "mission_id": "demo",
                "workflow_id": workflow.workflow_id,
                "reviewed_event": "event-patch",
                "actor": "orchestrator",
                "verdict": "approved",
                "reason": "Patch fact accepted.",
                "evidence_refs": ["artifact-patch-report"],
                "accepted_findings": [
                    {
                        "finding_id": "finding-implement",
                        "content": "Implementation produced the requested patch.",
                    }
                ],
                "rejected_findings": [],
                "next_action": "continue",
            }
        ),
        workflow=workflow,
        decision_ref="artifacts/reviews/review-implement.yaml",
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-review",
            "event_type": "review_approved",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "review",
            "role": "reviewer",
            "agent_id": "reviewer-agent",
        },
        workflow,
    )
    ledger = apply_review_decision(
        ledger,
        load_review_decision(
            {
                "decision_type": "review_decision",
                "decision_id": "review-review",
                "mission_id": "demo",
                "workflow_id": workflow.workflow_id,
                "reviewed_event": "event-review",
                "actor": "human",
                "verdict": "approved",
                "reason": "Review fact accepted.",
                "evidence_refs": ["artifact-review-report"],
                "accepted_findings": [
                    {
                        "finding_id": "finding-review",
                        "content": "Human review approved the patch.",
                    }
                ],
                "rejected_findings": [],
                "next_action": "continue",
            }
        ),
        workflow=workflow,
        decision_ref="artifacts/reviews/review-review.yaml",
    )

    first = compile_context_capsule(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-commit",
    )
    second = compile_context_capsule(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-commit",
    )

    assert first == second
    assert first.workspace_ref == "workspace:def456"
    assert first.dependency_node_ids == ["commit", "implement", "review"]
    assert [item["finding_id"] for item in first.accepted_facts] == [
        "finding-implement",
        "finding-review",
    ]
    assert [item["decision_id"] for item in first.accepted_decisions] == [
        "review-implement",
        "review-review",
    ]
    assert all(ref.get("ref") != "artifact-inventory-report" for ref in first.artifact_refs)
    assert [ref["ref"] for ref in first.artifact_refs] == [
        "artifact-patch-report",
        "artifact-review-report",
    ]


def test_export_assignment_embeds_context_capsule_and_artifact_refs() -> None:
    workflow = _context_workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Ship the reviewed patch",
            "current_plan_ref": "workflow.yaml",
            "projection": {},
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-001",
            "event_type": "node_outcome_decided",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "implement",
            "source_outcome_id": "outcome-001",
            "actor": "harness",
            "disposition": "accepted",
            "outcome_status": "completed",
            "accepted_event_types": ["patch_ready"],
            "pre_state_ref": "workspace:abc123",
            "post_state_ref": "workspace:def456",
        },
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-patch",
            "event_type": "patch_ready",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "implement",
            "role": "coder",
            "agent_id": "coder-agent",
        },
        workflow,
    )
    ledger = apply_review_decision(
        ledger,
        load_review_decision(
            {
                "decision_type": "review_decision",
                "decision_id": "review-implement",
                "mission_id": "demo",
                "workflow_id": workflow.workflow_id,
                "reviewed_event": "event-patch",
                "actor": "orchestrator",
                "verdict": "approved",
                "reason": "Patch fact accepted.",
                "evidence_refs": ["artifact-patch-report"],
                "accepted_findings": [
                    {
                        "finding_id": "finding-implement",
                        "content": "Implementation produced the requested patch.",
                    }
                ],
                "rejected_findings": [],
                "next_action": "continue",
            }
        ),
        workflow=workflow,
        decision_ref="artifacts/reviews/review-implement.yaml",
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-review",
            "event_type": "review_approved",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "review",
            "role": "reviewer",
            "agent_id": "reviewer-agent",
        },
        workflow,
    )

    assignment = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-commit",
        force=True,
    )
    capsule = assignment.visible_context["context_capsule"]

    assert assignment.artifact_refs == [{"ref": "artifact-patch-report"}]
    assert capsule["context_capsule_id"] == "context-assign-commit"
    assert capsule["dependency_node_ids"] == ["commit", "implement", "review"]
    assert capsule["role_permissions"]["can_consume"] == ["patch_ready", "review_approved"]
    assert capsule["accepted_facts"][0]["finding_id"] == "finding-implement"
    assert "## Artifact Refs" in render_assignment_prompt(assignment)


def test_resolve_context_request_grants_scoped_artifact() -> None:
    workflow = _context_workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Ship the reviewed patch",
            "current_plan_ref": "workflow.yaml",
            "projection": {},
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [
                {
                    "artifact_id": "artifact-patch-report",
                    "path": "artifacts/patch-report.md",
                    "sha256": "abc123",
                    "source_event": "event-patch",
                }
            ],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-patch",
            "event_type": "patch_ready",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "implement",
            "role": "coder",
            "agent_id": "coder-agent",
        },
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-review",
            "event_type": "review_approved",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "review",
            "role": "reviewer",
            "agent_id": "reviewer-agent",
        },
        workflow,
    )
    assignment = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-commit",
        force=True,
    )
    request = load_context_request(
        {
            "context_request_id": "context-request-001",
            "assignment_id": "assign-commit",
            "missing_information": "Need the exact patch report body.",
            "requested_refs": ["artifact-patch-report"],
            "expected_value": "Validate whether the patch satisfies the commit gate.",
        }
    )

    resolution = resolve_context_request(assignment, ledger, request)

    assert resolution.status == "granted"
    assert resolution.policy_version == "context-v1"
    assert resolution.denied_refs == []
    assert resolution.unavailable_refs == []
    assert resolution.granted_artifacts == [
        {
            "artifact_id": "artifact-patch-report",
            "path": "artifacts/patch-report.md",
            "sha256": "abc123",
            "source_event": "event-patch",
        }
    ]


def test_resolve_context_request_reports_denied_and_unavailable_refs() -> None:
    workflow = _context_workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Ship the reviewed patch",
            "current_plan_ref": "workflow.yaml",
            "projection": {},
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-patch",
            "event_type": "patch_ready",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "implement",
            "role": "coder",
            "agent_id": "coder-agent",
        },
        workflow,
    )
    ledger = apply_review_decision(
        ledger,
        load_review_decision(
            {
                "decision_type": "review_decision",
                "decision_id": "review-implement",
                "mission_id": "demo",
                "workflow_id": workflow.workflow_id,
                "reviewed_event": "event-patch",
                "actor": "orchestrator",
                "verdict": "approved",
                "reason": "Patch fact accepted.",
                "evidence_refs": ["artifact-patch-report"],
                "accepted_findings": [
                    {
                        "finding_id": "finding-implement",
                        "content": "Implementation produced the requested patch.",
                    }
                ],
                "rejected_findings": [],
                "next_action": "continue",
            }
        ),
        workflow=workflow,
        decision_ref="artifacts/reviews/review-implement.yaml",
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-review",
            "event_type": "review_approved",
            "mission_id": "demo",
            "workflow_id": workflow.workflow_id,
            "node_id": "review",
            "role": "reviewer",
            "agent_id": "reviewer-agent",
        },
        workflow,
    )
    assignment = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-commit",
        force=True,
    )
    request = load_context_request(
        {
            "context_request_id": "context-request-002",
            "assignment_id": "assign-commit",
            "missing_information": "Need more evidence.",
            "requested_refs": ["artifact-patch-report", "artifact-inventory-report"],
            "expected_value": "Decide whether to continue or escalate.",
        }
    )

    resolution = resolve_context_request(assignment, ledger, request)

    assert resolution.status == "partially_granted" or resolution.status == "unavailable"
    assert resolution.granted_artifacts == []
    assert resolution.denied_refs == [
        {
            "requested_ref": "artifact-inventory-report",
            "reason": "not_in_assignment_scope",
        }
    ]
    assert resolution.unavailable_refs == [
        {
            "requested_ref": "artifact-patch-report",
            "reason": "artifact_payload_unavailable",
        }
    ]


def test_codex_context_request_resolves_and_resumes_same_logical_session(
    tmp_path,
    monkeypatch,
) -> None:
    workflow = _workflow()
    ledger = replace(
        _empty_ledger(),
        ledger_version=2,
        artifacts=[
            {
                "artifact_id": "artifact-api-contract",
                "path": "artifacts/api-contract.md",
                "sha256": "abc123",
                "source_event": "event-contract",
            },
            {
                "artifact_id": "artifact-secret-branch",
                "path": "artifacts/secret.md",
                "sha256": "secret",
                "source_event": "event-secret",
            },
        ],
    )
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-context-continuation",
    )
    assignment = replace(
        assignment,
        artifact_refs=[{"artifact_id": "artifact-api-contract"}],
    )
    mission, packet = _dispatch_fixture(
        workflow,
        assignment,
        "packet-context-continuation",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    prompts: list[str] = []
    workdirs: list[Path] = []

    def runner(command, **kwargs):
        prompts.append(kwargs["input"])
        workdirs.append(Path(kwargs["cwd"]))
        if len(prompts) == 1:
            Path(kwargs["cwd"]).joinpath("requested-context.txt").write_text(
                "requesting\n", encoding="utf-8"
            )
            text = (
                "status: context_requested\n"
                "emitted_events: []\n"
                "verification:\n  status: not_run\n"
                "context_request:\n"
                "  missing_information: Need the API contract.\n"
                "  requested_refs: [artifact-api-contract]\n"
                "  expected_value: Avoid guessing the existing API.\n"
            )
        else:
            assert "artifact-api-contract" in kwargs["input"]
            assert "artifact-secret-branch" not in kwargs["input"]
            Path(kwargs["cwd"]).joinpath("continued.txt").write_text(
                "continued\n", encoding="utf-8"
            )
            text = (
                "status: completed\n"
                "emitted_events: [patch_ready]\n"
                "verification:\n  status: passed\n"
            )
        stdout = (
            '{"type":"item.completed","item":{"id":"item_0",'
            '"type":"agent_message","text":'
            + json.dumps(text)
            + "}}\n"
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}\n'
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    record = dispatch_session(
        mission,
        workflow,
        packet,
        agent_id="codex-cli",
        workdir=tmp_path,
        dispatch_packet_path=tmp_path / "dispatch.yaml",
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-context-continuation",
        command_runner=runner,
        context_ledger=ledger,
    )

    assert len(prompts) == 2
    assert workdirs[0] == workdirs[1]
    assert record.status == "completed"
    assert record.session_id == "session-context-continuation"
    assert record.outcome_metrics["continuation_turn_count"] == 1
    assert record.outcome_metrics["context_request_count"] == 1
    assert record.outcome_metrics["added_context_tokens_estimate"] > 0
    assert record.outcome_metrics["changed_files_count"] == 2
    assert Path(record.workspace["path"]).joinpath("requested-context.txt").is_file()
    assert Path(record.workspace["path"]).joinpath("continued.txt").is_file()
    assert record.extraction["context_requests"][0]["resumed"] is True
    assert [event["event_type"] for event in record.extraction["context_events"]] == [
        "context_requested",
        "context_resolved",
        "context_resumed",
    ]

    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            record.session_id,
            record.agent_id,
        ),
        workflow,
    )
    staged = stage_session_record(workflow, ledger, assignment, record)
    assert [event["event_type"] for event in staged.ledger.event_log[-4:]] == [
        "context_requested",
        "context_resolved",
        "context_resumed",
        "result_submitted",
    ]
    replay = replay_workflow(workflow, staged.ledger)
    assert replay.nodes["implement"].state == "blocked"
    assert replay.nodes["implement"].blocked_reasons[0].code == "awaiting_acceptance"


def test_context_continuation_denied_request_never_resumes(tmp_path, monkeypatch) -> None:
    workflow = _workflow()
    ledger = replace(
        _empty_ledger(),
        ledger_version=2,
        artifacts=[{"artifact_id": "artifact-secret", "path": "secret.md"}],
    )
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-context-denied",
    )
    assignment = replace(assignment, artifact_refs=[])
    mission, packet = _dispatch_fixture(workflow, assignment, "packet-context-denied")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = 0

    def runner(command, **_kwargs):
        nonlocal calls
        calls += 1
        text = (
            "status: context_requested\n"
            "emitted_events: []\n"
            "verification:\n  status: not_run\n"
            "context_request:\n"
            "  missing_information: Need secret branch history.\n"
            "  requested_refs: [artifact-secret]\n"
            "  expected_value: Inspect unrelated history.\n"
        )
        stdout = (
            '{"type":"item.completed","item":{"id":"item_0",'
            '"type":"agent_message","text":'
            + json.dumps(text)
            + "}}\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    record = dispatch_session(
        mission,
        workflow,
        packet,
        agent_id="codex-cli",
        workdir=tmp_path,
        dispatch_packet_path=tmp_path / "dispatch.yaml",
        target_model="gpt-5",
        target_provider="openai",
        command_runner=runner,
        context_ledger=ledger,
    )

    assert calls == 1
    assert record.status == "blocked"
    assert record.exit["reason"] == "context_denied"
    assert record.result_proposal is None
    assert record.extraction["context_requests"][0]["resumed"] is False
    assert record.extraction["context_events"][-1]["event_type"] == "context_resolved"

    replay_ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            record.session_id,
            record.agent_id,
        ),
        workflow,
    )
    for event in record.extraction["context_events"]:
        replay_ledger = append_ledger_event(replay_ledger, event, workflow)
    replay = replay_workflow(workflow, replay_ledger)
    assert replay.nodes["implement"].assignment_attempts[0].state == "context_blocked"
    assert replay.nodes["implement"].blocked_reasons[0].code == "context_unresolved"


def test_context_resolution_enforces_expiry_and_added_token_budget() -> None:
    workflow = _workflow()
    ledger = replace(
        _empty_ledger(),
        artifacts=[
            {
                "artifact_id": "artifact-large",
                "path": "artifacts/large.md",
                "sha256": "a" * 256,
            }
        ],
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-context")
    assignment = replace(assignment, artifact_refs=[{"artifact_id": "artifact-large"}])
    intent = load_context_request_intent(
        {
            "missing_information": "Need bounded evidence.",
            "requested_refs": ["artifact-large"],
            "expected_value": "Use the exact contract.",
        }
    )
    started = datetime(2026, 7, 2, tzinfo=timezone.utc)
    request = build_context_request(
        intent,
        assignment_id=assignment.assignment_id,
        session_id="session-context",
        continuation_id="continuation-session-context",
        request_index=1,
        now=started,
        ttl_seconds=10,
    )

    expired = resolve_context_request(
        assignment,
        ledger,
        request,
        now=started + timedelta(seconds=11),
    )
    over_budget = resolve_context_request(
        assignment,
        ledger,
        request,
        max_added_tokens=1,
        now=started + timedelta(seconds=1),
    )

    assert expired.status == "expired"
    assert expired.granted_artifacts == []
    assert over_budget.status == "budget_exceeded"
    assert over_budget.granted_artifacts == []
    assert over_budget.denied_refs[0]["reason"] == "context_token_budget_exceeded"


def test_cli_assignment_prompt_export(capsys) -> None:
    exit_code = main(
        [
            "assignment",
            "export",
            "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
            "examples/missions/demo/ledger.yaml",
            "implement",
            "--assignment-id",
            "assign-demo",
            "--prompt",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "# Assignment assign-demo" in captured.out
    assert "## Forbidden Actions" in captured.out
    assert "patch_ready" in captured.out


def test_imports_result_proposal_as_event() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "manual-worker",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 1,
                "usage_confidence": "none",
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)

    assert updated.event_log[0]["event_type"] == "result_submitted"
    assert updated.event_log[0]["result"]["result_id"] == "result-001"
    assert updated.event_log[1]["event_type"] == "patch_ready"
    assert updated.event_log[1]["source_event_id"] == "event-result-001"
    assert updated.public_findings == []


def test_rejects_result_with_unauthorized_event() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "manual-worker",
            "status": "completed",
            "emitted_events": ["review_approved"],
        }
    )

    try:
        import_result_proposal(workflow, ledger, assignment, result)
    except ProtocolError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_rejects_result_missing_required_outcome_metrics() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "manual-worker",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "outcome_metrics": {
                "changed_files_count": 1,
            },
        }
    )

    try:
        import_result_proposal(workflow, ledger, assignment, result)
    except ProtocolError as exc:
        assert "wall_time_ms" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_cli_result_import(tmp_path) -> None:
    workflow_path = Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml")
    ledger_path = tmp_path / "ledger.yaml"
    assignment_path = tmp_path / "assignment.yaml"
    result_path = tmp_path / "result.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 2,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assignment_path.write_text(
        yaml.safe_dump(
            export_assignment(
                load_workflow(workflow_path),
                load_ledger(ledger_path),
                "implement",
                assignment_id="assign-001",
            ).to_dict(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result_path.write_text(
        yaml.safe_dump(
            {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "manual-worker",
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 1,
                },
                "verification": {"status": "passed"},
                "native_log_refs": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "result",
            "import",
            str(workflow_path),
            str(ledger_path),
            str(assignment_path),
            str(result_path),
        ]
    )
    updated = load_ledger(ledger_path)

    assert exit_code == 0
    assert updated.public_findings == []
    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted"
    ]
    assert replay_workflow(load_workflow(workflow_path), updated).nodes[
        "implement"
    ].blocked_reasons[0].code == "awaiting_acceptance"


def test_cli_session_import(tmp_path, capsys) -> None:
    workflow_path = Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml")
    ledger_path = tmp_path / "ledger.yaml"
    assignment_path = tmp_path / "assignment.yaml"
    session_path = tmp_path / "session.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 2,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assignment = export_assignment(
        load_workflow(workflow_path),
        load_ledger(ledger_path),
        "implement",
        assignment_id="assign-001",
    )
    assignment_path.write_text(yaml.safe_dump(assignment.to_dict(), sort_keys=False), encoding="utf-8")
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "workspace": {
                    "path": str(tmp_path),
                    "source_root": str(tmp_path),
                    "session_root": str(tmp_path),
                },
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 0,
                },
                "extraction": {"status": "native_stream_captured"},
                "result_proposal": {
                    "result_id": "result-session-001",
                    "assignment_id": "assign-001",
                    "agent_id": "codex-cli",
                    "status": "completed",
                    "effective_model": "gpt-5.4-mini",
                    "effective_provider": "openai-compatible",
                    "emitted_events": ["patch_ready"],
                    "artifacts": [],
                    "outcome_metrics": {
                        "wall_time_ms": 1000,
                        "changed_files_count": 0,
                    },
                    "verification": {"status": "passed"},
                    "native_log_refs": [],
                    "mutation_proposal_refs": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "session",
            "import",
            str(workflow_path),
            str(ledger_path),
            str(assignment_path),
            str(session_path),
        ]
    )
    updated = load_ledger(ledger_path)
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert [event["event_type"] for event in updated.event_log] == ["result_submitted"]
    assert payload["status"] == "awaiting_acceptance"
    assert Path(payload["result_path"]).exists()
    assert Path(payload["outcome_path"]).exists()


def test_result_import_advances_gatekeeper_and_replay_state() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "manual-worker",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)
    gatekeeper = evaluate_gatekeeper(workflow, updated)
    replay = replay_workflow(workflow, updated)

    assert gatekeeper.ready == ["review"]
    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"


def test_builds_node_outcome_from_session_record() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    session_record = {
        "session_id": "session-001",
        "assignment_id": "assign-001",
        "agent_id": "codex-cli",
        "status": "completed",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "exit": {"code": 0, "reason": "completed"},
        "native_logs": {"stdout": "", "stderr": ""},
        "diff_refs": [{"kind": "inline_patch", "bytes": 12}],
        "artifacts": [],
        "workspace": {
            "pre_state_ref": "workspace:before",
            "post_state_ref": "workspace:after",
        },
        "outcome_metrics": {
            "wall_time_ms": 1000,
            "changed_files_count": 1,
            "patch_bytes": 12,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        "extraction": {"status": "native_stream_captured"},
        "result_proposal": {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai-compatible",
            "emitted_events": [],
            "artifacts": [],
            "outcome_metrics": {},
            "verification": {"status": "not_run"},
            "native_log_refs": [],
            "mutation_proposal_refs": [],
        },
    }

    outcome = node_outcome_from_session(assignment, session_record, outcome_id="outcome-001")
    loaded = load_node_outcome(outcome.to_dict())

    assert loaded.outcome_id == "outcome-001"
    assert loaded.status == "completed"
    assert loaded.node_id == "implement"
    assert loaded.effective_model == "gpt-5.4-mini"
    assert loaded.pre_state_ref == "workspace:before"
    assert loaded.post_state_ref == "workspace:after"
    assert loaded.observed_delta["changed_files_count"] == 1
    assert loaded.observed_delta["patch_bytes"] == 12


def test_appends_node_outcome_decision_event() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    outcome = node_outcome_from_session(
        assignment,
        {
            "session_id": "session-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "exit": {"code": 0, "reason": "completed"},
            "native_logs": {"stdout": "", "stderr": ""},
            "diff_refs": [],
            "artifacts": [],
            "workspace": {},
            "outcome_metrics": {"wall_time_ms": 1000, "changed_files_count": 0},
            "extraction": {"status": "native_stream_captured"},
            "result_proposal": {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "effective_model": "gpt-5.4-mini",
                "effective_provider": "openai-compatible",
                "emitted_events": [],
                "artifacts": [],
                "outcome_metrics": {},
                "verification": {"status": "not_run"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        },
        outcome_id="outcome-001",
    )
    event = build_node_outcome_decision_event(
        outcome,
        event_id="event-outcome-001",
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        actor="harness",
        disposition="accepted",
        accepted_event_types=["patch_ready"],
        validation_rule="manual_test_v1",
        created_at="2026-01-01T00:00:02Z",
    )

    updated = append_ledger_event(ledger, event, workflow)

    assert updated.event_log[0]["event_type"] == "node_outcome_decided"
    assert updated.event_log[0]["source_outcome_id"] == "outcome-001"
    assert updated.event_log[0]["accepted_event_types"] == ["patch_ready"]


def test_import_session_record_appends_result_and_outcome_decision(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai-compatible",
            "emitted_events": ["patch_ready"],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=f"cat <<'EOF'\n{payload}\nEOF",
            session_id="session-001",
        ),
        assignment,
    )

    updated = import_session_record(workflow, ledger, assignment, record)
    replay = replay_workflow(workflow, updated)

    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted",
        "patch_ready",
        "node_outcome_decided",
    ]
    assert updated.event_log[-1]["source_outcome_id"] == "outcome-session-001"
    assert updated.event_log[-1]["accepted_event_types"] == ["patch_ready"]
    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"


def test_import_session_record_marks_outcome_stale_when_pre_state_is_outdated(
    tmp_path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = _empty_ledger()
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-old",
            "event_type": "node_outcome_decided",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-old",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "session_id": "session-old",
            "source_outcome_id": "outcome-old",
            "outcome_status": "completed",
            "actor": "harness",
            "disposition": "accepted",
            "accepted_event_types": [],
            "post_state_ref": "workspace:accepted-current",
        },
        workflow,
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001", force=True)
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="shell-dummy",
        ),
        workflow,
    )
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai-compatible",
            "emitted_events": ["patch_ready"],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=f"cat <<'EOF'\n{payload}\nEOF",
            session_id="session-001",
        ),
        assignment,
    )
    record = replace(
        record,
        workspace={
            **record.workspace,
            "pre_state_ref": "workspace:older-pre-state",
            "post_state_ref": "workspace:new-post-state",
        },
    )

    updated = import_session_record(workflow, ledger, assignment, record)
    replay = replay_workflow(workflow, updated)

    assert updated.event_log[-1]["event_type"] == "node_outcome_decided"
    assert updated.event_log[-1]["outcome_status"] == "stale"
    assert updated.event_log[-1]["accepted_event_types"] == []
    assert replay.nodes["implement"].state == "blocked"
    assert replay.nodes["review"].state == "blocked"


def test_replay_accepts_outcome_decision_without_raw_workflow_event() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="codex-cli",
        ),
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-result-001",
            "event_type": "result_submitted",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "result": {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "emitted_events": [],
                "artifacts": [],
                "outcome_metrics": {},
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        },
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-001",
            "event_type": "node_outcome_decided",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "session_id": "session-001",
            "source_outcome_id": "outcome-001",
            "outcome_status": "completed",
            "actor": "harness",
            "disposition": "accepted",
            "accepted_event_types": ["patch_ready"],
        },
        workflow,
    )

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"
    assert gatekeeper.ready == ["review"]


def test_replay_rejects_raw_workflow_event_when_outcome_decision_rejects_it() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="codex-cli",
        ),
        workflow,
    )
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )
    ledger = import_result_proposal(
        workflow,
        ledger,
        assignment,
        result,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-001",
            "event_type": "node_outcome_decided",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "session_id": "session-001",
            "source_outcome_id": "outcome-001",
            "outcome_status": "completed",
            "actor": "harness",
            "disposition": "rejected",
            "accepted_event_types": [],
        },
        workflow,
    )

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    assert replay.nodes["implement"].state == "blocked"
    assert replay.nodes["review"].state == "blocked"
    assert gatekeeper.ready == []
    assert replay.nodes["review"].blocked_reasons[0].missing_ref == "patch_ready"


def test_v2_replay_stages_result_until_outcome_decision() -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=2)
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-001",
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="codex-cli",
        ),
        workflow,
    )
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )
    ledger = import_result_proposal(workflow, ledger, assignment, result)

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    assert [event["event_type"] for event in ledger.event_log] == [
        "assignment_created",
        "result_submitted",
    ]
    assert replay.nodes["implement"].state == "blocked"
    assert replay.nodes["implement"].assignment_attempts[0].state == (
        "awaiting_acceptance"
    )
    assert replay.nodes["implement"].blocked_reasons[0].code == (
        "awaiting_acceptance"
    )
    assert gatekeeper.ready == []


def test_v2_replay_materializes_only_outcome_accepted_events() -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=2)
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-001",
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="codex-cli",
        ),
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-result-001",
            "event_type": "result_submitted",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": assignment.assignment_id,
            "node_id": assignment.node_id,
            "role": assignment.role,
            "agent_id": "codex-cli",
            "result": {
                "result_id": "result-001",
                "assignment_id": assignment.assignment_id,
                "agent_id": "codex-cli",
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "artifacts": [],
                "outcome_metrics": {},
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        },
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-001",
            "event_type": "node_outcome_decided",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": assignment.assignment_id,
            "node_id": assignment.node_id,
            "role": assignment.role,
            "agent_id": "codex-cli",
            "session_id": "session-001",
            "source_result_event_id": "event-result-001",
            "source_outcome_id": "outcome-001",
            "outcome_status": "completed",
            "actor": "harness",
            "disposition": "accepted",
            "accepted_event_types": ["patch_ready"],
            "acceptance_policy_version": "acceptance-v1",
            "verification_status": "passed",
            "validation_rule": "verified_result_v1",
        },
        workflow,
    )

    replay = replay_workflow(workflow, ledger)

    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["implement"].assignment_attempts[0].state == "completed"
    assert replay.nodes["review"].state == "runnable"


def test_v1_to_v2_migration_quarantines_undecided_result_events() -> None:
    workflow = _workflow()
    source = _empty_ledger()
    assignment = export_assignment(
        workflow,
        source,
        "implement",
        assignment_id="assign-migrate-001",
    )
    result = load_result_proposal(
        {
            "result_id": "result-migrate-001",
            "assignment_id": assignment.assignment_id,
            "agent_id": "legacy-worker",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )
    source = import_result_proposal(workflow, source, assignment, result)

    migration = migrate_ledger_to_v2(workflow, source)
    replay = replay_workflow(workflow, migration.ledger)

    assert source.ledger_version == 1
    assert replay_workflow(workflow, source).nodes["implement"].state == "completed"
    assert migration.ledger.ledger_version == 2
    assert migration.report["quarantined_results"] == [
        {
            "assignment_id": "assign-migrate-001",
            "result_event_id": "event-result-migrate-001",
            "claimed_event_types": ["patch_ready"],
            "reason": "requires_acceptance_review",
        }
    ]
    assert replay.nodes["implement"].state == "blocked"
    assert replay.nodes["implement"].blocked_reasons[0].code == "awaiting_acceptance"


def test_cli_migrate_v2_preserves_source_and_writes_report(tmp_path, capsys) -> None:
    workflow_path = Path(
        "examples/missions/demo/workflows/coder_reviewer_committer.yaml"
    )
    source_path = tmp_path / "ledger-v1.yaml"
    output_path = tmp_path / "ledger-v2.yaml"
    source_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "ledger",
            "migrate-v2",
            str(workflow_path),
            str(source_path),
            str(output_path),
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert load_ledger(source_path).ledger_version == 1
    assert load_ledger(output_path).ledger_version == 2
    assert Path(payload["report"]).exists()
    assert payload["from_version"] == 1
    assert payload["to_version"] == 2


def test_cli_rejects_v1_result_write_until_migrated(tmp_path, capsys) -> None:
    workflow_path = Path(
        "examples/missions/demo/workflows/coder_reviewer_committer.yaml"
    )
    paths = prepare_demo_workspace(tmp_path / "legacy-write")
    assignment_path = tmp_path / "assignment.yaml"
    assignment = export_assignment(
        load_workflow(workflow_path),
        load_ledger(paths["ledger"]),
        "implement",
        assignment_id="assign-legacy-write",
    )
    assignment_path.write_text(
        yaml.safe_dump(assignment.to_dict(), sort_keys=False),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "result",
            "import",
            str(workflow_path),
            str(paths["ledger"]),
            str(assignment_path),
            str(paths["results_dir"] / "implement_result.yaml"),
        ]
    )

    assert exit_code == 1
    assert "requires ledger_version 2" in capsys.readouterr().err


def _v2_staged_acceptance_fixture():
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=2)
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-acceptance-001",
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-acceptance-001",
            agent_id="codex-cli",
        ),
        workflow,
    )
    result = load_result_proposal(
        {
            "result_id": "result-acceptance-001",
            "assignment_id": assignment.assignment_id,
            "agent_id": "codex-cli",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )
    outcome = load_node_outcome(
        {
            "outcome_id": "outcome-acceptance-001",
            "assignment_id": assignment.assignment_id,
            "session_id": "session-acceptance-001",
            "workflow_id": workflow.workflow_id,
            "node_id": assignment.node_id,
            "role": assignment.role,
            "agent_id": "codex-cli",
            "status": "completed",
            "pre_state_ref": "workspace:before",
            "post_state_ref": "workspace:after",
            "observed_delta": {"changed_files_count": 1},
            "verification": {"status": "passed"},
            "native_log_refs": [],
            "diff_refs": [],
            "outcome_metrics": {},
            "extraction": {},
        }
    )
    staged = stage_result(workflow, ledger, assignment, result, outcome)
    return workflow, assignment, result, outcome, staged


def _apply_acceptance_review(
    workflow,
    ledger,
    *,
    verdict="approved",
    next_action="continue",
):
    decision = load_review_decision(
        {
            "decision_type": "review_decision",
            "decision_id": "review-acceptance-001",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "reviewed_event": "event-result-acceptance-001",
            "actor": "orchestrator",
            "verdict": verdict,
            "reason": "Acceptance policy review evidence.",
            "evidence_refs": [],
            "accepted_findings": [],
            "rejected_findings": [],
            "next_action": next_action,
        }
    )
    return apply_review_decision(
        ledger,
        decision,
        workflow=workflow,
        event_id="event-review-acceptance-001",
        decision_ref="reviews/review-acceptance-001.yaml",
    )


def test_acceptance_service_requires_review_and_verification() -> None:
    workflow, assignment, result, outcome, staged = _v2_staged_acceptance_fixture()

    with pytest.raises(ProtocolError, match="requires a review decision"):
        decide_staged_result(
            workflow,
            staged.ledger,
            assignment,
            result,
            outcome,
            policy=DEFAULT_ACCEPTANCE_POLICY,
            verification_status="passed",
        )

    reviewed = _apply_acceptance_review(workflow, staged.ledger)
    accepted = decide_staged_result(
        workflow,
        reviewed,
        assignment,
        result,
        outcome,
        policy=DEFAULT_ACCEPTANCE_POLICY,
        verification_status="passed",
        review_event_id="event-review-acceptance-001",
    )

    assert accepted.disposition == "accepted"
    assert accepted.accepted_event_types == ["patch_ready"]
    assert replay_workflow(workflow, accepted.ledger).nodes["review"].state == (
        "runnable"
    )


@pytest.mark.parametrize(
    ("verdict", "verification_status"),
    [("rejected", "passed"), ("changes_requested", "passed"), ("approved", "failed")],
)
def test_acceptance_service_rejects_failed_policy_evidence(
    verdict,
    verification_status,
) -> None:
    workflow, assignment, result, outcome, staged = _v2_staged_acceptance_fixture()
    reviewed = _apply_acceptance_review(
        workflow,
        staged.ledger,
        verdict=verdict,
        next_action="retry" if verdict == "changes_requested" else "stop",
    )

    decided = decide_staged_result(
        workflow,
        reviewed,
        assignment,
        result,
        outcome,
        policy=DEFAULT_ACCEPTANCE_POLICY,
        verification_status=verification_status,
        review_event_id="event-review-acceptance-001",
    )

    assert decided.disposition == "rejected"
    assert decided.accepted_event_types == []
    assert replay_workflow(workflow, decided.ledger).nodes["implement"].state == (
        "blocked"
    )


def test_acceptance_service_enforces_partial_and_single_terminal_decision() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {
                    "id": "implement",
                    "role": "coder",
                    "emits": ["patch_ready", "verification_ready"],
                }
            ],
            "events": {
                "patch_ready": {"producer_roles": ["coder"]},
                "verification_ready": {"producer_roles": ["coder"]},
            },
            "terminal_events": ["patch_ready"],
        }
    )
    ledger = replace(_empty_ledger(), ledger_version=2)
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-partial-001",
    )
    result = load_result_proposal(
        {
            "result_id": "result-partial-001",
            "assignment_id": assignment.assignment_id,
            "agent_id": "codex-cli",
            "status": "completed",
            "emitted_events": ["patch_ready", "verification_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )
    outcome = load_node_outcome(
        {
            "outcome_id": "outcome-partial-001",
            "assignment_id": assignment.assignment_id,
            "session_id": "session-partial-001",
            "workflow_id": workflow.workflow_id,
            "node_id": assignment.node_id,
            "role": assignment.role,
            "agent_id": "codex-cli",
            "status": "completed",
            "observed_delta": {},
            "verification": {"status": "passed"},
            "native_log_refs": [],
            "diff_refs": [],
            "outcome_metrics": {},
            "extraction": {},
        }
    )
    staged = stage_result(workflow, ledger, assignment, result, outcome)
    policy = AcceptancePolicy(
        policy_version="acceptance-v1",
        review_required=False,
        allowed_review_actors=["orchestrator", "human"],
        required_verification_statuses=["passed"],
        allow_partial_acceptance=True,
    )
    decided = decide_staged_result(
        workflow,
        staged.ledger,
        assignment,
        result,
        outcome,
        policy=policy,
        verification_status="passed",
        accepted_event_types=["patch_ready"],
    )

    assert decided.disposition == "partially_accepted"
    with pytest.raises(ProtocolError, match="already has a terminal decision"):
        decide_staged_result(
            workflow,
            decided.ledger,
            assignment,
            result,
            outcome,
            policy=policy,
            verification_status="passed",
            accepted_event_types=["patch_ready"],
            event_id="event-outcome-partial-duplicate",
        )


def test_cli_mission_golden_path_prepares_manifest_and_executes_end_to_end(
    tmp_path, capsys
) -> None:
    workspace = tmp_path / "golden-path"
    exit_code = main(["mission", "golden-path", str(workspace)])
    manifest = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert Path(manifest["mission_path"]).exists()
    assert Path(manifest["workflow_path"]).exists()
    assert Path(manifest["ledger_path"]).exists()
    assert Path(manifest["results"]["implement"]).exists()
    assert Path(manifest["results"]["review"]).exists()
    assert Path(manifest["results"]["commit"]).exists()
    assert Path(manifest["artifacts_root"]).exists()

    implement_result = yaml.safe_load(
        Path(manifest["results"]["implement"]).read_text(encoding="utf-8")
    )
    assert implement_result["artifacts"][0]["path"] == "artifacts/implement_patch.diff"
    assert len(implement_result["artifacts"][0]["sha256"]) == 64

    for step in manifest["steps"]:
        step_exit = main(step["argv"])
        captured = capsys.readouterr()
        assert step_exit == 0, step["id"]
        expects = step["expects"]

        if "capture_to" in step:
            capture_path = Path(step["capture_to"])
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture_path.write_text(captured.out, encoding="utf-8")
            payload = yaml.safe_load(captured.out)
            assert payload["assignment_id"] == expects["assignment_id"]
            assert payload["node_id"] == expects["node_id"]
            assert payload["expected_events"] == expects["expected_events"]
            continue

        if "ready" in expects:
            ready = [line.strip() for line in captured.out.splitlines() if line.strip()]
            assert ready == expects["ready"]
            continue

        if "terminal_complete" in expects:
            replay_payload = yaml.safe_load(captured.out)
            assert replay_payload["terminal_complete"] is expects["terminal_complete"]
            node_states = {
                node_id: node_payload["state"]
                for node_id, node_payload in replay_payload["nodes"].items()
            }
            assert node_states == expects["node_states"]
            if "blocked_refs" in expects:
                blocked_refs = {
                    node_id: sorted(
                        {
                            reason["missing_ref"]
                            for reason in node_payload["blocked_reasons"]
                            if "missing_ref" in reason
                        }
                    )
                    for node_id, node_payload in replay_payload["nodes"].items()
                    if node_payload["blocked_reasons"]
                }
                assert blocked_refs == expects["blocked_refs"]
            continue

        assert expects["stdout_contains"] in captured.out

    updated = load_ledger(Path(manifest["ledger_path"]))
    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted",
        "node_outcome_decided",
        "result_submitted",
        "node_outcome_decided",
        "result_submitted",
        "node_outcome_decided",
    ]
    assert [
        event["accepted_event_types"]
        for event in updated.event_log
        if event["event_type"] == "node_outcome_decided"
    ] == [["patch_ready"], ["review_approved"], ["commit_created"]]


def test_run_live_demo_executes_three_node_session_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        prompt = kwargs["input"]
        if "Node: implement" in prompt:
            event_name = "patch_ready"
        elif "Node: review" in prompt:
            event_name = "review_approved"
        elif "Node: commit" in prompt:
            event_name = "commit_created"
        else:
            raise AssertionError(prompt)
        stdout = (
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"'
            f'status: completed\\nemitted_events:\\n  - {event_name}\\nverification:\\n  status: passed'
            '"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    manifest = run_live_demo(
        tmp_path / "live-demo",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        timeout_seconds=10.0,
        command_runner=fake_runner,
    )

    assert manifest["terminal_complete"] is True
    assert manifest["failure"] is None
    assert manifest["ready"] == []
    assert manifest["node_states"] == {
        "implement": "completed",
        "review": "completed",
        "commit": "completed",
    }
    assert [step["node_id"] for step in manifest["steps"]] == [
        "implement",
        "review",
        "commit",
    ]
    assert manifest["steps"][0]["ready_after"] == ["review"]
    assert manifest["steps"][1]["ready_after"] == ["commit"]
    assert manifest["steps"][2]["ready_after"] == []
    assert Path(manifest["routing_decision_path"]).exists()
    assert Path(manifest["advisor_gate_decision_path"]).exists()
    assert Path(manifest["advisor_gate_outcome_path"]).exists()
    assert Path(manifest["metrics_summary_path"]).exists()
    assert Path(manifest["manifest_path"]).exists()
    assert Path(manifest["steps"][0]["context_capsule_path"]).exists()
    assert Path(manifest["steps"][0]["node_outcome_path"]).exists()
    assert Path(manifest["steps"][0]["review_decision_path"]).exists()

    metrics_summary = yaml.safe_load(Path(manifest["metrics_summary_path"]).read_text(encoding="utf-8"))
    assert metrics_summary["context_summary"]["fit_counts"]["well_provisioned"] == 3
    assert metrics_summary["policy_recommendations"] == []

    routing_decision = yaml.safe_load(
        Path(manifest["routing_decision_path"]).read_text(encoding="utf-8")
    )
    assert routing_decision["decision_type"] == "routing_decision"
    assert routing_decision["selected_mode"] == "small_dag"

    ledger = load_ledger(Path(manifest["ledger_path"]))
    assert [
        event["event_type"]
        for event in ledger.event_log
        if event["event_type"] == "review_decision_recorded"
    ] == [
        "review_decision_recorded",
        "review_decision_recorded",
        "review_decision_recorded",
    ]
    assert [finding["finding_id"] for finding in ledger.public_findings] == [
        "finding-implement-live",
        "finding-review-live",
        "finding-commit-live",
    ]


def test_run_live_demo_follows_replay_ready_nodes_for_separate_verification(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cli_main = importlib.import_module("bureauless.cli.main")
    original_prepare = cli_main.prepare_demo_workspace

    def prepare_with_verify(*args, **kwargs):
        paths = original_prepare(*args, **kwargs)
        workflow_path = paths["workflow"]
        payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        payload["nodes"].insert(
            1,
            {
                "id": "verify",
                "role": "coder",
                "waits_for": {"all_of": ["implement.patch_ready"]},
                "emits": ["patch_ready"],
            },
        )
        for node in payload["nodes"]:
            if node["id"] == "review":
                node["waits_for"] = {"all_of": ["verify.patch_ready"]}
            if node["id"] == "commit":
                node["waits_for"] = {
                    "all_of": ["verify.patch_ready", "review_approved"]
                }
        payload["gates"][0]["requires"] = {
            "all_of": ["verify.patch_ready", "review_approved"]
        }
        workflow_path.write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )
        return paths

    monkeypatch.setattr(cli_main, "prepare_demo_workspace", prepare_with_verify)

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        prompt = kwargs["input"]
        if "Node: implement" in prompt:
            event_name = "patch_ready"
        elif "Node: verify" in prompt:
            event_name = "patch_ready"
        elif "Node: review" in prompt:
            event_name = "review_approved"
        elif "Node: commit" in prompt:
            event_name = "commit_created"
        else:
            raise AssertionError(prompt)
        stdout = (
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"'
            f'status: completed\\nemitted_events:\\n  - {event_name}\\nverification:\\n  status: passed'
            '"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    manifest = run_live_demo(
        tmp_path / "live-demo-with-verify",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        timeout_seconds=10.0,
        command_runner=fake_runner,
    )

    assert manifest["terminal_complete"] is True
    assert manifest["failure"] is None
    assert [step["node_id"] for step in manifest["steps"]] == [
        "implement",
        "verify",
        "review",
        "commit",
    ]
    assert manifest["steps"][0]["ready_after"] == ["verify"]


def test_run_live_demo_rejects_unstructured_implement_progress(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        prompt = kwargs["input"]
        if "Node: implement" in prompt:
            body = (
                "status: completed\n"
                "emitted_events:\n"
                "  - patch_ready\n"
                "verification:\n"
                "  status: coder_smoke_passed_final_verification_pending_independent_assignment\n"
                "  verifier_entrypoint: scripts/verify_demo_cli.sh"
            )
        elif "Node: review" in prompt:
            body = (
                "status: completed\n"
                "emitted_events:\n"
                "  - review_approved\n"
                "verification:\n"
                "  status: passed"
            )
        elif "Node: commit" in prompt:
            body = (
                "status: completed\n"
                "emitted_events:\n"
                "  - commit_created\n"
                "verification:\n"
                "  status: passed"
            )
        else:
            raise AssertionError(prompt)
        escaped_body = body.replace("\n", "\\n")
        stdout = (
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"'
            f"{escaped_body}"
            '"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    manifest = run_live_demo(
        tmp_path / "live-demo-boundary",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        timeout_seconds=10.0,
        command_runner=fake_runner,
    )

    assert manifest["terminal_complete"] is False
    assert manifest["failure"] is None
    assert manifest["steps"][0]["node_id"] == "implement"
    assert manifest["steps"][0]["ready_after"] == []

    ledger = load_ledger(Path(manifest["ledger_path"]))
    implement_decision = next(
        event
        for event in ledger.event_log
        if event.get("event_id") == "event-outcome-session-implement-live-decision"
    )
    assert implement_decision["disposition"] == "rejected"
    assert implement_decision["accepted_event_types"] == []
    assert implement_decision["verification_status"] == (
        "coder_smoke_passed_final_verification_pending_independent_assignment"
    )
    assert implement_decision["acceptance_policy_version"] == "acceptance-v1"


def test_execution_spine_acceptance_cli_proves_cross_capability_path(
    tmp_path,
    capsys,
) -> None:
    workspace = tmp_path / "execution-spine-acceptance"
    exit_code = main(
        ["mission", "execution-spine-acceptance", str(workspace)]
    )
    report = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert report["status"] == "passed"
    assert all(check["passed"] is True for check in report["checks"].values())
    assert Path(report["report_path"]).is_file()
    assert report["deferred_findings"] == {
        "REX-001": "Owned by Runtime M4 mutation intake and temporal replay scope."
    }

    ledger = load_ledger(Path(report["artifacts"]["ledger_path"]))
    lifecycle = [
        event["event_type"]
        for event in ledger.event_log
        if event["event_type"]
        in {
            "context_requested",
            "context_resolved",
            "context_resumed",
            "result_submitted",
            "review_decision_recorded",
            "node_outcome_decided",
        }
    ]
    assert lifecycle == [
        "context_requested",
        "context_resolved",
        "context_resumed",
        "result_submitted",
        "review_decision_recorded",
        "node_outcome_decided",
    ]
    bundle = load_run_bundle(Path(report["artifacts"]["run_bundle_path"]))
    assert bundle["flow_id"] == "maintained-session-dispatch"
    assert bundle["steps"][0]["context_request_path"] is not None
    assert bundle["steps"][0]["context_resolution_path"] is not None
    assert bundle["steps"][0]["result_path"] is None
    assert report["checks"]["cancellation_safety"]["forced"] is True
    assert Path(report["checks"]["advisor_policy"]["invoked_outcome_path"]).is_file()


def test_run_live_demo_returns_partial_manifest_when_session_times_out(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    manifest = run_live_demo(
        tmp_path / "live-demo-timeout",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        timeout_seconds=1.0,
        command_runner=fake_runner,
    )

    assert manifest["terminal_complete"] is False
    assert manifest["failure"] == {
        "node_id": "implement",
        "session_id": "session-implement-live",
        "status": "timed_out",
        "reason": "timed_out",
        "session_path": str(
            tmp_path
            / "live-demo-timeout"
            / "generated"
            / "sessions"
            / "implement_session.yaml"
        ),
    }
    assert manifest["steps"] == [
        {
            "node_id": "implement",
            "assignment_path": str(
                tmp_path
                / "live-demo-timeout"
                / "generated"
                / "assignments"
                / "implement_assignment.yaml"
            ),
                "context_capsule_path": str(
                tmp_path
                / "live-demo-timeout"
                / "generated"
                / "capsules"
                    / "implement_context_capsule.yaml"
                ),
                "context_request_path": None,
                "context_resolution_path": None,
                "session_path": str(
                tmp_path
                / "live-demo-timeout"
                / "generated"
                / "sessions"
                    / "implement_session.yaml"
                ),
                "result_path": None,
                "node_outcome_path": None,
                "review_decision_path": None,
                "turn_report_path": str(
                    tmp_path
                    / "live-demo-timeout"
                    / "generated"
                    / "telemetry"
                    / "implement_turn_report.yaml"
                ),
                "dispatch_packet_path": str(
                    tmp_path
                    / "live-demo-timeout"
                    / "generated"
                    / "decisions"
                    / "implement_dispatch_packet.yaml"
                ),
                "record_status": "timed_out",
            "failure_reason": "timed_out",
            "ready_after": [],
            "node_state_after": "blocked",
        }
    ]


def test_run_live_demo_blocks_proposed_workflow_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cli_main = importlib.import_module("bureauless.cli.main")
    original_prepare = cli_main.prepare_demo_workspace

    def prepare_proposed(*args, **kwargs):
        paths = original_prepare(*args, **kwargs)
        workflow_path = paths["workflow"]
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        workflow["status"] = "proposed"
        workflow_path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
        return paths

    monkeypatch.setattr(cli_main, "prepare_demo_workspace", prepare_proposed)
    runner_called = False

    def runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("proposed workflow reached the external runner")

    manifest = run_live_demo(
        tmp_path / "live-demo-proposed",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        command_runner=runner,
    )

    assert runner_called is False
    assert manifest["steps"] == []
    assert manifest["failure"] == {
        "node_id": None,
        "status": "blocked",
        "reason": "workflow_not_accepted",
        "workflow_status": "proposed",
    }


def test_run_live_demo_bootstraps_accepted_worker_workflow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    workflow = {
        "workflow_id": "orchestrated-workflow",
        "mission_id": "demo",
        "status": "proposed",
        "proposed_by": "orchestrator",
        "mode": "single_agent",
        "reason": "One bounded implementation assignment is sufficient.",
        "roles": {"coder": {"can_emit": ["patch_ready"], "can_consume": []}},
        "events": {"patch_ready": {"producer_roles": ["coder"]}},
        "nodes": [{"id": "implement", "role": "coder", "emits": ["patch_ready"]}],
        "gates": [],
        "terminal_events": ["patch_ready"],
        "broadcast_policy": {"default": "filtered_delta"},
        "budget_policy": {},
    }

    def runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        prompt = kwargs["input"]
        if "Node: orchestrate" in prompt:
            payload = {
                "status": "completed",
                "emitted_events": ["control_plane_complete"],
                "verification": {"status": "passed"},
                "control_intents": [
                    {
                        "intent_type": "initial_control_plane",
                        "proposal_id": "proposal-live-bootstrap",
                        "workflow": workflow,
                        "routing_decision": {
                            "decision_type": "routing_decision",
                            "mission_id": "demo",
                            "workflow_id": "orchestrated-workflow",
                            "selected_mode": "single_agent",
                            "selection_policy_version": "0.1",
                            "triggered_rules": ["bounded_implementation"],
                            "rejected_modes": [],
                            "estimated_coordination_ratio": 0.0,
                            "budget_confidence": "high",
                            "reason": "One bounded implementation assignment is sufficient.",
                            "advisor_gate_decision": {
                                "invoked": False,
                                "policy_version": "0.1",
                                "reason": ["first_run_heuristic"],
                                "decision_basis": "first_run_heuristic",
                            },
                        },
                        "worker_bindings": [
                            {
                                "node_id": "implement",
                                "role": "coder",
                                "agent_id": "codex-cli",
                                "model": "gpt-5-mini",
                            }
                        ],
                    },
                    {
                        "intent_type": "accept_initial_control_plane",
                        "proposal_id": "proposal-live-bootstrap",
                    },
                ],
            }
        elif "Node: implement" in prompt:
            payload = {
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "verification": {"status": "passed"},
            }
        else:
            raise AssertionError(prompt)
        stdout = "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": yaml.safe_dump(payload, sort_keys=False)}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    manifest = run_live_demo(
        tmp_path / "live-demo-bootstrap",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        command_runner=runner,
        bootstrap_context={
            "task": "Plan a bounded implementation workflow.",
            "provider_allowed_worker_models": ["gpt-5-mini"],
        },
    )

    assert manifest["terminal_complete"] is True
    ledger = load_ledger(Path(manifest["ledger_path"]))
    assert [event["event_type"] for event in ledger.event_log[:3]] == [
        "assignment_created",
        "initial_control_plane_proposed",
        "initial_control_plane_accepted",
    ]
    assert load_session_record(
        yaml.safe_load(
            (tmp_path / "live-demo-bootstrap" / "generated" / "sessions" / "implement_session.yaml").read_text(encoding="utf-8")
        )
    ).result_proposal["effective_model"] == "gpt-5-mini"


def test_run_live_demo_replans_rejected_bootstrap_once_then_runs_semantic_dag(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls: list[str] = []
    workflow = {
        "workflow_id": "orchestrated-semantic-workflow",
        "mission_id": "demo",
        "status": "proposed",
        "proposed_by": "orchestrator",
        "mode": "small_dag",
        "reason": "Separate implementation, review, verification, and commit evidence.",
        "roles": {
            "coder": {"can_emit": ["patch_ready"], "can_consume": []},
            "reviewer": {
                "can_emit": ["review_approved"],
                "can_consume": ["patch_ready"],
            },
            "verifier": {
                "can_emit": ["verification_passed"],
                "can_consume": ["patch_ready"],
            },
            "committer": {
                "can_emit": ["commit_complete"],
                "can_consume": [
                    "patch_ready",
                    "review_approved",
                    "verification_passed",
                ],
            },
        },
        "events": {
            "patch_ready": {"producer_roles": ["coder"]},
            "review_approved": {"producer_roles": ["reviewer"]},
            "verification_passed": {"producer_roles": ["verifier"]},
            "commit_complete": {"producer_roles": ["committer"]},
        },
        "nodes": [
            {"id": "write_cli", "role": "coder", "emits": ["patch_ready"]},
            {
                "id": "inspect_patch",
                "role": "reviewer",
                "waits_for": ["write_cli.patch_ready"],
                "emits": ["review_approved"],
            },
            {
                "id": "accept_cli",
                "role": "verifier",
                "waits_for": ["write_cli.patch_ready"],
                "emits": ["verification_passed"],
            },
            {
                "id": "publish_release",
                "role": "committer",
                "waits_for": [
                    "write_cli.patch_ready",
                    "inspect_patch.review_approved",
                    "accept_cli.verification_passed",
                ],
                "emits": ["commit_complete"],
            },
        ],
        "gates": [
            {
                "id": "release-requires-verification",
                "node_id": "publish_release",
                "requires": ["accept_cli.verification_passed"],
            }
        ],
        "terminal_events": ["publish_release.commit_complete"],
        "broadcast_policy": {"default": "filtered_delta"},
        "budget_policy": {},
    }

    def bootstrap_payload(selected_mode: str) -> dict[str, Any]:
        return {
            "status": "completed",
            "emitted_events": ["control_plane_complete"],
            "verification": {"status": "passed"},
            "control_intents": [
                {
                    "intent_type": "initial_control_plane",
                    "proposal_id": "proposal-live-replan",
                    "workflow": workflow,
                    "routing_decision": {
                        "decision_type": "routing_decision",
                        "mission_id": "demo",
                        "workflow_id": workflow["workflow_id"],
                        "selected_mode": selected_mode,
                        "selection_policy_version": "0.1",
                        "triggered_rules": ["independent_verification_required"],
                        "rejected_modes": (
                            [
                                {
                                    "mode": "single_agent",
                                    "rejected_because": "Independent verification requires separate evidence boundaries.",
                                }
                            ]
                            if selected_mode == "small_dag"
                            else []
                        ),
                        "estimated_coordination_ratio": 0.1,
                        "budget_confidence": "high",
                        "reason": "Separate evidence-bearing nodes are required.",
                        "advisor_gate_decision": {
                            "invoked": False,
                            "policy_version": "0.1",
                            "reason": ["first_run_heuristic"],
                            "decision_basis": "first_run_heuristic",
                        },
                    },
                    "worker_bindings": [
                        {
                            "node_id": node["id"],
                            "role": node["role"],
                            "agent_id": "codex-cli",
                            "model": "gpt-5-mini",
                        }
                        for node in workflow["nodes"]
                    ],
                },
                {
                    "intent_type": "accept_initial_control_plane",
                    "proposal_id": "proposal-live-replan",
                },
            ],
        }

    def runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        prompt = kwargs["input"]
        if "Node: orchestrate" in prompt:
            calls.append("orchestrate")
            if len(calls) == 1:
                payload = bootstrap_payload("single_agent")
            else:
                assert "control_plane_replan" in prompt
                assert "selected_mode does not match workflow mode" in prompt
                assert "previous_proposal" in prompt
                payload = bootstrap_payload("small_dag")
        elif "Node: write_cli" in prompt:
            calls.append("write_cli")
            assert "pending_separate_assignment" in prompt
            payload = {
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "verification": {
                    "status": "implementation_smoke_passed",
                    "final_independent_verification": "pending_separate_assignment",
                },
            }
        elif "Node: inspect_patch" in prompt:
            calls.append("inspect_patch")
            payload = {
                "status": "completed",
                "emitted_events": ["review_approved"],
                "verification": {"status": "passed"},
            }
        elif "Node: accept_cli" in prompt:
            calls.append("accept_cli")
            assert "verification.evidence" in prompt
            payload = {
                "status": "completed",
                "emitted_events": ["verification_passed"],
                "verification": {
                    "status": "passed",
                    "evidence": {"command": "verify-demo", "observed": "passed"},
                },
            }
        elif "Node: publish_release" in prompt:
            calls.append("publish_release")
            assert "danger-full-access" in command
            payload = {
                "status": "completed",
                "emitted_events": ["commit_complete"],
                "verification": {"status": "passed"},
            }
        else:
            raise AssertionError(prompt)
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": yaml.safe_dump(payload, sort_keys=False),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    manifest = run_live_demo(
        tmp_path / "live-demo-bootstrap-replan",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        command_runner=runner,
        bootstrap_context={
            "task": "Plan and run a verified implementation workflow.",
            "provider_allowed_worker_models": ["gpt-5-mini"],
            "control_plane_requirements": {
                "independent_verification": True,
                "terminal_commit": True,
            },
        },
    )

    assert calls == [
        "orchestrate",
        "orchestrate",
        "write_cli",
        "inspect_patch",
        "accept_cli",
        "publish_release",
    ]
    assert manifest["terminal_complete"] is True
    assert manifest["failure"] is None
    assert len(manifest["steps"][0]["attempts"]) == 2
    assert "selected_mode does not match workflow mode" in (
        manifest["steps"][0]["attempts"][0]["protocol_error"]
    )
    assert manifest["steps"][0]["attempts"][1]["accepted"] is True
    assert any(
        item["field"] == "steps[0].attempts[0].session_path"
        for item in manifest["artifact_index"]
    )
    assert [step["node_id"] for step in manifest["steps"][1:]] == [
        "write_cli",
        "inspect_patch",
        "accept_cli",
        "publish_release",
    ]
    assert set(manifest["node_states"].values()) == {"completed"}


def test_run_live_demo_records_rejected_control_plane_without_worker_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    orchestrator_calls = 0

    def runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        nonlocal orchestrator_calls
        orchestrator_calls += 1
        prompt = kwargs["input"]
        assert "Node: orchestrate" in prompt
        payload = {
            "status": "completed",
            "emitted_events": ["control_plane_complete"],
            "verification": {"status": "passed"},
            "control_intents": [
                {
                    "intent_type": "initial_control_plane",
                    "proposal_id": "invalid-bootstrap",
                    "proposed_workflow": {"nodes": []},
                    "worker_bindings": [],
                },
                {
                    "intent_type": "accept_initial_control_plane",
                    "proposal_id": "invalid-bootstrap",
                },
            ],
        }
        stdout = "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": yaml.safe_dump(payload, sort_keys=False)}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    manifest = run_live_demo(
        tmp_path / "live-demo-invalid-bootstrap",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        command_runner=runner,
        bootstrap_context={"task": "Plan a bounded implementation workflow."},
    )

    assert manifest["terminal_complete"] is False
    assert manifest["failure"]["reason"] == "control_plane_bootstrap_rejected"
    assert "Initial control-plane workflow must be an object" in manifest["failure"]["message"]
    assert [step["node_id"] for step in manifest["steps"]] == ["orchestrate"]
    assert manifest["ready"] == []
    assert set(manifest["node_states"].values()) == {"blocked"}
    assert Path(manifest["steps"][0]["session_path"]).is_file()
    assert orchestrator_calls == 2
    assert len(manifest["steps"][0]["attempts"]) == 2


def test_prepare_demo_workspace_initializes_clean_git_repo(tmp_path) -> None:
    workspace = prepare_demo_workspace(tmp_path / "demo-workspace")
    git_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=tmp_path / "demo-workspace",
        check=False,
        capture_output=True,
        text=True,
    )
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=tmp_path / "demo-workspace",
        check=False,
        capture_output=True,
        text=True,
    )

    assert workspace["ledger"].exists()
    assert git_root.returncode == 0
    assert Path(git_root.stdout.strip()) == (tmp_path / "demo-workspace").resolve()
    assert status.returncode == 0
    assert status.stdout.strip() == ""


def test_lists_agent_specs() -> None:
    specs = list_agent_specs()
    agent_ids = [spec.agent_id for spec in specs]

    assert agent_ids == ["claude-code", "codex-cli", "gemini", "opencode", "pi"]
    codex = next(spec for spec in specs if spec.agent_id == "codex-cli")
    assert codex.non_interactive_markers == ["exec"]
    assert codex.model_override_markers == ["--model"]
    assert codex.provider_override_markers == ["--config"]
    assert codex.kind == "local_agent_cli"


def test_agent_doctor_reports_missing_binary() -> None:
    result = doctor_agent("codex-cli", which=lambda _binary: None)

    assert result.status == "unavailable"
    assert result.control_level == "none"
    assert result.binary_path is None
    assert result.warnings == ["Binary not found on PATH: codex"]


def test_agent_doctor_detects_high_control_surface() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    result = doctor_agent(
        "codex-cli",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert result.status == "usable"
    assert result.control_level == "high"
    assert result.version == "codex 1.0"
    assert all(check.status == "passed" for check in result.checks)


def test_agent_doctor_degrades_when_required_marker_is_missing() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="opencode 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="run --model --format --pure",
            stderr="",
        )

    result = doctor_agent(
        "opencode",
        which=lambda _binary: "/usr/bin/opencode",
        run_command=fake_run,
    )

    assert result.status == "degraded"
    assert result.control_level == "low"
    failed = {check.name for check in result.checks if check.status == "failed"}
    assert "working_directory" in failed


def test_agent_doctor_emits_warnings_on_failed_help_or_version() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=2, stdout="", stderr="bad version")
        return CommandOutput(returncode=3, stdout="", stderr="bad help")

    result = doctor_agent(
        "codex-cli",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert result.status == "degraded"
    assert "Help command exited with 3" in result.warnings
    assert "Version command exited with 2" in result.warnings


def test_agent_compatibility_reports_dispatchable_for_full_control_surface() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    compatibility = assess_agent_compatibility(
        "codex-cli",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert compatibility.compatibility_state == "dispatchable"
    assert compatibility.capabilities["non_interactive_execution"] == "strong"
    assert compatibility.capabilities["working_directory_control"] == "strong"
    assert compatibility.capabilities["timeout_control"] == "strong"
    assert compatibility.capabilities["cancellation_control"] == "strong"


def test_agent_compatibility_reports_limited_for_partial_config_isolation() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="claude 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="--print --model --settings --bare --worktree --add-dir --output-format --no-session-persistence",
            stderr="",
        )

    compatibility = assess_agent_compatibility(
        "claude-code",
        which=lambda _binary: "/usr/bin/claude",
        run_command=fake_run,
    )

    assert compatibility.compatibility_state == "limited"
    assert compatibility.capabilities["config_isolation"] == "weak"
    assert compatibility.capabilities["cancellation_control"] == "strong"
    assert "config_isolation" in compatibility.reasons


def test_agent_compatibility_uses_registered_provider_injection_for_gemini() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="gemini 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout=(
                "--prompt --model --skip-trust --extensions --output-format stream-json "
                "--resume --session-file --session-id"
            ),
            stderr="",
        )

    compatibility = assess_agent_compatibility(
        "gemini",
        which=lambda _binary: "/usr/bin/gemini",
        run_command=fake_run,
    )

    assert compatibility.compatibility_state == "dispatchable"
    assert compatibility.capabilities["provider_override"] == "strong"
    assert compatibility.capabilities["cancellation_control"] == "strong"


def test_agent_compatibility_reports_manual_only_when_binary_missing() -> None:
    compatibility = assess_agent_compatibility(
        "codex-cli",
        which=lambda _binary: None,
    )

    assert compatibility.compatibility_state == "manual_only"
    assert compatibility.capabilities["non_interactive_execution"] == "none"
    assert compatibility.reasons == ["binary_unavailable"]


def test_workspace_isolation_reports_ready_for_copy_and_blocked_for_missing_root(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    ready = assess_workspace_isolation(source_root, isolation_mode="copy")
    blocked = assess_workspace_isolation(tmp_path / "missing", isolation_mode="copy")

    assert ready.status == "ready"
    assert ready.effective_mode == "copy"
    assert blocked.status == "blocked"
    assert blocked.reasons == ["source_root_missing"]


def test_dispatch_readiness_reports_dispatchable_for_strong_agent_and_copy_workspace(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    readiness = assess_dispatch_readiness(
        "codex-cli",
        source_root,
        isolation_mode="copy",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert readiness.readiness_state == "dispatchable"
    assert readiness.compatibility_state == "dispatchable"
    assert readiness.isolation.status == "ready"
    assert readiness.isolation.effective_mode == "copy"


def test_dispatch_readiness_reports_manual_only_for_limited_agent(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="claude 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="--print --model --settings --bare --worktree --add-dir --output-format --no-session-persistence",
            stderr="",
        )

    readiness = assess_dispatch_readiness(
        "claude-code",
        source_root,
        isolation_mode="copy",
        which=lambda _binary: "/usr/bin/claude",
        run_command=fake_run,
    )

    assert readiness.readiness_state == "manual_only"
    assert readiness.compatibility_state == "limited"
    assert "config_isolation" in readiness.reasons
    assert readiness.isolation.status == "ready"


def test_dispatch_readiness_reports_blocked_when_worktree_is_unavailable(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    readiness = assess_dispatch_readiness(
        "codex-cli",
        source_root,
        isolation_mode="worktree",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert readiness.readiness_state == "blocked"
    assert readiness.compatibility_state == "dispatchable"
    assert readiness.isolation.status == "blocked"
    assert readiness.isolation.reasons == ["worktree_unavailable"]


def test_resolve_codex_openai_binding_defaults_to_codex_api_key() -> None:
    binding = resolve_agent_binding(
        "codex-cli",
        target_model="gpt-5",
        target_provider="openai",
    )

    assert binding.agent_id == "codex-cli"
    assert binding.provider_id == "openai"
    assert binding.model == "gpt-5"
    assert binding.api_key_env == "OPENAI_API_KEY"
    assert binding.codex_config_overrides == {"model_provider": "openai"}


def test_resolve_codex_openai_compatible_binding_requires_base_url_and_api_key_env() -> None:
    with pytest.raises(ProtocolError, match="requires provider_base_url"):
        resolve_agent_binding(
            "codex-cli",
            target_model="gpt-5",
            target_provider="openai-compatible",
        )

    with pytest.raises(ProtocolError, match="requires provider_api_key_env"):
        resolve_agent_binding(
            "codex-cli",
            target_model="gpt-5",
            target_provider="openai-compatible",
            provider_base_url="https://proxy.example.com/v1",
        )

    binding = resolve_agent_binding(
        "codex-cli",
        target_model="gpt-5-mini",
        target_provider="openai-compatible",
        provider_base_url="https://proxy.example.com/v1",
        provider_api_key_env="OPENAI_API_KEY",
    )

    assert binding.provider_id == "openai-compatible"
    assert binding.base_url == "https://proxy.example.com/v1"
    assert binding.api_key_env == "OPENAI_API_KEY"
    assert binding.codex_config_overrides["model_provider"] == "bureauless"
    assert (
        binding.codex_config_overrides["model_providers.bureauless.base_url"]
        == "https://proxy.example.com/v1"
    )
    assert (
        binding.codex_config_overrides[
            "model_providers.bureauless.requires_openai_auth"
        ]
        is True
    )


def test_cli_agent_list(capsys) -> None:
    exit_code = main(["agent", "list"])
    captured = capsys.readouterr()
    payload = yaml.safe_load(captured.out)

    assert exit_code == 0
    assert [item["agent_id"] for item in payload] == [
        "claude-code",
        "codex-cli",
        "gemini",
        "opencode",
        "pi",
    ]
    assert payload[1]["kind"] == "local_agent_cli"


def test_cli_agent_doctor(capsys) -> None:
    exit_code = main(["agent", "doctor", "codex-cli"])
    captured = capsys.readouterr()
    payload = yaml.safe_load(captured.out)

    assert exit_code == 0
    assert payload["agent_id"] == "codex-cli"
    assert payload["status"] in {"usable", "degraded", "unavailable"}
    assert "checks" in payload


def test_list_agent_compatibility_returns_known_agent_ids() -> None:
    payload = list_agent_compatibility(which=lambda _binary: None)

    assert [entry.agent_id for entry in payload] == [
        "claude-code",
        "codex-cli",
        "gemini",
        "opencode",
        "pi",
    ]
    assert all(entry.compatibility_state == "manual_only" for entry in payload)


def test_cli_agent_matrix(capsys) -> None:
    exit_code = main(["agent", "matrix"])
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert [item["agent_id"] for item in payload] == [
        "claude-code",
        "codex-cli",
        "gemini",
        "opencode",
        "pi",
    ]
    assert all(item["compatibility_state"] in {"dispatchable", "limited", "manual_only"} for item in payload)


def test_cli_agent_readiness(tmp_path, capsys) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    exit_code = main(["agent", "readiness", "codex-cli", "--workdir", str(source_root)])
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["agent_id"] == "codex-cli"
    assert payload["readiness_state"] in {"dispatchable", "manual_only", "blocked"}
    assert payload["isolation"]["status"] == "ready"


def test_fake_session_produces_result_without_touching_ledger(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="fake",
        workdir=tmp_path,
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.extraction["status"] == "synthetic"
    assert record.result_proposal is not None
    assert record.result_proposal["assignment_id"] == "assign-001"
    assert record.result_proposal["effective_model"] == "fake"
    assert ledger.event_log == []


def test_session_dry_run_and_cancel(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="fake",
        workdir=tmp_path,
        dry_run=True,
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    cancelled = cancel_session_record(record)

    assert record.status == "dry_run"
    assert record.extraction["status"] == "dry_run"
    assert record.result_proposal is None
    assert cancelled.status == "cancelled"
    assert cancelled.exit["reason"] == "cancelled"


def test_shell_dummy_session_timeout(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=tmp_path,
        shell_command="sleep 1",
        timeout_seconds=0.01,
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "timed_out"
    assert record.exit["reason"] == "timed_out"
    assert record.extraction["status"] == "timed_out"
    assert record.result_proposal is None


def test_codex_native_progress_extends_the_idle_timeout(tmp_path) -> None:
    completed = _run_live_process(
        [
            "python",
            "-u",
            "-c",
            "import sys, time; "
            "events = ['{\"type\":\"thread.started\"}', "
            "'{\"type\":\"item.started\"}', "
            "'{\"type\":\"turn.completed\"}']; "
            "[(sys.stdout.write(event + '\\n'), sys.stdout.flush(), time.sleep(0.04)) "
            "for event in events]",
        ],
        cwd=tmp_path,
        timeout=0.06,
        env=None,
        input_text=None,
        controller=None,
        progress_line=_is_codex_native_progress_line,
    )

    assert completed.returncode == 0


def test_shell_dummy_failed_run_reports_partial_workspace_effects(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=(
            "python3 -c \"from pathlib import Path; "
            "Path('tracked.txt').write_text('changed\\n', encoding='utf-8'); "
            "raise SystemExit(3)\""
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "failed"
    assert record.result_proposal is None
    assert record.outcome_metrics["changed_files_count"] == 1
    assert record.workspace["pre_state_ref"] != record.workspace["post_state_ref"]


def test_shell_dummy_extracts_structured_native_output(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai",
            "review_status": "not_required",
            "emitted_events": ["patch_ready"],
            "changed_files": ["src/app.py", "tests/test_app.py"],
            "patch": "--- a/src/app.py\n+++ b/src/app.py\n",
            "verification": {"status": "passed"},
            "native_log_refs": [{"kind": "stdout", "path": "logs/stdout.txt"}],
            "control_intents": [
                {"intent_type": "workflow_mutation", "proposal_id": "forged"}
            ],
            "artifacts": [
                {
                    "artifact_id": "artifact-001",
                    "path": "artifacts/report.md",
                    "sha256": "a" * 64,
                    "created_by": "shell-dummy",
                    "source_event": "event-result-session-001",
                    "mutable": False,
                }
            ],
            "outcome_metrics": {
                "input_tokens": 120,
                "output_tokens": 80,
                "cost_usd": 0.012,
                "cost_source": "adapter_reported",
                "cost_confidence": "high",
                "usage_confidence": "high",
            },
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=tmp_path,
        shell_command=f"cat <<'EOF'\n{payload}\nEOF",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.extraction["status"] == "extracted"
    assert record.result_proposal is not None
    assert record.result_proposal["effective_model"] == "gpt-5.4-mini"
    assert record.result_proposal["effective_provider"] == "openai"
    assert record.result_proposal["review_status"] == "not_required"
    assert record.result_proposal["emitted_events"] == ["patch_ready"]
    assert record.result_proposal["control_intents"] == [
        {"intent_type": "workflow_mutation", "proposal_id": "forged"}
    ]
    assert record.outcome_metrics["input_tokens"] == 120
    assert record.outcome_metrics["output_tokens"] == 80
    assert record.outcome_metrics["total_tokens"] == 200
    assert record.outcome_metrics["cost_usd"] == 0.012
    assert record.outcome_metrics["patch_bytes"] > 0
    assert record.outcome_metrics["changed_files_count"] == 2
    assert record.diff_refs[0]["kind"] == "inline_patch"
    assert record.artifacts[0]["artifact_id"] == "artifact-001"


def test_shell_dummy_marks_unstructured_output_as_agent_not_emitting_usage(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=tmp_path,
        shell_command="printf 'plain text output only\\n'",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.extraction["status"] == "agent_does_not_emit_usage"
    assert record.result_proposal is not None
    assert record.result_proposal["emitted_events"] == []
    assert record.outcome_metrics["usage_confidence"] == "none"
    assert record.outcome_metrics["cost_source"] == "agent_not_supported"
    assert "total_tokens" not in record.outcome_metrics


def test_reported_cost_is_not_promoted_to_a_payment_side_effect(tmp_path) -> None:
    workflow = _workflow()
    assignment = export_assignment(
        workflow,
        _empty_ledger(),
        "implement",
        assignment_id="assign-cost-only",
    )
    mission, packet = _dispatch_fixture(workflow, assignment, "packet-cost-only")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "outcome_metrics": {
                "cost_usd": 0.01,
                "cost_source": "provider_reported",
            },
        },
        sort_keys=False,
    ).strip()
    record = dispatch_session(
        mission,
        workflow,
        packet,
        agent_id="shell-dummy",
        workdir=tmp_path,
        dispatch_packet_path=tmp_path / "dispatch-cost-only.yaml",
        shell_command=f"cat <<'EOF'\n{payload}\nEOF",
        session_id="session-cost-only",
    )

    assert record.outcome_metrics["cost_usd"] == 0.01
    assert all(
        effect["type"] != "payment"
        for effect in record.audit_evidence["side_effects"]
    )
    assert record.audit_evidence["side_effect_coverage"]["payment"] == {
        "status": "not_observed",
        "evidence_source": "unavailable",
        "evidence_ref": None,
    }


def test_shell_dummy_reports_wrapper_failed_to_extract(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=tmp_path,
        shell_command="printf 'status: [broken\\n'",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.extraction["status"] == "wrapper_failed_to_extract"
    assert record.result_proposal is not None
    assert record.result_proposal["emitted_events"] == []
    assert record.extraction["warnings"] != []


def test_shell_dummy_copy_isolation_preserves_source_root(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")

    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        isolation_mode="copy",
        shell_command=(
            "python3 -c \"from pathlib import Path; "
            "Path('tracked.txt').write_text('changed\\n', encoding='utf-8')\""
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    workspace_file = Path(record.workspace["path"]) / "tracked.txt"

    assert record.workspace["mode"] == "copy"
    assert tracked.read_text(encoding="utf-8") == "original\n"
    assert workspace_file.read_text(encoding="utf-8") == "changed\n"
    assert Path(record.native_logs["stdout_path"]).exists()
    assert Path(record.native_logs["stderr_path"]).exists()
    assert str(workspace_file.parent) in record.workspace["retained_paths"]


def test_shell_dummy_ignores_preexisting_dirty_workspace_in_delta_metrics(tmp_path) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked.write_text("dirty-before-session\n", encoding="utf-8")

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        isolation_mode="copy",
        shell_command="printf 'plain text output only\\n'",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.outcome_metrics["changed_files_count"] == 0
    assert "patch_bytes" not in record.outcome_metrics
    assert record.diff_refs == []


def test_shell_dummy_worktree_isolation_when_git_available(tmp_path) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        isolation_mode="worktree",
        shell_command=(
            "python3 -c \"from pathlib import Path; "
            "Path('tracked.txt').write_text('changed\\n', encoding='utf-8')\""
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    workspace_file = Path(record.workspace["path"]) / "tracked.txt"

    assert record.workspace["mode"] == "worktree"
    assert tracked.read_text(encoding="utf-8") == "original\n"
    assert workspace_file.read_text(encoding="utf-8") == "changed\n"


def test_codex_session_requires_target_model_and_provider(tmp_path) -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")

    with pytest.raises(ProtocolError, match="requires target_model and target_provider"):
        create_session_spec(
            assignment=assignment,
            agent_id="codex-cli",
            workdir=tmp_path,
            session_id="session-001",
        )


def test_gemini_session_runs_in_an_ephemeral_home_and_extracts_native_usage(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    source_root.joinpath("tracked.txt").write_text("original\n", encoding="utf-8")
    assignment = export_assignment(_workflow(), _empty_ledger(), "implement", assignment_id="assign-001")
    secret = "top-secret-gemini-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    spec = create_session_spec(
        assignment=assignment,
        agent_id="gemini",
        workdir=source_root,
        target_model="gemini-3-pro-preview",
        target_provider="gemini-compatible",
        provider_base_url="https://gateway.example/gemini",
        session_id="session-001",
    )
    homes: list[Path] = []
    stdout = "\n".join(
        [
            '{"type":"init","session_id":"native-session","model":"gemini-3-pro-preview"}',
            f'{{"type":"message","role":"assistant","content":"done {secret}"}}',
            '{"type":"tool_use","tool_id":"tool-1","tool_name":"replace"}',
            '{"type":"tool_result","tool_id":"tool-1"}',
            '{"type":"result","stats":{"input_tokens":100,"output_tokens":20,"cached":11,"total_tokens":131,"duration_ms":12,"tool_calls":1,"models":{"gemini-3.1-pro-preview":{}}}}',
        ]
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert command[:5] == ["gemini", "--skip-trust", "--approval-mode", "auto_edit", "--output-format"]
        assert "stream-json" in command
        assert "--model" in command
        assert "gemini-3-pro-preview" in command
        assert kwargs["env"]["GEMINI_API_KEY"] == secret
        assert kwargs["env"]["GOOGLE_GEMINI_BASE_URL"] == "https://gateway.example/gemini"
        home = Path(kwargs["env"]["HOME"])
        homes.append(home)
        assert yaml.safe_load(home.joinpath(".gemini/settings.json").read_text()) == {
            "security": {"auth": {"selectedType": "gemini-api-key"}}
        }
        Path(kwargs["cwd"]).joinpath("tracked.txt").write_text("changed\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout, "")

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.status == "completed"
    assert record.result_proposal is not None
    assert record.result_proposal["effective_provider"] == "gemini-compatible"
    assert record.outcome_metrics["input_tokens"] == 100
    assert record.outcome_metrics["output_tokens"] == 20
    assert record.outcome_metrics["total_tokens"] == 131
    assert record.outcome_metrics["cached_input_tokens"] == 11
    assert record.outcome_metrics["agent_tool_calls"] == 1
    assert record.extraction["native_session_id"] == "native-session"
    assert record.extraction["provider_reported_models"] == ["gemini-3.1-pro-preview"]
    assert record.outcome_metrics["changed_files_count"] == 1
    assert len(record.extraction["native_tool_events"]) == 2
    serialized = yaml.safe_dump(record.to_dict())
    assert secret not in serialized
    assert "<redacted>" in record.native_logs["stdout"]
    assert secret not in Path(record.native_logs["stdout_path"]).read_text(encoding="utf-8")
    assert homes and not homes[0].exists()


def test_codex_session_produces_importable_result_from_completed_run(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert command[:4] == ["codex", "--ask-for-approval", "never", "exec"]
        assert "--json" in command
        assert "--ignore-user-config" in command
        assert "--ephemeral" in command
        assert "--model" in command
        assert "gpt-5" in command
        assert '-c' in command
        assert 'model_provider="openai"' in command
        assert kwargs["env"]["OPENAI_API_KEY"] == "test-key"
        assert "CODEX_HOME" in kwargs["env"]
        auth_path = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
        assert auth_path.exists()
        auth_payload = yaml.safe_load(auth_path.read_text(encoding="utf-8"))
        assert auth_payload["OPENAI_API_KEY"] == "test-key"
        Path(kwargs["cwd"]) .joinpath("tracked.txt").write_text("changed\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"message","role":"assistant","content":"done"}\n',
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.status == "completed"
    assert record.result_proposal is not None
    assert record.result_proposal["effective_model"] == "gpt-5"
    assert record.result_proposal["effective_provider"] == "openai"
    assert record.outcome_metrics["changed_files_count"] == 1
    assert record.outcome_metrics["patch_bytes"] > 0
    assert record.diff_refs[0]["kind"] == "inline_patch"


def test_create_session_spec_accepts_explicit_sandbox_mode() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-commit",
        force=True,
    )

    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=Path("."),
        target_model="gpt-5",
        target_provider="openai",
        sandbox_mode="danger-full-access",
        session_id="session-commit",
    )

    assert spec.sandbox_mode == "danger-full-access"


def test_codex_session_ignores_preexisting_dirty_workspace_in_delta_metrics(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked.write_text("dirty-before-session\n", encoding="utf-8")

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"message","role":"assistant","content":"OK"}\n',
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.status == "completed"
    assert record.outcome_metrics["changed_files_count"] == 0
    assert "patch_bytes" not in record.outcome_metrics
    assert record.diff_refs == []


def test_codex_session_extracts_usage_from_jsonl(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    stdout = (
        '{"type":"thread.started","thread_id":"x"}\n'
        '{"type":"turn.started"}\n'
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"OK"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":25,"output_tokens":20,"reasoning_output_tokens":10}}\n'
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.outcome_metrics["input_tokens"] == 100
    assert record.outcome_metrics["output_tokens"] == 20
    assert record.outcome_metrics["total_tokens"] == 120
    assert record.outcome_metrics["cached_input_tokens"] == 25
    assert record.outcome_metrics["reasoning_output_tokens"] == 10
    assert record.outcome_metrics["usage_confidence"] == "high"
    assert record.extraction["assistant_text"] == "OK"
    assert not Path(record.workspace["session_root"]).joinpath("codex-home").exists()


def test_provider_usage_capture_round_trips_and_writes_immutable_artifact(tmp_path) -> None:
    capture = ProviderUsageCapture(
        assignment_id="assign-001",
        session_id="session-001",
        result_id="result-001",
        agent_id="codex-cli",
        provider="openai-compatible",
        model="gpt-5.4",
        collected_at="2026-07-10T00:00:00Z",
        source_ref="responses/resp_123",
        usage={
            "input_tokens": 120,
            "output_tokens": 30,
            "cached_input_tokens": 10,
            "reasoning_output_tokens": 4,
            "cost_usd": 0.012,
            "cost_source": "provider_attributed",
            "cost_confidence": "high",
            "usage_confidence": "high",
        },
    )

    artifact_path = tmp_path / "artifacts" / "usage" / "provider-usage.yaml"
    artifact = write_provider_usage_capture_artifact(
        artifact_path,
        capture,
        source_event="event-result-001",
    )

    stored = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))
    loaded = load_provider_usage_capture(stored)

    assert loaded.usage["total_tokens"] == 150
    assert loaded.usage["cached_input_tokens"] == 10
    assert artifact["artifact_type"] == "provider_usage_capture"
    assert artifact["source_event"] == "event-result-001"
    assert artifact["sha256"] == sha256_file(artifact_path)


def test_provider_usage_capture_rejects_unknown_or_inconsistent_usage_fields() -> None:
    with pytest.raises(ProtocolError, match="unknown fields"):
        load_provider_usage_capture(
            {
                "artifact_type": "provider_usage_capture",
                "assignment_id": "assign-001",
                "session_id": "session-001",
                "agent_id": "codex-cli",
                "provider": "openai-compatible",
                "model": "gpt-5.4",
                "collected_at": "2026-07-10T00:00:00Z",
                "source": "provider_usage_capture_v1",
                "usage": {"prompt_tokens": 120},
            }
        )
    with pytest.raises(ProtocolError, match="total_tokens must equal"):
        load_provider_usage_capture(
            {
                "artifact_type": "provider_usage_capture",
                "assignment_id": "assign-001",
                "session_id": "session-001",
                "agent_id": "codex-cli",
                "provider": "openai-compatible",
                "model": "gpt-5.4",
                "collected_at": "2026-07-10T00:00:00Z",
                "source": "provider_usage_capture_v1",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 999,
                },
            }
        )


def test_codex_openai_compatible_session_captures_provider_usage_artifact(
    tmp_path, monkeypatch
) -> None:
    class _ProviderHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            payload = {
                "id": "resp_test_123",
                "model": "gpt-5.4",
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "input_tokens_details": {"cached_tokens": 20},
                    "output_tokens_details": {"reasoning_tokens": 5},
                },
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            return

    provider_server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider_server.serve_forever, daemon=True)
    provider_thread.start()
    try:
        source_root = tmp_path / "repo"
        source_root.mkdir()
        assignment = export_assignment(
            _workflow(), _empty_ledger(), "implement", assignment_id="assign-001"
        )
        monkeypatch.setenv("TEST_OPENAI_COMPAT_KEY", "test-key")
        spec = create_session_spec(
            assignment=assignment,
            agent_id="codex-cli",
            workdir=source_root,
            target_model="gpt-5.4",
            target_provider="openai-compatible",
            provider_base_url=f"http://127.0.0.1:{provider_server.server_port}",
            provider_api_key_env="TEST_OPENAI_COMPAT_KEY",
            session_id="session-001",
        )
        assistant_text = yaml.safe_dump(
            {
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "verification": {"status": "passed"},
            },
            sort_keys=False,
        ).strip()

        def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
            proxy_base_url = None
            for index, value in enumerate(command):
                if value == "-c" and index + 1 < len(command):
                    override = command[index + 1]
                    prefix = "model_providers.bureauless.base_url="
                    if override.startswith(prefix):
                        proxy_base_url = override[len(prefix) :].strip('"')
                        break
            assert proxy_base_url is not None
            request = urllib_request.Request(
                f"{proxy_base_url}/responses",
                data=json.dumps({"input": "ping"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-key",
                },
                method="POST",
            )
            with urllib_request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            assert payload["usage"]["input_tokens"] == 120
            stdout = "\n".join(
                [
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": assistant_text},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        }
                    ),
                ]
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")

        record = run_session(spec, assignment, command_runner=fake_runner)
        packaged = package_session_result(record, assignment, artifact_root=tmp_path)

        provider_capture = load_provider_usage_capture(record.extraction["provider_usage_capture"])
        provider_artifact = next(
            artifact
            for artifact in packaged.artifacts
            if artifact.get("artifact_type") == "provider_usage_capture"
        )
        stored = yaml.safe_load((tmp_path / provider_artifact["path"]).read_text(encoding="utf-8"))

        assert provider_capture.provider == "openai-compatible"
        assert provider_capture.model == "gpt-5.4"
        assert provider_capture.usage["input_tokens"] == 120
        assert provider_capture.usage["output_tokens"] == 30
        assert provider_capture.usage["cached_input_tokens"] == 20
        assert provider_capture.usage["reasoning_output_tokens"] == 5
        assert provider_capture.usage["usage_confidence"] == "high"
        assert provider_capture.source_ref == "resp_test_123"
        assert record.outcome_metrics["input_tokens"] == 120
        assert record.outcome_metrics["output_tokens"] == 30
        assert record.outcome_metrics["total_tokens"] == 150
        assert record.outcome_metrics["cached_input_tokens"] == 20
        assert record.outcome_metrics["reasoning_output_tokens"] == 5
        assert record.outcome_metrics["usage_source"] == "provider_attributed"
        assert provider_artifact["created_by"] == "harness"
        assert provider_artifact["path"].startswith("artifacts/provider-usage/")
        assert stored["usage"]["total_tokens"] == 150
    finally:
        provider_server.shutdown()
        provider_server.server_close()
        provider_thread.join(timeout=1.0)


def test_codex_openai_compatible_session_captures_provider_usage_from_sse(
    tmp_path, monkeypatch
) -> None:
    class _ProviderHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            chunks = [
                'event: response.output_text.delta\n'
                'data: {"type":"response.output_text.delta","delta":"pong"}\n\n',
                'event: response.completed\n'
                'data: {"type":"response.completed","response":{"id":"resp_sse_123","model":"gpt-5.5","usage":{"input_tokens":140,"output_tokens":35,"input_tokens_details":{"cached_tokens":22},"output_tokens_details":{"reasoning_tokens":6}}}}\n\n',
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()

        def log_message(self, _format: str, *_args) -> None:
            return

    provider_server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider_server.serve_forever, daemon=True)
    provider_thread.start()
    try:
        source_root = tmp_path / "repo"
        source_root.mkdir()
        assignment = export_assignment(
            _workflow(), _empty_ledger(), "implement", assignment_id="assign-001"
        )
        monkeypatch.setenv("TEST_OPENAI_COMPAT_KEY", "test-key")
        spec = create_session_spec(
            assignment=assignment,
            agent_id="codex-cli",
            workdir=source_root,
            target_model="gpt-5.5",
            target_provider="openai-compatible",
            provider_base_url=f"http://127.0.0.1:{provider_server.server_port}",
            provider_api_key_env="TEST_OPENAI_COMPAT_KEY",
            session_id="session-001",
        )
        assistant_text = yaml.safe_dump(
            {
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "verification": {"status": "passed"},
            },
            sort_keys=False,
        ).strip()

        def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
            proxy_base_url = None
            for index, value in enumerate(command):
                if value == "-c" and index + 1 < len(command):
                    override = command[index + 1]
                    prefix = "model_providers.bureauless.base_url="
                    if override.startswith(prefix):
                        proxy_base_url = override[len(prefix) :].strip('"')
                        break
            assert proxy_base_url is not None
            request = urllib_request.Request(
                f"{proxy_base_url}/responses",
                data=json.dumps({"input": "ping"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-key",
                },
                method="POST",
            )
            with urllib_request.urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
            assert '"type":"response.completed"' in body
            stdout = "\n".join(
                [
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": assistant_text},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        }
                    ),
                ]
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")

        record = run_session(spec, assignment, command_runner=fake_runner)

        assert record.outcome_metrics["usage_source"] == "provider_attributed"
        assert record.outcome_metrics["input_tokens"] == 140
        assert record.outcome_metrics["output_tokens"] == 35
        assert record.outcome_metrics["total_tokens"] == 175
        assert record.outcome_metrics["cached_input_tokens"] == 22
        assert record.outcome_metrics["reasoning_output_tokens"] == 6
        assert record.extraction["provider_usage_capture"]["source_ref"] == "resp_sse_123"
    finally:
        provider_server.shutdown()
        provider_server.server_close()
        provider_thread.join(timeout=1.0)


def test_codex_openai_compatible_proxy_returns_502_when_provider_disconnects(
    tmp_path, monkeypatch
) -> None:
    class _ProviderHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            self.connection.close()

        def log_message(self, _format: str, *_args) -> None:
            return

    provider_server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider_server.serve_forever, daemon=True)
    provider_thread.start()
    try:
        source_root = tmp_path / "repo"
        source_root.mkdir()
        assignment = export_assignment(
            _workflow(), _empty_ledger(), "implement", assignment_id="assign-001"
        )
        monkeypatch.setenv("TEST_OPENAI_COMPAT_KEY", "test-key")
        spec = create_session_spec(
            assignment=assignment,
            agent_id="codex-cli",
            workdir=source_root,
            target_model="gpt-5.5",
            target_provider="openai-compatible",
            provider_base_url=f"http://127.0.0.1:{provider_server.server_port}",
            provider_api_key_env="TEST_OPENAI_COMPAT_KEY",
            session_id="session-001",
        )
        assistant_text = yaml.safe_dump(
            {
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "verification": {"status": "passed"},
            },
            sort_keys=False,
        ).strip()

        def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
            proxy_base_url = None
            for index, value in enumerate(command):
                if value == "-c" and index + 1 < len(command):
                    override = command[index + 1]
                    prefix = "model_providers.bureauless.base_url="
                    if override.startswith(prefix):
                        proxy_base_url = override[len(prefix) :].strip('"')
                        break
            assert proxy_base_url is not None
            request = urllib_request.Request(
                f"{proxy_base_url}/responses",
                data=json.dumps({"input": "ping"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-key",
                },
                method="POST",
            )
            with pytest.raises(urllib_error.HTTPError) as exc_info:
                urllib_request.urlopen(request, timeout=5)
            assert exc_info.value.code == 502
            stdout = "\n".join(
                [
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": assistant_text},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        }
                    ),
                ]
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")

        record = run_session(spec, assignment, command_runner=fake_runner)

        assert record.status == "completed"
        assert record.outcome_metrics["usage_source"] == "agent_reported"
        assert "provider_usage_capture" not in record.extraction
    finally:
        provider_server.shutdown()
        provider_server.server_close()
        provider_thread.join(timeout=1.0)


def test_package_session_result_merges_provider_usage_capture_into_result_metrics(tmp_path) -> None:
    assignment = export_assignment(
        _workflow(), _empty_ledger(), "implement", assignment_id="assign-001"
    )
    record = load_session_record(
        {
            "session_id": "session-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "exit": {"code": 0, "reason": "completed"},
            "native_logs": {"stdout": "", "stderr": ""},
            "diff_refs": [],
            "artifacts": [],
            "workspace": {
                "path": str(tmp_path),
                "source_root": str(tmp_path),
                "session_root": str(tmp_path),
            },
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 0,
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "usage_confidence": "low",
            },
            "extraction": {
                "status": "native_stream_captured",
                "provider_usage_capture": {
                    "artifact_type": "provider_usage_capture",
                    "assignment_id": "assign-001",
                    "session_id": "session-001",
                    "result_id": "result-session-001",
                    "agent_id": "codex-cli",
                    "provider": "openai-compatible",
                    "model": "gpt-5.4",
                    "collected_at": "2026-01-01T00:00:01Z",
                    "source": "provider_usage_capture_v1",
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 30,
                        "cached_input_tokens": 20,
                        "reasoning_output_tokens": 5,
                        "usage_confidence": "high",
                    },
                },
            },
            "result_proposal": {
                "result_id": "result-session-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "effective_model": "gpt-5.4",
                "effective_provider": "openai-compatible",
                "emitted_events": ["patch_ready"],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 0,
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                    "usage_confidence": "low",
                },
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        }
    )

    packaged = package_session_result(record, assignment, artifact_root=tmp_path)

    assert packaged.outcome_metrics["input_tokens"] == 120
    assert packaged.outcome_metrics["output_tokens"] == 30
    assert packaged.outcome_metrics["total_tokens"] == 150
    assert packaged.outcome_metrics["cached_input_tokens"] == 20
    assert packaged.outcome_metrics["reasoning_output_tokens"] == 5
    assert packaged.outcome_metrics["usage_source"] == "provider_attributed"
    assert packaged.outcome_metrics["usage_confidence"] == "high"


def test_dispatch_session_allows_provider_specific_gpt5_family_models(
    tmp_path, monkeypatch
) -> None:
    workflow = _workflow()
    assignment = export_assignment(
        workflow, _empty_ledger(), "implement", assignment_id="assign-001"
    )
    mission, packet = _dispatch_fixture(workflow, assignment)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": yaml.safe_dump(
                                {
                                    "status": "completed",
                                    "emitted_events": ["patch_ready"],
                                    "verification": {"status": "passed"},
                                },
                                sort_keys=False,
                            ).strip(),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    }
                ),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    record = dispatch_session(
        mission,
        workflow,
        packet,
        agent_id="codex-cli",
        workdir=tmp_path,
        dispatch_packet_path=tmp_path / "dispatch.yaml",
        target_model="gpt-5.5",
        target_provider="openai",
        session_id="session-family-model",
        command_runner=fake_runner,
    )

    assert record.status == "completed"
    assert record.result_proposal is not None
    assert record.result_proposal["effective_model"] == "gpt-5.5"


def test_metrics_summarize_preserves_provider_attribution_after_result_import(tmp_path) -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    record = load_session_record(
        {
            "session_id": "session-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "exit": {"code": 0, "reason": "completed"},
            "native_logs": {"stdout": "", "stderr": ""},
            "diff_refs": [],
            "artifacts": [],
            "workspace": {
                "path": str(tmp_path),
                "source_root": str(tmp_path),
                "session_root": str(tmp_path),
            },
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 0,
                "usage_source": "provider_attributed",
                "usage_confidence": "high",
            },
            "extraction": {
                "status": "native_stream_captured",
                "provider_usage_capture": {
                    "artifact_type": "provider_usage_capture",
                    "assignment_id": "assign-001",
                    "session_id": "session-001",
                    "result_id": "result-session-001",
                    "agent_id": "codex-cli",
                    "provider": "openai-compatible",
                    "model": "gpt-5.4",
                    "collected_at": "2026-01-01T00:00:01Z",
                    "source": "provider_usage_capture_v1",
                    "source_ref": "resp_test_123",
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 30,
                        "cached_input_tokens": 20,
                        "reasoning_output_tokens": 5,
                        "cost_usd": 0.012,
                        "usage_confidence": "high",
                    },
                },
            },
            "result_proposal": {
                "result_id": "result-session-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "effective_model": "gpt-5.4",
                "effective_provider": "openai-compatible",
                "emitted_events": ["patch_ready"],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 0,
                },
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        }
    )

    packaged = package_session_result(record, assignment, artifact_root=tmp_path)
    updated = import_result_proposal(workflow, ledger, assignment, packaged)
    ledger_path = tmp_path / "ledger.yaml"
    write_ledger(ledger_path, updated)

    summary = summarize_metrics(ledger_path)
    entry = summary["entries"][0]

    assert entry["usage_source"] == "provider_attributed"
    assert entry["input_tokens"] == 120
    assert entry["output_tokens"] == 30
    assert entry["total_tokens"] == 150
    assert entry["cached_input_tokens"] == 20
    assert entry["reasoning_output_tokens"] == 5
    assert entry["cost_usd"] == 0.012
    assert entry["provider"] == "openai-compatible"


def test_metrics_summarize_distinguishes_provider_agent_and_missing_usage_sources(
    tmp_path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    fixtures = [
        (
            "provider.yaml",
            {
                "session_id": "session-provider",
                "assignment_id": "assign-provider",
                "agent_id": "codex-cli",
                "effective_model": "gpt-5.4",
                "effective_provider": "openai-compatible",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "total_tokens": 150,
                    "cached_input_tokens": 20,
                    "reasoning_output_tokens": 5,
                    "cost_usd": 0.012,
                    "usage_source": "provider_attributed",
                    "usage_confidence": "high",
                    "cost_source": "provider_attributed",
                    "cost_confidence": "high",
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
        ),
        (
            "agent.yaml",
            {
                "session_id": "session-agent",
                "assignment_id": "assign-agent",
                "agent_id": "codex-cli",
                "effective_model": "gpt-5.4",
                "effective_provider": "openai",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 40,
                    "output_tokens": 10,
                    "total_tokens": 50,
                    "usage_source": "agent_reported",
                    "usage_confidence": "high",
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
        ),
        (
            "missing.yaml",
            {
                "session_id": "session-missing",
                "assignment_id": "assign-missing",
                "agent_id": "shell-dummy",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 0,
                    "usage_source": "unavailable",
                    "usage_confidence": "none",
                },
                "result_proposal": {},
            },
        ),
    ]
    for filename, payload in fixtures:
        (sessions_dir / filename).write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )

    summary = summarize_metrics(sessions_dir)
    by_assignment = {entry["assignment_id"]: entry for entry in summary["entries"]}

    assert by_assignment["assign-provider"]["usage_source"] == "provider_attributed"
    assert by_assignment["assign-agent"]["usage_source"] == "agent_reported"
    assert by_assignment["assign-missing"]["usage_source"] == "unavailable"
    assert summary["observed_budget"]["total_tokens_used"] == 200
    assert summary["observed_budget"]["missing_usage_count"] == 1
    assert summary["observed_budget"]["known_cost_usd_total"] == 0.012


def test_codex_session_extracts_structured_result_from_assistant_text(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    stdout = (
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"status: completed\\n'
        'emitted_events:\\n  - patch_ready\\nverification:\\n  status: passed"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert "Output Contract" in kwargs["input"]
        assert "control_intents" in kwargs["input"]
        assert "mutation_proposal_refs" not in kwargs["input"]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.result_proposal is not None
    assert record.result_proposal["status"] == "completed"
    assert record.result_proposal["emitted_events"] == ["patch_ready"]
    assert record.result_proposal["verification"] == {"status": "passed"}
    assert "control_intents" not in record.result_proposal
    assert record.extraction["emitted_events"] == ["patch_ready"]
    assert record.extraction["verification"] == {"status": "passed"}
    assert record.outcome_metrics["input_tokens"] == 100
    assert record.outcome_metrics["total_tokens"] == 120


def test_codex_session_tolerates_backticks_in_structured_assistant_text(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    stdout = (
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"status: completed\\n'
        'emitted_events:\\n  - patch_ready\\nverification:\\n  status: passed\\n  details:\\n'
        '  - updated `src/demo.py`"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.result_proposal is not None
    assert record.result_proposal["emitted_events"] == ["patch_ready"]
    assert record.result_proposal["verification"]["status"] == "passed"


def test_codex_session_extracts_blocked_mutation_control_intent(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    assignment = export_assignment(
        _workflow(), _empty_ledger(), "implement", assignment_id="assign-001"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )
    assistant_text = yaml.safe_dump(
        {
            "status": "blocked",
            "emitted_events": [],
            "verification": {"status": "workflow_structure"},
            "control_intents": [_mutation_intent()],
        },
        sort_keys=False,
    ).strip()
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": assistant_text},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                }
            ),
        ]
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout, "")

    record = run_session(spec, assignment, command_runner=fake_runner)
    packaged = package_session_result(record, assignment)

    assert record.extraction["control_intents"] == [_mutation_intent()]
    assert record.result_proposal is not None
    assert record.result_proposal["status"] == "blocked"
    assert packaged.control_intents == [_mutation_intent()]


def test_package_session_result_normalizes_artifacts_and_native_logs(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai",
            "emitted_events": ["patch_ready"],
            "artifacts": [
                {
                    "artifact_id": "artifact-report",
                    "path": "artifacts/report.md",
                }
            ],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=(
            "mkdir -p artifacts\n"
            "printf 'report\\n' > artifacts/report.md\n"
            f"cat <<'EOF'\n{payload}\nEOF"
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    packaged = package_session_result(record, assignment)
    packaged_again = package_session_result(record, assignment)

    assert packaged.to_dict() == packaged_again.to_dict()
    assert packaged.result_id == "result-session-001"
    assert packaged.artifacts[0]["artifact_id"] == "artifact-report"
    assert packaged.artifacts[0]["path"] == "workspace/artifacts/report.md"
    assert packaged.artifacts[0]["source_event"] == "event-result-session-001"
    assert packaged.native_log_refs[0]["path"] == "logs/stdout.log"
    assert packaged.native_log_refs[1]["path"] == "logs/stderr.log"
    assert packaged.native_log_refs[0]["sha256"]


def test_session_packages_mutation_proposal_artifact_ref(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    payload = yaml.safe_dump(
        {
            "status": "completed_with_proposal",
            "emitted_events": [],
            "artifacts": [
                {
                    "artifact_id": "artifact-mutation-001",
                    "path": "artifacts/mutation-001.yaml",
                }
            ],
            "mutation_proposal_refs": ["artifact-mutation-001"],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=(
            "mkdir -p artifacts\n"
            "printf 'proposal_type: workflow_mutation\\n' > artifacts/mutation-001.yaml\n"
            f"cat <<'EOF'\n{payload}\nEOF"
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    packaged = package_session_result(record, assignment)

    assert record.extraction["mutation_proposal_refs"] == [
        "artifact-mutation-001"
    ]
    assert packaged.status == "completed_with_proposal"
    assert packaged.mutation_proposal_refs == ["artifact-mutation-001"]
    assert packaged.artifacts[0]["artifact_id"] == "artifact-mutation-001"
    assert packaged.artifacts[0]["path"] == (
        "workspace/artifacts/mutation-001.yaml"
    )
    assert len(packaged.artifacts[0]["sha256"]) == 64
    assert packaged.artifacts[0]["mutable"] is False


def test_package_session_result_ignores_non_ref_artifact_metadata(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "commit", assignment_id="assign-001", force=True
    )
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["commit_created"],
            "artifacts": [
                {"commit": "abc123"},
                {"message": "Apply approved demo patch"},
            ],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=f"cat <<'EOF'\n{payload}\nEOF",
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    packaged = package_session_result(record, assignment)

    assert packaged.artifacts == []


def test_package_session_result_rejects_missing_artifact_or_assignment_mismatch(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    wrong_assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-002")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [{"path": "artifacts/missing.md"}],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=f"cat <<'EOF'\n{payload}\nEOF",
        session_id="session-001",
    )
    record = run_session(spec, assignment)

    try:
        package_session_result(record, wrong_assignment)
    except ProtocolError as exc:
        assert "assignment_id does not match" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    try:
        package_session_result(record, assignment)
    except ProtocolError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_packaged_session_result_reuses_manual_result_import_path(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [{"artifact_id": "artifact-report", "path": "artifacts/report.md"}],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=(
                "mkdir -p artifacts\n"
                "printf 'report\\n' > artifacts/report.md\n"
                f"cat <<'EOF'\n{payload}\nEOF"
            ),
            session_id="session-001",
        ),
        assignment,
    )

    packaged = package_session_result(record, assignment)
    updated = import_result_proposal(workflow, ledger, assignment, packaged)
    replay = replay_workflow(workflow, updated)

    assert updated.event_log[0]["event_type"] == "result_submitted"
    assert updated.event_log[1]["event_type"] == "patch_ready"
    assert updated.event_log[0]["result"]["artifacts"][0]["path"] == "workspace/artifacts/report.md"
    assert updated.event_log[0]["result"]["native_log_refs"][0]["path"] == "logs/stdout.log"
    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"


def test_session_lifecycle_events_map_timeout_cancel_and_supersede(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="fake",
        workdir=tmp_path,
        session_id="session-001",
    )
    created = build_assignment_created_event(workflow, assignment, spec.session_id, spec.agent_id)
    timed_out = build_session_terminal_event(
        workflow,
        assignment,
        run_session(
            create_session_spec(
                assignment=assignment,
                agent_id="shell-dummy",
                workdir=tmp_path,
                shell_command="sleep 1",
                timeout_seconds=0.01,
                session_id="session-timeout",
            ),
            assignment,
        ),
    )
    cancelled = build_session_terminal_event(
        workflow,
        assignment,
        cancel_session_record(run_session(spec, assignment), reason="user_cancelled"),
    )
    superseded = build_session_terminal_event(
        workflow,
        assignment,
        supersede_session_record(run_session(spec, assignment)),
        superseded_by="assign-002",
    )

    assert created["event_type"] == "assignment_created"
    assert created["assignment_id"] == "assign-001"
    assert timed_out is not None and timed_out["event_type"] == "worker_timeout"
    assert cancelled is not None and cancelled["event_type"] == "assignment_cancelled"
    assert cancelled["reason"] == "user_cancelled"
    assert superseded is not None and superseded["event_type"] == "assignment_superseded"
    assert superseded["superseded_by"] == "assign-002"


def test_replay_blocks_duplicate_dispatch_while_assignment_is_in_flight() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-assign-001-created",
                    "event_type": "assignment_created",
                    "mission_id": "demo",
                    "workflow_id": "test-workflow",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                    "agent_id": "shell-dummy",
                    "session_id": "session-001",
                }
            ],
        }
    )

    gatekeeper = evaluate_gatekeeper(workflow, ledger)
    replay = replay_workflow(workflow, ledger)

    assert gatekeeper.ready == []
    assert gatekeeper.decisions["implement"].state == "blocked"
    assert gatekeeper.decisions["implement"].blocked_reasons[0].code == "assignment_in_flight"
    assert replay.nodes["implement"].assignment_attempts[0].state == "in_flight"


def test_replay_reopens_node_after_timeout_or_cancellation() -> None:
    workflow = _workflow()
    timeout_ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-assign-001-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-assign-001-timeout",
                    "event_type": "worker_timeout",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                },
            ],
        }
    )
    cancelled_ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-assign-002-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-002",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-assign-002-cancelled",
                    "event_type": "assignment_cancelled",
                    "assignment_id": "assign-002",
                    "node_id": "implement",
                    "role": "coder",
                },
            ],
        }
    )

    timeout_result = evaluate_gatekeeper(workflow, timeout_ledger)
    cancelled_result = evaluate_gatekeeper(workflow, cancelled_ledger)
    timeout_replay = replay_workflow(workflow, timeout_ledger)
    cancelled_replay = replay_workflow(workflow, cancelled_ledger)

    assert timeout_result.ready == ["implement"]
    assert cancelled_result.ready == ["implement"]
    assert timeout_replay.nodes["implement"].assignment_attempts[0].state == "timed_out"
    assert cancelled_replay.nodes["implement"].assignment_attempts[0].state == "cancelled"
    assert timeout_replay.nodes["implement"].state == "runnable"
    assert cancelled_replay.nodes["implement"].state == "runnable"


def test_replay_tracks_superseded_assignment_without_marking_completed() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-assign-001-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-assign-001-superseded",
                    "event_type": "assignment_superseded",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                    "superseded_by": "assign-002",
                },
                {
                    "event_id": "event-assign-002-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-002",
                    "node_id": "implement",
                    "role": "coder",
                },
            ],
        }
    )

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    assert gatekeeper.ready == []
    assert replay.nodes["implement"].state == "blocked"
    assert [attempt.state for attempt in replay.nodes["implement"].assignment_attempts] == [
        "superseded",
        "in_flight",
    ]
    assert replay.nodes["implement"].assignment_attempts[0].superseded_by == "assign-002"
    assert replay.nodes["implement"].emitted_events == []


def test_retry_policy_bounds_transient_recovery_and_opens_circuit() -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "codex-cli"
        ),
        workflow,
    )

    first = apply_retry_policy(
        workflow,
        ledger,
        assignment,
        _retry_record("assign-001", status="timed_out", reason="timeout"),
    )
    second_assignment = replace(
        assignment, assignment_id=first.event["attempt_id"]
    )
    second = apply_retry_policy(
        workflow,
        first.ledger,
        second_assignment,
        _retry_record(second_assignment.assignment_id, status="timed_out", reason="timeout"),
    )
    third_assignment = replace(
        assignment, assignment_id=second.event["attempt_id"]
    )
    third = apply_retry_policy(
        workflow,
        second.ledger,
        third_assignment,
        _retry_record(third_assignment.assignment_id, status="timed_out", reason="timeout"),
    )

    assert first.action == second.action == "retry_scheduled"
    assert first.event["attempt_id"] == "assign-001:attempt-002"
    assert second.event["budget_snapshot"]["tokens_used"] == 2000
    first_attempts = replay_workflow(workflow, first.ledger).nodes[
        "implement"
    ].assignment_attempts
    assert [attempt.state for attempt in first_attempts] == [
        "rejected",
        "retry_scheduled",
    ]
    assert not any(
        reason.code == "assignment_in_flight"
        for reason in replay_workflow(workflow, first.ledger).nodes[
            "implement"
        ].blocked_reasons
    )
    assert third.action == "circuit_opened"
    assert third.event["reason"] == "attempt_budget_exhausted"
    assert third.event["terminal_state"] == "needs_review"
    assert evaluate_gatekeeper(workflow, third.ledger).ready == []


def test_retry_policy_opens_repeated_deterministic_fingerprint() -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "codex-cli"
        ),
        workflow,
    )
    first = apply_retry_policy(
        workflow,
        ledger,
        assignment,
        _retry_record("assign-001"),
        changed_evidence_refs=["artifact-failure"],
        repair_strategy="repair-v1",
    )
    retry_assignment = replace(
        assignment, assignment_id=first.event["attempt_id"]
    )

    repeated = apply_retry_policy(
        workflow,
        first.ledger,
        retry_assignment,
        _retry_record(retry_assignment.assignment_id),
        changed_evidence_refs=["artifact-failure"],
        repair_strategy="repair-v1",
    )

    assert repeated.action == "circuit_opened"
    assert repeated.event["reason"] == "repeated_deterministic_fingerprint"
    assert repeated.event["failure_fingerprint"] == first.event["failure_fingerprint"]
    reasons = replay_workflow(workflow, repeated.ledger).nodes["implement"].blocked_reasons
    assert any(reason.code == "needs_review" for reason in reasons)


def test_retry_policy_requires_repair_or_reroute_evidence() -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "codex-cli"
        ),
        workflow,
    )

    denied = apply_retry_policy(
        workflow,
        ledger,
        assignment,
        _retry_record("assign-001", status="completed", verification_status="failed"),
    )
    rerouted = apply_retry_policy(
        workflow,
        ledger,
        assignment,
        _retry_record("assign-001", reason="capability_model_mismatch"),
        error_code="capability_model_mismatch",
        routing_decision_id="routing-002",
        strategy_id="larger-model",
    )

    assert denied.event["reason"] == "repair_evidence_or_strategy_missing"
    assert rerouted.action == "retry_scheduled"
    assert rerouted.failure_class == "capability_mismatch"


def test_retry_policy_stops_structural_failure_and_token_exhaustion() -> None:
    workflow = _workflow()
    ledger = replace(_empty_ledger(), ledger_version=3)
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow, assignment, "session-001", "codex-cli"
        ),
        workflow,
    )

    structural = apply_retry_policy(
        workflow,
        ledger,
        assignment,
        _retry_record(
            "assign-001",
            status="completed",
            verification_status="workflow_structure",
            control_intents=[_mutation_intent()],
        ),
    )
    exhausted = apply_retry_policy(
        workflow,
        ledger,
        assignment,
        _retry_record(
            "assign-001", status="timed_out", reason="timeout", total_tokens=20_000
        ),
    )

    assert structural.failure_class == "workflow_structure"
    assert structural.event["terminal_state"] == "needs_replan"
    assert exhausted.event["reason"] == "token_budget_exhausted"
    assert classify_session_failure(
        _retry_record("assign-001", status="completed", extraction_status="wrapper_failed_to_extract")
    ) == "malformed_output_contract"

    revised_assignment = replace(assignment, assignment_id="assign-002")
    revised_ledger = append_ledger_event(
        structural.ledger,
        build_assignment_created_event(
            workflow, revised_assignment, "session-002", "codex-cli"
        ),
        workflow,
    )
    revised_reasons = replay_workflow(workflow, revised_ledger).nodes[
        "implement"
    ].blocked_reasons
    assert not any(reason.code == "needs_replan" for reason in revised_reasons)


def test_cli_session_run_and_cancel(tmp_path, capsys) -> None:
    session_path = tmp_path / "session.yaml"
    mission_path = Path("examples/missions/demo/mission.yaml")
    workflow_path = Path(
        "examples/missions/demo/workflows/coder_reviewer_committer.yaml"
    )
    workflow = load_workflow(workflow_path)
    assignment = export_assignment(
        workflow,
        load_ledger(Path("examples/missions/demo/ledger.yaml")),
        "implement",
        assignment_id="assign-001",
    )
    _, packet = _dispatch_fixture(workflow, assignment)
    packet_path = tmp_path / "dispatch.yaml"
    packet_path.write_text(
        yaml.safe_dump(packet.to_dict(), sort_keys=False), encoding="utf-8"
    )

    exit_code = main(
        [
            "session",
            "run",
            str(mission_path),
            str(workflow_path),
            str(packet_path),
            "--agent",
            "fake",
            "--session-id",
            "session-001",
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)
    session_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["dispatch"]["packet_id"] == "packet-001"
    assert payload["dispatch"]["assignment_id"] == "assign-001"
    assert payload["extraction"]["status"] == "synthetic"
    assert payload["result_proposal"]["assignment_id"] == "assign-001"
    degraded_report = payload["extraction"]["turn_reports"][0]
    assert degraded_report["telemetry_mode"] == "degraded"
    assert degraded_report["tool_calls_since_last_report"] == 0
    assert degraded_report["policy_compliance"]["status"] == "degraded"

    cancel_exit = main(["session", "cancel", str(session_path), "--reason", "user_cancelled"])
    updated = load_session_record(yaml.safe_load(session_path.read_text(encoding="utf-8")))
    capsys.readouterr()

    assert cancel_exit == 0
    assert updated.status == "cancelled"
    assert updated.exit["reason"] == "user_cancelled"


def test_dispatch_session_rejects_invalid_packet_before_runner(tmp_path) -> None:
    workflow = _workflow()
    assignment = export_assignment(
        workflow,
        _empty_ledger(),
        "implement",
        assignment_id="assign-dispatch-invalid",
    )
    mission, packet = _dispatch_fixture(workflow, assignment)
    invalid_packet = replace(packet, workflow_id="wrong-workflow")
    runner_called = False

    def runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("invalid dispatch reached the external runner")

    with pytest.raises(ProtocolError, match="workflow_id does not match workflow"):
        dispatch_session(
            mission,
            workflow,
            invalid_packet,
            agent_id="codex-cli",
            workdir=tmp_path,
            dispatch_packet_path=tmp_path / "dispatch.yaml",
            target_model="gpt-5",
            target_provider="openai",
            command_runner=runner,
        )

    assert runner_called is False
    assert not (tmp_path / "dispatch.yaml").exists()


def test_dispatch_session_rejects_proposed_workflow_before_runner(tmp_path) -> None:
    workflow = _workflow()
    assignment = export_assignment(
        workflow,
        _empty_ledger(),
        "implement",
        assignment_id="assign-dispatch-proposed",
    )
    mission, packet = _dispatch_fixture(workflow, assignment)
    runner_called = False

    def runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("proposed workflow reached the external runner")

    with pytest.raises(ProtocolError, match="Dispatch workflow must be accepted"):
        dispatch_session(
            mission,
            replace(workflow, status="proposed"),
            packet,
            agent_id="codex-cli",
            workdir=tmp_path,
            dispatch_packet_path=tmp_path / "dispatch.yaml",
            target_model="gpt-5",
            target_provider="openai",
            command_runner=runner,
        )

    assert runner_called is False
    assert not (tmp_path / "dispatch.yaml").exists()


def test_dispatch_session_persists_prelaunch_packet_and_reconstructs_binding(
    tmp_path,
    monkeypatch,
) -> None:
    workflow = _workflow()
    assignment = export_assignment(
        workflow,
        _empty_ledger(),
        "implement",
        assignment_id="assign-dispatch-001",
    )
    mission, packet = _dispatch_fixture(workflow, assignment)
    packet_path = tmp_path / "evidence" / "dispatch.yaml"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def runner(command, **_kwargs):
        assert packet_path.is_file()
        assert load_dispatch_packet(
            yaml.safe_load(packet_path.read_text(encoding="utf-8"))
        ).packet_id == packet.packet_id
        assert "Packet: packet-001" in _kwargs["input"]
        assert "Review constraints:" in _kwargs["input"]
        assert "Turn report policy:" in _kwargs["input"]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"type":"item.completed","timestamp":"2026-07-03T00:00:01Z",'
                '"item":{"id":"tool-001","type":"command_execution","command":"pytest -q"}}\n'
                '{"type":"item.completed","item":{"id":"item_0",'
                '"type":"agent_message","text":"status: completed\\n'
                'emitted_events:\\n  - patch_ready\\nverification:\\n  status: passed"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
            ),
            stderr="",
        )

    record = dispatch_session(
        mission,
        workflow,
        packet,
        agent_id="codex-cli",
        workdir=tmp_path,
        dispatch_packet_path=packet_path,
        timeout_seconds=17,
        sandbox_mode="workspace-write",
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-dispatch-001",
        command_runner=runner,
    )
    reconstructed_packet, reconstructed_spec = reconstruct_dispatched_session(record)

    assert record.dispatch is not None
    assert reconstructed_packet.to_dict() == packet.to_dict()
    assert reconstructed_spec.to_dict() == record.dispatch["session_spec"]
    assert reconstructed_spec.timeout_seconds == 17
    assert reconstructed_spec.target_model == "gpt-5"
    assert reconstructed_spec.target_provider == "openai"
    assert reconstructed_spec.sandbox_mode == "workspace-write"
    assert record.dispatch["review_constraints"] == packet.review_constraints
    assert record.dispatch["turn_report_policy"] == packet.turn_report_policy
    observed_report = record.extraction["turn_reports"][0]
    assert observed_report["telemetry_mode"] == "observed"
    assert observed_report["tool_calls_since_last_report"] == 1
    assert observed_report["source_event_ids"] == ["tool-001"]
    assert observed_report["observed_at"] == record.finished_at
    assert observed_report["policy_compliance"]["status"] == "violated"
    assert observed_report["policy_compliance"]["reasons"] == [
        "native_events_aggregated_after_process_exit"
    ]
    assert record.extraction["native_tool_events"][0]["native_timestamp"] == (
        "2026-07-03T00:00:01Z"
    )
    assert record.outcome_metrics["observed_tool_call_count"] == 1

    strict_ledger = append_ledger_event(
        replace(_empty_ledger(), ledger_version=2),
        build_assignment_created_event(
            workflow,
            assignment,
            record.session_id,
            record.agent_id,
        ),
        workflow,
    )
    staged = stage_session_record(workflow, strict_ledger, assignment, record)
    assert staged.ledger.event_log[-1]["event_type"] == "result_submitted"
    assert all(
        event["event_type"] != "turn_report_recorded"
        for event in staged.ledger.event_log
    )

    tampered_evidence = dict(record.dispatch)
    tampered_spec = dict(tampered_evidence["session_spec"])
    tampered_spec["assignment_id"] = "assign-other"
    tampered_evidence["session_spec"] = tampered_spec
    with pytest.raises(ProtocolError, match="assignment_id does not match packet"):
        reconstruct_dispatched_session(replace(record, dispatch=tampered_evidence))


def test_live_dispatch_cancellation_kills_process_group_and_preserves_evidence(
    tmp_path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    marker_path = tmp_path / "started.marker"
    child_pid_path = tmp_path / "child.pid"
    workflow = _workflow()
    assignment = export_assignment(
        workflow,
        _empty_ledger(),
        "implement",
        assignment_id="assign-live-cancel",
    )
    mission, packet = _dispatch_fixture(workflow, assignment, "packet-live-cancel")
    command = (
        "printf 'partial-output\\n'; "
        "printf 'partial-work\\n' > partial.txt; "
        f"printf started > {marker_path}; "
        "trap '' TERM; "
        "sleep 30 & "
        f"printf '%s' $! > {child_pid_path}; "
        "wait"
    )
    handle = start_dispatch_session(
        mission,
        workflow,
        packet,
        agent_id="shell-dummy",
        workdir=source_root,
        dispatch_packet_path=tmp_path / "dispatch.yaml",
        shell_command=command,
        session_id="session-live-cancel",
    )
    deadline = time.monotonic() + 2
    while not marker_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker_path.exists()

    assert handle.cancel("user_cancelled", grace_seconds=0.05) is True
    assert handle.cancel("duplicate_cancel", grace_seconds=0.05) is False
    assert handle.supersede("late_supersede", grace_seconds=0.05) is False
    record = handle.wait(timeout=2)

    assert record.status == "cancelled"
    assert record.exit["reason"] == "user_cancelled"
    assert record.exit["termination"] == {
        "status": "cancelled",
        "process_group": True,
        "forced": True,
    }
    assert record.result_proposal is None
    assert "partial-output" in record.native_logs["stdout"]
    assert Path(record.native_logs["stdout_path"]).is_file()
    assert Path(record.workspace["path"]).joinpath("partial.txt").is_file()
    assert record.outcome_metrics["changed_files_count"] == 1
    assert {
        (effect["type"], effect["source"], effect["verified"])
        for effect in record.audit_evidence["side_effects"]
    } == {
        ("process", "harness", True),
        ("workspace", "harness", True),
    }
    assert record.audit_evidence["decision_points"] == [
        {
            "decision_id": "decision-session-live-cancel-dispatch",
            "decision_type": "dispatch",
            "source": "harness",
            "evidence_available_at_time": [
                "dispatch_packet.routing_decision",
                "dispatch_packet.assignment",
                "dispatch.session_spec",
            ],
            "action_selected": "dispatch_agent:shell-dummy",
            "alternatives_visible": ["routing_mode:single_agent"],
            "selected_context": {
                "routing_mode": "small_dag",
                "selection_policy_version": "test-v1",
                "agent_id": "shell-dummy",
                "target_provider": None,
                "target_model": None,
            },
            "later_outcome": {
                "session_status": "cancelled",
                "exit_reason": "user_cancelled",
                "changed_files_count": 1,
                "agent_verification_status": "not_run",
            },
        }
    ]
    assert record.audit_evidence["capability_contributions"] == []
    assert {
        key: value["status"]
        for key, value in record.audit_evidence["side_effect_coverage"].items()
    } == {
        "workspace": "observed",
        "process": "observed",
        "network": "not_observed",
        "credential": "not_applicable",
        "payment": "not_observed",
    }
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)

    ledger = append_ledger_event(
        _empty_ledger(),
        build_assignment_created_event(
            workflow,
            assignment,
            record.session_id,
            record.agent_id,
        ),
        workflow,
    )
    terminal_event = build_session_terminal_event(workflow, assignment, record)
    assert terminal_event is not None
    ledger = append_ledger_event(ledger, terminal_event, workflow)
    replay = replay_workflow(workflow, ledger)
    assert replay.nodes["implement"].state == "runnable"
    assert replay.nodes["implement"].assignment_attempts[0].state == "cancelled"


def test_live_dispatch_graceful_exit_cannot_overwrite_superseded_terminal_state(
    tmp_path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    marker_path = tmp_path / "started.marker"
    workflow = _workflow()
    assignment = export_assignment(
        workflow,
        _empty_ledger(),
        "implement",
        assignment_id="assign-live-graceful-cancel",
    )
    mission, packet = _dispatch_fixture(
        workflow,
        assignment,
        "packet-live-graceful-cancel",
    )
    handle = start_dispatch_session(
        mission,
        workflow,
        packet,
        agent_id="shell-dummy",
        workdir=source_root,
        dispatch_packet_path=tmp_path / "dispatch.yaml",
        shell_command=(
            f"printf started > {marker_path}; "
            "trap 'exit 0' TERM; "
            "while true; do sleep 0.1; done"
        ),
        session_id="session-live-graceful-cancel",
    )
    deadline = time.monotonic() + 2
    while not marker_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker_path.exists()

    assert handle.supersede("replacement_dispatch", grace_seconds=1.0) is True
    record = handle.wait(timeout=2)

    assert record.status == "superseded"
    assert record.exit["reason"] == "replacement_dispatch"
    assert record.exit["termination"]["status"] == "superseded"
    assert record.exit["termination"]["forced"] is False
    assert record.result_proposal is None


def test_cli_result_package(tmp_path, capsys) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    assignment_path = tmp_path / "assignment.yaml"
    session_path = tmp_path / "session.yaml"
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    assignment_path.write_text(
        yaml.safe_dump(assignment.to_dict(), sort_keys=False),
        encoding="utf-8",
    )
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [{"artifact_id": "artifact-report", "path": "artifacts/report.md"}],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=(
                "mkdir -p artifacts\n"
                "printf 'report\\n' > artifacts/report.md\n"
                f"cat <<'EOF'\n{payload}\nEOF"
            ),
            session_id="session-001",
        ),
        assignment,
    )
    session_path.write_text(yaml.safe_dump(record.to_dict(), sort_keys=False), encoding="utf-8")

    exit_code = main(["result", "package", str(assignment_path), str(session_path)])
    packaged = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert packaged["result_id"] == "result-session-001"
    assert packaged["artifacts"][0]["path"] == "workspace/artifacts/report.md"
    assert packaged["native_log_refs"][0]["path"] == "logs/stdout.log"


def test_metrics_summarize_session_and_allow_missing_usage(tmp_path) -> None:
    session_path = tmp_path / "session.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 0,
                    "usage_confidence": "none",
                },
                "result_proposal": {
                    "assignment_id": "assign-001",
                    "agent_id": "fake",
                    "verification": {"status": "not_run"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(session_path)

    assert summary["entries"][0]["agent_id"] == "fake"
    assert summary["entries"][0]["total_tokens"] is None
    assert summary["entries"][0]["usage_source"] == "unavailable"
    assert summary["entries"][0]["usage_confidence"] == "none"
    assert summary["entries"][0]["cost_source"] == "unknown"
    assert summary["summary"][0]["missing_usage_count"] == 1


def test_metrics_summarize_includes_observed_budget_snapshot(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "single.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "workflow_mode": "single_agent",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "cost_usd": 0.01,
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (sessions_dir / "dag.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-002",
                "assignment_id": "assign-002",
                "agent_id": "fake",
                "workflow_mode": "small_dag",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 200,
                    "output_tokens": 40,
                    "total_tokens": 240,
                    "cost_usd": 0.02,
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(sessions_dir)

    assert summary["observed_budget"]["session_count"] == 2
    assert summary["observed_budget"]["completed_count"] == 2
    assert summary["observed_budget"]["total_tokens_used"] == 360
    assert summary["observed_budget"]["known_cost_usd_total"] == 0.03
    assert summary["observed_budget"]["observed_coordination_ratio"] == 0.666667
    assert summary["summary"][0]["cached_input_tokens_total"] == 0
    assert summary["summary"][0]["reasoning_output_tokens_total"] == 0


def test_metrics_summarize_includes_cache_related_provider_usage_fields(tmp_path) -> None:
    session_path = tmp_path / "session.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "effective_model": "gpt-5.4",
                "effective_provider": "openai-compatible",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "total_tokens": 150,
                    "cached_input_tokens": 20,
                    "reasoning_output_tokens": 5,
                    "usage_confidence": "high",
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(session_path)

    assert summary["entries"][0]["cached_input_tokens"] == 20
    assert summary["entries"][0]["reasoning_output_tokens"] == 5
    assert summary["entries"][0]["usage_source"] == "unavailable"
    assert summary["summary"][0]["cached_input_tokens_total"] == 20
    assert summary["summary"][0]["reasoning_output_tokens_total"] == 5


def test_metrics_summarize_ledger_results(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [
                    {
                        "event_id": "event-001",
                        "event_type": "result_submitted",
                        "result": {
                            "assignment_id": "assign-001",
                            "agent_id": "fake",
                            "status": "completed",
                            "outcome_metrics": {
                                "wall_time_ms": 500,
                                "input_tokens": 20,
                                "output_tokens": 22,
                                "total_tokens": 42,
                                "cost_usd": 0.01,
                                "changed_files_count": 0,
                                "usage_source": "agent_reported",
                                "usage_confidence": "high",
                                "cost_source": "adapter_reported",
                                "cost_confidence": "high",
                            },
                            "verification": {"status": "passed"},
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(ledger_path)

    assert summary["entries"][0]["status"] == "completed"
    assert summary["summary"][0]["completed"] == 1
    assert summary["summary"][0]["total_tokens_total"] == 42
    assert summary["entries"][0]["usage_source"] == "agent_reported"
    assert summary["entries"][0]["cost_source"] == "adapter_reported"


def test_cli_metrics_summarize(tmp_path, capsys) -> None:
    session_path = tmp_path / "session.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {"wall_time_ms": 1000, "changed_files_count": 0},
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(["metrics", "summarize", str(session_path)])
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["entries"][0]["assignment_id"] == "assign-001"
    assert payload["entries"][0]["usage_source"] == "unavailable"


def test_budget_snapshot_estimates_token_cost_and_preserves_unknowns(tmp_path) -> None:
    snapshot_path = tmp_path / "prices.yaml"
    snapshot_path.write_text(
        yaml.safe_dump(
            {
                "snapshot_id": "price-snapshot-2026-06-20",
                "provider": "mixed",
                "captured_at": "2026-06-20T00:00:00Z",
                "currency": "USD",
                "source": "manual",
                "models": {
                    "gpt-5-mini": {
                        "provider": "openai",
                        "pricing_model": "token",
                        "input_per_million": 0.5,
                        "output_per_million": 1.0,
                        "source": "manual",
                        "confidence": "high",
                    },
                    "m3": {
                        "provider": "minimax",
                        "pricing_model": "bundled_quota",
                        "source": "manual",
                        "confidence": "low",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    snapshot = load_price_snapshot(snapshot_path)

    token_estimate = estimate_cost_from_snapshot(snapshot, "gpt-5-mini", 1000, 2000)
    bundled_estimate = estimate_cost_from_snapshot(snapshot, "m3", 1000, 2000)
    unknown_estimate = estimate_cost_from_snapshot(snapshot, "unknown-model", 1000, 2000)

    assert token_estimate.cost_usd == 0.0025
    assert token_estimate.source == "manual"
    assert token_estimate.confidence == "high"
    assert bundled_estimate.cost_usd is None
    assert bundled_estimate.pricing_model == "bundled_quota"
    assert bundled_estimate.confidence == "low"
    assert unknown_estimate.cost_usd is None
    assert unknown_estimate.source == "price_snapshot_missing_model"


def test_metrics_summarize_can_apply_price_snapshot(tmp_path) -> None:
    session_path = tmp_path / "session.yaml"
    snapshot_path = tmp_path / "prices.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "effective_model": "gpt-5-mini",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 1000,
                    "output_tokens": 2000,
                    "total_tokens": 3000,
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    snapshot_path.write_text(
        yaml.safe_dump(
            {
                "snapshot_id": "price-snapshot-2026-06-20",
                "provider": "mixed",
                "captured_at": "2026-06-20T00:00:00Z",
                "currency": "USD",
                "source": "manual",
                "models": {
                    "gpt-5-mini": {
                        "provider": "openai",
                        "pricing_model": "token",
                        "input_per_million": 0.5,
                        "output_per_million": 1.0,
                        "source": "manual",
                        "confidence": "high",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(session_path, snapshot_path)

    assert summary["entries"][0]["cost_usd"] == 0.0025
    assert summary["entries"][0]["cost_source"] == "manual"
    assert summary["entries"][0]["cost_confidence"] == "high"


def test_pre_dispatch_policy_attaches_price_snapshot_attribution() -> None:
    snapshot = {
        "snapshot_id": "price-snapshot-2026-06-20",
        "source": "manual",
        "models": {
            "gpt-5-mini": {
                "pricing_model": "token",
            }
        },
    }

    decision = evaluate_pre_dispatch_policy(
        mission_budget={
            "max_total_tokens": 100000,
            "max_coordination_ratio": 0.25,
            "max_usd": 10.0,
        },
        routing_facts={
            "selected_mode": "small_dag",
            "target_model": "gpt-5-mini",
            "predicted_total_tokens": 1000,
            "predicted_cost_usd": 0.02,
            "coordination_ratio_prediction": 0.1,
        },
        observed_budget={
            "total_tokens_used": 900,
            "known_cost_usd_total": 0.018,
            "observed_coordination_ratio": 0.1,
        },
        price_snapshot=snapshot,
    )

    assert decision.price_snapshot_attribution == {
        "snapshot_id": "price-snapshot-2026-06-20",
        "snapshot_source": "manual",
        "model": "gpt-5-mini",
        "pricing_model": "token",
        "predicted_cost_usd": 0.02,
        "predicted_cost_basis": "recorded_cost",
        "actual_cost_usd": 0.018,
        "actual_cost_basis": "recorded_cost",
        "cost_delta_usd": -0.002,
    }


def test_metrics_summarize_exports_advisor_outcome_price_snapshot_attribution(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [
                    {
                        "event_id": "event-advisor-outcome-002",
                        "event_type": "advisor_outcome_recorded",
                        "mission_id": "demo",
                        "advisor_outcome_id": "advisor-outcome-002",
                        "status": "scored",
                        "source_decision_type": "routing_decision",
                        "source_decision_ref": "artifacts/decisions/routing-001.yaml",
                        "advisor_decision_ref": "artifacts/decisions/advisor-gate-002.yaml",
                        "outcome_ref": "artifacts/outcomes/advisor-outcome-002.yaml",
                        "classification": "good_skip",
                        "actual_advisor_tokens": 0,
                        "actual_total_tokens": 18400,
                        "rework_count": 0,
                        "broadcast_tokens": 1200,
                        "duplicate_context_observed": False,
                        "price_snapshot_attribution": {
                            "snapshot_id": "price-snapshot-2026-06-20",
                            "snapshot_source": "manual",
                            "model": "gpt-5-mini",
                            "pricing_model": "token",
                            "predicted_cost_usd": 0.02,
                            "predicted_cost_basis": "recorded_cost",
                            "actual_cost_usd": 0.018,
                            "actual_cost_basis": "recorded_cost",
                            "cost_delta_usd": -0.002,
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(ledger_path)

    assert summary["advisor_outcomes"] == [
        {
            "advisor_outcome_id": "advisor-outcome-002",
            "status": "scored",
            "source_decision_type": "routing_decision",
            "source_decision_ref": "artifacts/decisions/routing-001.yaml",
            "advisor_decision_ref": "artifacts/decisions/advisor-gate-002.yaml",
            "advisor_recommendation_ref": None,
            "advisor_invocation_ref": None,
            "recommendation_applied": None,
            "outcome_ref": "artifacts/outcomes/advisor-outcome-002.yaml",
            "classification": "good_skip",
            "pending_reason": None,
            "actual_advisor_tokens": 0,
            "actual_advisor_cost_usd": None,
            "actual_total_tokens": 18400,
            "rework_count": 0,
            "broadcast_tokens": 1200,
            "duplicate_context_observed": False,
            "price_snapshot_attribution": {
                "snapshot_id": "price-snapshot-2026-06-20",
                "snapshot_source": "manual",
                "model": "gpt-5-mini",
                "pricing_model": "token",
                "predicted_cost_usd": 0.02,
                "predicted_cost_basis": "recorded_cost",
                "actual_cost_usd": 0.018,
                "actual_cost_basis": "recorded_cost",
                "cost_delta_usd": -0.002,
            },
        }
    ]
    assert summary["advisor_score_summary"]["classification_counts"]["good_skip"] == 0
    assert summary["advisor_score_summary"]["insufficient_evidence_count"] == 1


def test_metrics_summarize_context_telemetry_and_fit_classification(tmp_path) -> None:
    session_path = tmp_path / "session.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "role": "coder",
                "task_type": "implementation",
                "risk_level": "medium",
                "effective_model": "gpt-5-mini",
                "workflow_mode": "small_dag",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "changed_files_count": 1,
                },
                "context_delivery": {
                    "policy_version": "context-v1",
                    "capsule_tokens": 1800,
                    "included_fact_ids": ["finding-001"],
                    "included_artifact_refs": ["artifact-report-001"],
                },
                "context_requests": [
                    {
                        "reason": "missing_test_failure_details",
                        "requested_refs": ["artifact-test-report-017"],
                        "granted_artifacts": [{"artifact_id": "artifact-test-report-017"}],
                        "denied_refs": [],
                        "unavailable_refs": [],
                        "added_tokens": 620,
                    }
                ],
                "outcome": {
                    "first_pass_success": True,
                    "rework_required": False,
                },
                "result_proposal": {
                    "review_status": "approved",
                    "verification": {"status": "passed"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(session_path)

    assert summary["entries"][0]["context_policy_version"] == "context-v1"
    assert summary["entries"][0]["context_fit_classification"] == "under_provisioned"
    assert summary["context_summary"]["total_context_requests"] == 1
    assert summary["context_summary"]["total_added_tokens"] == 620
    assert summary["context_summary"]["fit_counts"]["under_provisioned"] == 1


def test_metrics_summarize_generates_reviewable_policy_recommendations(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    common_payload = {
        "agent_id": "fake",
        "role": "coder",
        "task_type": "implementation",
        "risk_level": "medium",
        "effective_model": "gpt-5-mini",
        "workflow_mode": "small_dag",
        "status": "completed",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "exit": {"code": 0, "reason": "completed"},
        "native_logs": {"stdout": "", "stderr": ""},
        "diff_refs": [],
        "artifacts": [],
        "outcome_metrics": {
            "wall_time_ms": 1000,
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "changed_files_count": 1,
        },
        "context_delivery": {
            "policy_version": "context-v1",
            "capsule_tokens": 1600,
            "included_fact_ids": [],
            "included_artifact_refs": [],
        },
        "context_requests": [
            {
                "reason": "missing_patch_details",
                "requested_refs": ["artifact-patch-report"],
                "granted_artifacts": [{"artifact_id": "artifact-patch-report"}],
                "denied_refs": [],
                "unavailable_refs": [],
                "added_tokens": 400,
            }
        ],
        "outcome": {
            "first_pass_success": True,
            "rework_required": False,
        },
        "result_proposal": {
            "review_status": "approved",
            "verification": {"status": "passed"},
        },
    }
    (sessions_dir / "one.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                **common_payload,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (sessions_dir / "two.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-002",
                "assignment_id": "assign-002",
                **common_payload,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(sessions_dir)

    assert summary["context_summary"]["repeated_requested_refs"] == [
        {"ref": "artifact-patch-report", "count": 2}
    ]
    assert summary["policy_recommendations"] == [
        {
            "recommendation_type": "promote_requested_evidence",
            "policy_version": "context-v1",
            "role": "coder",
            "task_type": "implementation",
            "risk_level": "medium",
            "model": "gpt-5-mini",
            "target_ref": "artifact-patch-report",
            "request_count": 2,
            "evidence_basis": "repeated_context_requests",
            "auto_apply": False,
        }
    ]


def test_metrics_summarize_distinguishes_unavailable_from_mis_scoped(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "unavailable.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "role": "coder",
                "task_type": "implementation",
                "risk_level": "medium",
                "effective_model": "gpt-5-mini",
                "workflow_mode": "small_dag",
                "status": "blocked",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {"wall_time_ms": 1000, "changed_files_count": 0},
                "context_delivery": {"policy_version": "context-v1", "capsule_tokens": 900},
                "context_requests": [
                    {
                        "reason": "missing_payload",
                        "requested_refs": ["artifact-a"],
                        "granted_artifacts": [],
                        "denied_refs": [],
                        "unavailable_refs": [{"requested_ref": "artifact-a"}],
                        "added_tokens": 0,
                    }
                ],
                "result_proposal": {"verification": {"status": "not_run"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (sessions_dir / "mis-scoped.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-002",
                "assignment_id": "assign-002",
                "agent_id": "fake",
                "role": "coder",
                "task_type": "implementation",
                "risk_level": "medium",
                "effective_model": "gpt-5-mini",
                "workflow_mode": "small_dag",
                "status": "blocked",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {"wall_time_ms": 1000, "changed_files_count": 0},
                "context_delivery": {"policy_version": "context-v1", "capsule_tokens": 900},
                "context_requests": [
                    {
                        "reason": "wrong_branch_history",
                        "requested_refs": ["artifact-b"],
                        "granted_artifacts": [],
                        "denied_refs": [{"requested_ref": "artifact-b"}],
                        "unavailable_refs": [],
                        "added_tokens": 0,
                    }
                ],
                "result_proposal": {"verification": {"status": "not_run"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(sessions_dir)

    classifications = {
        entry["assignment_id"]: entry["context_fit_classification"]
        for entry in summary["entries"]
    }
    assert classifications == {
        "assign-001": "insufficient_evidence",
        "assign-002": "mis_scoped",
    }


def test_pre_dispatch_policy_rejects_hard_budget_limit_from_observed_usage() -> None:
    decision = evaluate_pre_dispatch_policy(
        mission_budget={
            "max_total_tokens": 300,
            "max_coordination_ratio": 0.25,
            "max_usd": 1.0,
        },
        routing_facts={
            "selected_mode": "small_dag",
            "predicted_total_tokens": 40,
            "predicted_cost_usd": 0.1,
            "coordination_ratio_prediction": 0.2,
        },
        observed_budget={
            "total_tokens_used": 280,
            "known_cost_usd_total": 0.2,
            "observed_coordination_ratio": 0.1,
        },
    )

    assert decision.decision == "reject"
    assert decision.budget_state == "hard_limit"
    assert "budget_hard_limit_tokens" in decision.triggered_rules


def test_pre_dispatch_policy_adjusts_parallel_swarm_to_review_mode() -> None:
    decision = evaluate_pre_dispatch_policy(
        mission_budget={
            "max_total_tokens": 100000,
            "max_coordination_ratio": 0.25,
            "max_usd": 10.0,
        },
        routing_facts={
            "selected_mode": "parallel_swarm",
            "risk_level": "medium",
            "shared_file_overlap": "high",
            "budget_confidence": "high",
            "coordination_ratio_prediction": 0.1,
            "merge_complexity": "low",
            "expected_wall_clock_savings": "material",
            "predicted_total_tokens": 1000,
            "predicted_cost_usd": 0.1,
        },
        observed_budget={
            "total_tokens_used": 1000,
            "known_cost_usd_total": 0.1,
            "observed_coordination_ratio": 0.2,
        },
    )

    assert decision.decision == "adjust"
    assert decision.selected_mode == "parallel_swarm"
    assert decision.recommended_mode == "single_agent_with_review"
    assert "reject_parallel_swarm_if" in decision.triggered_rules


def test_pre_dispatch_policy_adjusts_single_agent_for_review_floor() -> None:
    decision = evaluate_pre_dispatch_policy(
        mission_budget={
            "max_total_tokens": 100000,
            "max_coordination_ratio": 0.25,
            "max_usd": 10.0,
        },
        routing_facts={
            "selected_mode": "single_agent",
            "risk_level": "high",
            "predicted_total_tokens": 1000,
            "predicted_cost_usd": 0.1,
        },
        observed_budget={
            "total_tokens_used": 1000,
            "known_cost_usd_total": 0.1,
            "observed_coordination_ratio": 0.0,
        },
    )

    assert decision.decision == "adjust"
    assert decision.recommended_mode == "single_agent_with_review"
