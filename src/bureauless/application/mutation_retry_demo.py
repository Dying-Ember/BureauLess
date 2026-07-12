from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import yaml

from .demo import prepare_demo_workspace
from ..errors import ProtocolError
from ..protocol.artifacts import sha256_file
from ..protocol.assignments import export_assignment, workflow_version_id
from ..protocol.dispatch import compile_dispatch_packet
from ..protocol.harness import load_ledger, load_mission, load_workflow
from ..protocol.ledger import append_ledger_event, write_ledger
from ..protocol.mutations import materialize_current_workflow, mutation_proposed_changes
from ..protocol.routing import load_routing_decision
from ..runtime.gatekeeper import evaluate_gatekeeper
from ..runtime.replay import (
    build_mutation_supersession_events,
    evaluate_assignment_impacts,
    replay_workflow,
)
from ..runtime.sessions import (
    CommandRunner,
    SessionRecord,
    apply_retry_policy,
    build_assignment_created_event,
    dispatch_session,
)
from .acceptance import stage_session_record


def run_mutation_retry_demo(
    workspace: Path,
    *,
    real_agent: bool = False,
    target_model: str | None = None,
    target_provider: str | None = None,
    provider_base_url: str | None = None,
    provider_api_key_env: str = "BUREAULESS_TEST_OPENAI_API_KEY",
    provider_wire_api: str | None = None,
    timeout_seconds: float = 120.0,
    command_runners: tuple[CommandRunner, CommandRunner] | None = None,
) -> dict[str, Any]:
    if real_agent and (not target_model or not target_provider):
        raise ProtocolError(
            "Real-agent mutation demo requires --target-model and --target-provider"
        )
    if command_runners is not None and real_agent:
        raise ProtocolError("Injected command runners cannot be combined with real_agent")

    paths = prepare_demo_workspace(
        workspace,
        include_fixture_results=False,
        ledger_version=3,
    )
    _qualify_demo_review_dependency(paths["workflow"])
    mission = load_mission(paths["mission"])
    workflow = load_workflow(paths["workflow"])
    ledger = load_ledger(paths["ledger"])
    gap_path = paths["artifacts_dir"] / "structural-gap.md"
    gap_path.write_text(
        "# Structural Gap\n\nReview requires an explicit verification dependency.\n",
        encoding="utf-8",
    )
    gap_artifact = {
        "artifact_id": "artifact-structural-gap",
        "path": gap_path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(gap_path),
        "created_by": "harness",
        "source_event": "event-rm4-demo-setup",
        "mutable": False,
    }
    ledger = replace(ledger, artifacts=[*ledger.artifacts, gap_artifact])
    ledger = write_ledger(paths["ledger"], ledger)
    initial_version = workflow_version_id(workflow, ledger)
    launch_count = 0

    fixture_runners = command_runners or (
        _codex_fixture_runner(_mutation_response()),
        _codex_fixture_runner(_verification_response()),
    )

    review_assignment = export_assignment(
        workflow,
        ledger,
        "review",
        assignment_id="assign-mutation-review",
        force=True,
    )
    review_assignment = replace(
        review_assignment,
        goal=(
            "Inspect whether review has a required verification dependency. "
            "The structural-gap artifact proves it is missing. Report "
            "workflow_structure and propose exactly this bounded repair: add a "
            "coder node named verify with no waits that emits patch_ready; replace "
            "implement.patch_ready -> review with verify.patch_ready -> review; "
            "supersede this assignment; cite artifact-structural-gap. Do not edit "
            "canonical workflow files."
        ),
    )
    review_packet_path = paths["decisions_dir"] / "mutation_review_dispatch.yaml"
    review_packet = _dispatch_packet(mission, workflow, review_assignment)
    _write_yaml(review_packet_path, review_packet.to_dict())
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            review_assignment,
            "session-mutation-review",
            "codex-cli",
        ),
        workflow,
    )
    ledger = write_ledger(paths["ledger"], ledger)

    review_record = _dispatch(
        mission,
        workflow,
        review_packet,
        workspace=workspace,
        packet_path=review_packet_path,
        session_id="session-mutation-review",
        real_agent=real_agent,
        runner=fixture_runners[0],
        target_model=target_model,
        target_provider=target_provider,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        provider_wire_api=provider_wire_api,
        timeout_seconds=timeout_seconds,
    )
    launch_count += 1
    _write_yaml(
        paths["sessions_dir"] / "mutation_review_session.yaml",
        review_record.to_dict(),
    )
    staged = stage_session_record(
        workflow,
        ledger,
        review_assignment,
        review_record,
        artifact_root=workspace,
        result_id="result-mutation-review",
        outcome_id="outcome-mutation-review",
    )
    ledger = staged.ledger
    proposal_event = next(
        (
            event
            for event in ledger.event_log
            if event.get("event_type") == "workflow_mutation_proposed"
            and event.get("source_event_id") == staged.result_event_id
        ),
        None,
    )
    if proposal_event is None:
        disposition = staged.mutation_intake_disposition or {}
        raise ProtocolError(
            "Mutation demo did not register a proposal: "
            + str(disposition.get("errors", disposition.get("status", "unknown")))
        )
    pending = replay_workflow(workflow, ledger)
    pending_gatekeeper = evaluate_gatekeeper(workflow, ledger)

    applied_changes = mutation_proposed_changes(proposal_event["mutation_proposal"])
    accepted_event = {
        "event_id": "event-accept-mutation-review",
        "event_type": "workflow_mutation_accepted",
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "source_event_id": proposal_event["event_id"],
        "actor": "orchestrator",
        "applied_changes": applied_changes,
    }
    before = materialize_current_workflow(workflow, ledger)
    ledger = append_ledger_event(ledger, accepted_event, workflow)
    after = materialize_current_workflow(workflow, ledger)
    impacts = evaluate_assignment_impacts(before, after, ledger, applied_changes)
    for event in build_mutation_supersession_events(workflow, accepted_event, impacts):
        ledger = append_ledger_event(ledger, event, workflow)
    accepted_version = workflow_version_id(after, ledger)
    ledger = write_ledger(paths["ledger"], ledger)

    verify_assignment = export_assignment(
        workflow,
        ledger,
        "verify",
        assignment_id="assign-mutation-verify",
    )
    verify_packet_path = paths["decisions_dir"] / "mutation_verify_dispatch.yaml"
    verify_packet = _dispatch_packet(mission, after, verify_assignment)
    _write_yaml(verify_packet_path, verify_packet.to_dict())
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            after,
            verify_assignment,
            "session-mutation-verify",
            "codex-cli",
        ),
        after,
    )
    verify_record = _dispatch(
        mission,
        after,
        verify_packet,
        workspace=workspace,
        packet_path=verify_packet_path,
        session_id="session-mutation-verify",
        real_agent=real_agent,
        runner=fixture_runners[1],
        target_model=target_model,
        target_provider=target_provider,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        provider_wire_api=provider_wire_api,
        timeout_seconds=timeout_seconds,
    )
    launch_count += 1
    _write_yaml(
        paths["sessions_dir"] / "mutation_verify_session.yaml",
        verify_record.to_dict(),
    )
    resumed = stage_session_record(
        workflow,
        ledger,
        verify_assignment,
        verify_record,
        artifact_root=workspace,
        result_id="result-mutation-verify",
        outcome_id="outcome-mutation-verify",
    )
    ledger = resumed.ledger

    malformed_assignment = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-malformed-intent-probe",
        force=True,
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            after,
            malformed_assignment,
            "session-malformed-intent-probe",
            "codex-cli",
        ),
        after,
    )
    malformed_payload = dict(review_record.result_proposal or {})
    malformed_payload.update(
        {
            "result_id": "result-malformed-intent-probe",
            "assignment_id": malformed_assignment.assignment_id,
            "control_intents": [
                {
                    **_mutation_response()["control_intents"][0],
                    "proposal_id": "agent-forged-canonical-id",
                }
            ],
        }
    )
    malformed_record = replace(
        review_record,
        session_id="session-malformed-intent-probe",
        assignment_id=malformed_assignment.assignment_id,
        result_proposal=malformed_payload,
    )
    workflow_before_malformed = materialize_current_workflow(workflow, ledger)
    proposal_count_before = sum(
        event.get("event_type") == "workflow_mutation_proposed"
        for event in ledger.event_log
    )
    malformed = stage_session_record(
        workflow,
        ledger,
        malformed_assignment,
        malformed_record,
        artifact_root=workspace,
        result_id="result-malformed-intent-probe",
        outcome_id="outcome-malformed-intent-probe",
    )
    ledger = malformed.ledger
    proposal_count_after = sum(
        event.get("event_type") == "workflow_mutation_proposed"
        for event in ledger.event_log
    )
    workflow_after_malformed = materialize_current_workflow(workflow, ledger)

    retry_launch_count = launch_count
    transient_assignment = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-transient-probe",
        force=True,
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            after, transient_assignment, "session-transient-probe", "codex-cli"
        ),
        workflow,
    )
    transient = apply_retry_policy(
        workflow,
        ledger,
        transient_assignment,
        _failure_record(transient_assignment.assignment_id, "timed_out", "timeout"),
    )
    ledger = transient.ledger

    deterministic_assignment = export_assignment(
        workflow,
        ledger,
        "review",
        assignment_id="assign-deterministic-probe",
        force=True,
    )
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            after,
            deterministic_assignment,
            "session-deterministic-probe",
            "codex-cli",
        ),
        workflow,
    )
    deterministic = apply_retry_policy(
        workflow,
        ledger,
        deterministic_assignment,
        _failure_record(deterministic_assignment.assignment_id, "failed", "test_failed"),
        changed_evidence_refs=["artifact-deterministic-failure"],
        repair_strategy="repair-v1",
    )
    retry_assignment = replace(
        deterministic_assignment,
        assignment_id=deterministic.event["attempt_id"],
    )
    circuit = apply_retry_policy(
        workflow,
        deterministic.ledger,
        retry_assignment,
        _failure_record(retry_assignment.assignment_id, "failed", "test_failed"),
        changed_evidence_refs=["artifact-deterministic-failure"],
        repair_strategy="repair-v1",
    )
    ledger = circuit.ledger
    ledger = write_ledger(paths["ledger"], ledger)

    superseded = any(
        event.get("event_type") == "assignment_superseded"
        and event.get("assignment_id") == review_assignment.assignment_id
        for event in ledger.event_log
    )
    checks = {
        "trusted_mutation_intake": {
            "passed": staged.mutation_intake_disposition is not None
            and staged.mutation_intake_disposition.get("status") == "registered",
            "proposal_event_id": proposal_event["event_id"],
        },
        "pending_gatekeeper": {
            "passed": pending.mutation_proposals[proposal_event["event_id"]].state
            == "pending"
            and "review" not in pending_gatekeeper.ready,
            "ready": pending_gatekeeper.ready,
        },
        "explicit_acceptance_and_version": {
            "passed": initial_version != accepted_version and "verify" in after.nodes,
            "version_before": initial_version,
            "version_after": accepted_version,
        },
        "supersession_and_resumed_dispatch": {
            "passed": superseded
            and verify_record.status == "completed"
            and launch_count == 2,
            "launch_count": launch_count,
            "resumed_assignment_id": verify_assignment.assignment_id,
        },
        "recoverable_error": {
            "passed": transient.action == "retry_scheduled",
            "attempt_id": transient.event.get("attempt_id"),
        },
        "malformed_intent_is_inert": {
            "passed": malformed.mutation_intake_disposition is not None
            and malformed.mutation_intake_disposition.get("status") == "invalid"
            and proposal_count_after == proposal_count_before
            and workflow_after_malformed == workflow_before_malformed,
            "intake_status": (
                malformed.mutation_intake_disposition or {}
            ).get("status"),
        },
        "deterministic_circuit": {
            "passed": deterministic.action == "retry_scheduled"
            and circuit.action == "circuit_opened"
            and circuit.event.get("reason") == "repeated_deterministic_fingerprint"
            and launch_count == retry_launch_count,
            "agent_turns_spent": launch_count - retry_launch_count,
        },
    }
    passed = all(check["passed"] is True for check in checks.values())
    report_path = workspace / "mutation_retry_demo.yaml"
    report = {
        "milestone": "runtime-milestone-4",
        "acceptance_id": "rm4-mutation-retry-v1",
        "mode": "real-agent" if real_agent else "deterministic-fixture",
        "status": "passed" if passed else "failed",
        "checks": checks,
        "artifacts": {
            "workflow_path": str(paths["workflow"]),
            "ledger_path": str(paths["ledger"]),
            "review_session_path": str(
                paths["sessions_dir"] / "mutation_review_session.yaml"
            ),
            "verify_session_path": str(
                paths["sessions_dir"] / "mutation_verify_session.yaml"
            ),
        },
        "report_path": str(report_path),
    }
    _write_yaml(report_path, report)
    if not passed:
        failed = [name for name, check in checks.items() if check["passed"] is not True]
        raise ProtocolError("Mutation/retry demo failed checks: " + ", ".join(failed))
    return report


def _dispatch(
    mission: Any,
    workflow: Any,
    packet: Any,
    *,
    workspace: Path,
    packet_path: Path,
    session_id: str,
    real_agent: bool,
    runner: CommandRunner,
    target_model: str | None,
    target_provider: str | None,
    provider_base_url: str | None,
    provider_api_key_env: str,
    provider_wire_api: str | None,
    timeout_seconds: float,
) -> SessionRecord:
    key_was_missing = provider_api_key_env not in os.environ
    if not real_agent and key_was_missing:
        os.environ[provider_api_key_env] = "deterministic-fixture-key"
    try:
        return dispatch_session(
            mission,
            workflow,
            packet,
            agent_id="codex-cli",
            workdir=workspace,
            dispatch_packet_path=packet_path,
            target_model=target_model or "gpt-5",
            target_provider=target_provider or "openai",
            provider_base_url=provider_base_url,
            provider_api_key_env=provider_api_key_env,
            provider_wire_api=provider_wire_api,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            command_runner=None if real_agent else runner,
        )
    finally:
        if not real_agent and key_was_missing:
            os.environ.pop(provider_api_key_env, None)


def _dispatch_packet(mission: Any, workflow: Any, assignment: Any) -> Any:
    routing = load_routing_decision(
        {
            "decision_type": "routing_decision",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "selected_mode": workflow.mode,
            "selection_policy_version": "rm4-demo-v1",
            "triggered_rules": ["maintained_mutation_retry_acceptance"],
            "rejected_modes": [
                {
                    "mode": "single_agent",
                    "rejected_because": (
                        "Mutation review and resumed verification require separate "
                        "provenance."
                    ),
                },
                {
                    "mode": "single_agent_with_review",
                    "rejected_because": (
                        "The resumed verification remains a distinct workflow node."
                    ),
                },
            ],
            "estimated_coordination_ratio": 0.1,
            "budget_confidence": "high",
            "reason": "Run the bounded Runtime M4 mutation and retry acceptance path.",
            "budget_reason": "The scenario is bounded to two agent turns.",
            "risk_reason": "Canonical mutation remains behind explicit acceptance.",
            "advisor_gate_decision": {
                "invoked": False,
                "policy_version": "0.1",
                "reason": ["bounded_acceptance_fixture"],
                "decision_basis": "maintained_demo",
            },
        }
    )
    return compile_dispatch_packet(
        mission,
        workflow,
        routing,
        assignment,
        packet_id=f"packet-{assignment.assignment_id}",
    )


def _mutation_response() -> dict[str, Any]:
    return {
        "status": "blocked",
        "emitted_events": [],
        "verification": {"status": "workflow_structure"},
        "control_intents": [
            {
                "intent_type": "workflow_mutation",
                "reason": "discovered_missing_dependency",
                "rationale": "Review requires an explicit verification step.",
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
                            "to_node": "review",
                            "event": "patch_ready",
                        }
                    ],
                    "remove_edges": [
                        {
                            "from_node": "implement",
                            "to_node": "review",
                            "event": "patch_ready",
                        }
                    ],
                    "supersede_assignments": ["assign-mutation-review"],
                },
                "evidence_refs": ["artifact-structural-gap"],
            }
        ],
    }


def _verification_response() -> dict[str, Any]:
    return {
        "status": "completed",
        "emitted_events": ["patch_ready"],
        "verification": {"status": "passed"},
    }


def _codex_fixture_runner(payload: dict[str, Any]) -> CommandRunner:
    response = yaml.safe_dump(payload, sort_keys=False)

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        stdout = (
            '{"type":"item.completed","item":{"id":"item_0",'
            '"type":"agent_message","text":'
            + json.dumps(response)
            + '}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,'
            '"output_tokens":20}}\n'
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return runner


def _failure_record(assignment_id: str, status: str, reason: str) -> SessionRecord:
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
        outcome_metrics={"total_tokens": 1000},
        extraction={"status": "failed"},
        result_proposal=None,
    )


def _qualify_demo_review_dependency(workflow_path: Path) -> None:
    payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
        raise ProtocolError("Runtime M4 demo workflow fixture is invalid")
    review = next(
        (
            node
            for node in payload["nodes"]
            if isinstance(node, dict) and node.get("id") == "review"
        ),
        None,
    )
    if review is None:
        raise ProtocolError("Runtime M4 demo workflow is missing review node")
    review["waits_for"] = {"all_of": ["implement.patch_ready"]}
    _write_yaml(workflow_path, payload)


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)
