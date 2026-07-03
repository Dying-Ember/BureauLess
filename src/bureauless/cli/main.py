from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

import yaml

from ..application.acceptance import decide_staged_result, stage_result, stage_session_record
from ..application.demo import prepare_demo_workspace
from ..application.run_bundles import load_run_bundle, write_run_bundle, write_session_run_bundle
from ..errors import ProtocolError
from ..protocol.advisors import (
    apply_advisor_outcome,
    load_advisor_gate_decision,
    load_advisor_outcome,
)
from ..protocol.acceptance import DEFAULT_ACCEPTANCE_POLICY
from ..protocol.artifacts import sha256_file
from ..protocol.assignments import export_assignment, load_assignment
from ..protocol.dispatch import compile_dispatch_packet
from ..protocol.harness import load_ledger, load_mission, load_workflow
from ..protocol.ledger import append_ledger_event, write_ledger
from ..protocol.outcomes import load_node_outcome, node_outcome_from_session
from ..protocol.results import load_result_proposal
from ..protocol.reviews import apply_review_decision, load_review_decision
from ..protocol.routing import load_routing_decision, validate_routing_decision
from ..runtime import (
    build_scored_advisor_outcome,
    evaluate_advisor_policy,
    evaluate_gatekeeper,
    replay_workflow,
    run_advisor_invocation,
    summarize_metrics,
)
from ..runtime.sessions import (
    build_assignment_created_event,
    build_session_terminal_event,
    cancel_session_record,
    dispatch_session,
    load_session_record,
    package_session_result,
    reconstruct_dispatched_session,
    start_dispatch_session,
    CommandRunner,
)
from . import agents as agent_commands
from . import exchange as exchange_commands
from . import legacy as legacy_commands
from . import metrics as metrics_commands
from . import runtime as runtime_commands
from . import sessions as session_commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bureauless")
    parser.add_argument("--runs-dir", default="runs", help="Directory for YAML run records")
    subparsers = parser.add_subparsers(dest="command", required=True)

    legacy_commands.register(subparsers)

    mission_parser = subparsers.add_parser("mission", help="Mission operations")
    mission_subparsers = mission_parser.add_subparsers(dest="mission_command", required=True)
    mission_validate_parser = mission_subparsers.add_parser("validate", help="Validate a mission YAML file")
    mission_validate_parser.add_argument("mission")
    mission_golden_path_parser = mission_subparsers.add_parser(
        "golden-path",
        help="Prepare and print the canonical runtime milestone golden path for the demo mission",
    )
    mission_golden_path_parser.add_argument("workspace")
    mission_mutation_demo_parser = mission_subparsers.add_parser(
        "mutation-demo",
        help="Prepare an isolated controlled-mutation workbench demo",
    )
    mission_mutation_demo_parser.add_argument("workspace")
    mission_live_demo_parser = mission_subparsers.add_parser(
        "live-demo",
        help="Run the demo mission end-to-end through real session wrappers",
    )
    mission_live_demo_parser.add_argument("workspace")
    mission_live_demo_parser.add_argument("--agent", default="codex-cli")
    mission_live_demo_parser.add_argument("--target-model", required=True)
    mission_live_demo_parser.add_argument("--target-provider", required=True)
    mission_live_demo_parser.add_argument("--provider-base-url")
    mission_live_demo_parser.add_argument(
        "--provider-api-key-env",
        default="BUREAULESS_TEST_OPENAI_API_KEY",
    )
    mission_live_demo_parser.add_argument("--provider-wire-api")
    mission_live_demo_parser.add_argument("--timeout-seconds", type=float, default=120.0)
    mission_advisor_demo_parser = mission_subparsers.add_parser(
        "advisor-demo",
        help="Run deterministic advisor skip or invocation evidence",
    )
    mission_advisor_demo_parser.add_argument("workspace")
    mission_advisor_demo_parser.add_argument(
        "--scenario",
        choices=["skip", "invoke"],
        default="invoke",
    )
    mission_spine_acceptance_parser = mission_subparsers.add_parser(
        "execution-spine-acceptance",
        help="Run the deterministic Runtime M3.5 end-to-end acceptance path",
    )
    mission_spine_acceptance_parser.add_argument("workspace")

    runtime_commands.register(subparsers)
    exchange_commands.register(subparsers)
    agent_commands.register(subparsers)
    session_commands.register(subparsers)
    metrics_commands.register(subparsers)

    args = parser.parse_args(argv)
    runs_dir = Path(args.runs_dir)

    try:
        if args.command == "mission" and args.mission_command == "validate":
            mission = load_mission(Path(args.mission))
            print(f"valid: {mission.mission_id} ({mission.status})")
            return 0

        if args.command == "mission" and args.mission_command == "golden-path":
            manifest = build_demo_golden_path(Path(args.workspace))
            print(yaml.safe_dump(manifest, sort_keys=False))
            return 0

        if args.command == "mission" and args.mission_command == "mutation-demo":
            paths = prepare_mutation_demo_workspace(Path(args.workspace))
            query = (
                f"workflow_path={paths['workflow']}"
                f"&ledger_path={paths['ledger']}"
            )
            print(
                yaml.safe_dump(
                    {
                        "workspace": str(Path(args.workspace).resolve()),
                        "workflow": str(paths["workflow"]),
                        "ledger": str(paths["ledger"]),
                        "workbench_url": f"http://127.0.0.1:5173/?{query}",
                    },
                    sort_keys=False,
                )
            )
            return 0

        if args.command == "mission" and args.mission_command == "live-demo":
            manifest = run_live_demo(
                Path(args.workspace),
                agent_id=args.agent,
                target_model=args.target_model,
                target_provider=args.target_provider,
                provider_base_url=args.provider_base_url,
                provider_api_key_env=args.provider_api_key_env,
                provider_wire_api=args.provider_wire_api,
                timeout_seconds=args.timeout_seconds,
            )
            print(yaml.safe_dump(manifest, sort_keys=False))
            return 0

        if args.command == "mission" and args.mission_command == "advisor-demo":
            evidence = run_advisor_policy_demo(
                Path(args.workspace),
                scenario=args.scenario,
            )
            print(yaml.safe_dump(evidence, sort_keys=False))
            return 0

        if args.command == "mission" and args.mission_command == "execution-spine-acceptance":
            report = run_execution_spine_acceptance(Path(args.workspace))
            print(yaml.safe_dump(report, sort_keys=False))
            return 0

        for handler in (
            runtime_commands.handle,
            exchange_commands.handle,
            agent_commands.handle,
            session_commands.handle,
            metrics_commands.handle,
        ):
            result = handler(args)
            if result is not None:
                return result

        result = legacy_commands.handle(args, runs_dir)
        if result is not None:
            return result
    except (OSError, ProtocolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unhandled command: {args.command}")
    return 2


def build_demo_golden_path(workspace: Path) -> dict:
    paths = prepare_demo_workspace(workspace, ledger_version=2)
    mission_path = paths["mission"]
    workflow_path = paths["workflow"]
    ledger_path = paths["ledger"]
    assignments_dir = paths["assignments_dir"]
    results_dir = paths["results_dir"]

    implement_assignment = assignments_dir / "implement_assignment.yaml"
    review_assignment = assignments_dir / "review_assignment.yaml"
    commit_assignment = assignments_dir / "commit_assignment.yaml"
    policy_path = paths["decisions_dir"] / "golden_path_acceptance_policy.yaml"
    _write_yaml(
        policy_path,
        {
            "policy_version": "acceptance-v1-manual-golden-path",
            "review": {
                "required": False,
                "allowed_actors": ["orchestrator", "human"],
            },
            "verification": {"required_statuses": ["passed"]},
            "allow_partial_acceptance": False,
        },
    )
    outcome_paths: dict[str, Path] = {}
    for node_id, role in (
        ("implement", "coder"),
        ("review", "reviewer"),
        ("commit", "committer"),
    ):
        outcome_path = paths["outcomes_dir"] / f"{node_id}_outcome.yaml"
        outcome_paths[node_id] = outcome_path
        _write_yaml(
            outcome_path,
            {
                "outcome_id": f"outcome-{node_id}",
                "assignment_id": f"assign-{node_id}",
                "session_id": f"session-{node_id}-manual",
                "workflow_id": "coder-reviewer-committer-001",
                "node_id": node_id,
                "role": role,
                "agent_id": "manual-demo-worker",
                "status": "completed",
                "pre_state_ref": None,
                "post_state_ref": None,
                "observed_delta": {},
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "diff_refs": [],
                "outcome_metrics": {},
                "extraction": {},
            },
        )

    return {
        "milestone": "runtime-milestone-2",
        "flow_id": "demo-manual-harness-golden-path",
        "workspace": str(workspace.resolve()),
        "mission_path": str(mission_path),
        "workflow_path": str(workflow_path),
        "ledger_path": str(ledger_path),
        "results": {
            "implement": str(results_dir / "implement_result.yaml"),
            "review": str(results_dir / "review_result.yaml"),
            "commit": str(results_dir / "commit_result.yaml"),
        },
        "artifacts_root": str(paths["artifacts_dir"]),
        "steps": [
            {
                "id": "validate_mission",
                "argv": ["mission", "validate", str(mission_path)],
                "expects": {"stdout_contains": "valid: demo"},
            },
            {
                "id": "compile_workflow",
                "argv": ["workflow", "compile", str(workflow_path)],
                "expects": {"stdout_contains": "compiled: coder-reviewer-committer-001"},
            },
            {
                "id": "replay_initial_state",
                "argv": ["ledger", "replay", str(workflow_path), str(ledger_path)],
                "expects": {
                    "terminal_complete": False,
                    "node_states": {
                        "implement": "runnable",
                        "review": "blocked",
                        "commit": "blocked",
                    },
                    "blocked_refs": {
                        "review": ["patch_ready"],
                        "commit": ["patch_ready", "review_approved"],
                    },
                },
            },
            {
                "id": "ready_initial",
                "argv": ["gatekeeper", "ready", str(workflow_path), str(ledger_path)],
                "expects": {"ready": ["implement"]},
            },
            {
                "id": "export_implement_assignment",
                "argv": [
                    "assignment",
                    "export",
                    str(workflow_path),
                    str(ledger_path),
                    "implement",
                    "--assignment-id",
                    "assign-implement",
                ],
                "capture_to": str(implement_assignment),
                "expects": {
                    "assignment_id": "assign-implement",
                    "node_id": "implement",
                    "expected_events": ["patch_ready"],
                },
            },
            {
                "id": "import_implement_result",
                "argv": [
                    "result",
                    "import",
                    str(workflow_path),
                    str(ledger_path),
                    str(implement_assignment),
                    str(results_dir / "implement_result.yaml"),
                ],
                "expects": {"stdout_contains": "staged: result-implement"},
            },
            {
                "id": "accept_implement_result",
                "argv": [
                    "decision",
                    "accept-outcome",
                    str(workflow_path),
                    str(ledger_path),
                    str(implement_assignment),
                    str(results_dir / "implement_result.yaml"),
                    str(outcome_paths["implement"]),
                    "--verification-status",
                    "passed",
                    "--policy",
                    str(policy_path),
                ],
                "expects": {"stdout_contains": "disposition: accepted"},
            },
            {
                "id": "ready_after_implement",
                "argv": ["gatekeeper", "ready", str(workflow_path), str(ledger_path)],
                "expects": {"ready": ["review"]},
            },
            {
                "id": "export_review_assignment",
                "argv": [
                    "assignment",
                    "export",
                    str(workflow_path),
                    str(ledger_path),
                    "review",
                    "--assignment-id",
                    "assign-review",
                ],
                "capture_to": str(review_assignment),
                "expects": {
                    "assignment_id": "assign-review",
                    "node_id": "review",
                    "expected_events": ["review_approved"],
                },
            },
            {
                "id": "import_review_result",
                "argv": [
                    "result",
                    "import",
                    str(workflow_path),
                    str(ledger_path),
                    str(review_assignment),
                    str(results_dir / "review_result.yaml"),
                ],
                "expects": {"stdout_contains": "staged: result-review"},
            },
            {
                "id": "accept_review_result",
                "argv": [
                    "decision",
                    "accept-outcome",
                    str(workflow_path),
                    str(ledger_path),
                    str(review_assignment),
                    str(results_dir / "review_result.yaml"),
                    str(outcome_paths["review"]),
                    "--verification-status",
                    "passed",
                    "--policy",
                    str(policy_path),
                ],
                "expects": {"stdout_contains": "disposition: accepted"},
            },
            {
                "id": "ready_after_review",
                "argv": ["gatekeeper", "ready", str(workflow_path), str(ledger_path)],
                "expects": {"ready": ["commit"]},
            },
            {
                "id": "export_commit_assignment",
                "argv": [
                    "assignment",
                    "export",
                    str(workflow_path),
                    str(ledger_path),
                    "commit",
                    "--assignment-id",
                    "assign-commit",
                ],
                "capture_to": str(commit_assignment),
                "expects": {
                    "assignment_id": "assign-commit",
                    "node_id": "commit",
                    "expected_events": ["commit_created"],
                },
            },
            {
                "id": "import_commit_result",
                "argv": [
                    "result",
                    "import",
                    str(workflow_path),
                    str(ledger_path),
                    str(commit_assignment),
                    str(results_dir / "commit_result.yaml"),
                ],
                "expects": {"stdout_contains": "staged: result-commit"},
            },
            {
                "id": "accept_commit_result",
                "argv": [
                    "decision",
                    "accept-outcome",
                    str(workflow_path),
                    str(ledger_path),
                    str(commit_assignment),
                    str(results_dir / "commit_result.yaml"),
                    str(outcome_paths["commit"]),
                    "--verification-status",
                    "passed",
                    "--policy",
                    str(policy_path),
                ],
                "expects": {"stdout_contains": "disposition: accepted"},
            },
            {
                "id": "replay_final_state",
                "argv": ["ledger", "replay", str(workflow_path), str(ledger_path)],
                "expects": {
                    "terminal_complete": True,
                    "node_states": {
                        "implement": "completed",
                        "review": "completed",
                        "commit": "completed",
                    },
                },
            },
        ],
    }


def _promote_demo_workspace_snapshot(session_workspace: Path, workspace: Path) -> None:
    excluded = {".bureauless", "generated", "ledger.yaml"}
    for child in workspace.iterdir():
        if child.name in excluded:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in session_workspace.iterdir():
        if child.name in excluded:
            continue
        destination = workspace / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def run_live_demo(
    workspace: Path,
    *,
    agent_id: str,
    target_model: str,
    target_provider: str,
    provider_base_url: str | None = None,
    provider_api_key_env: str | None = None,
    provider_wire_api: str | None = None,
    timeout_seconds: float = 120.0,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    paths = prepare_demo_workspace(
        workspace,
        include_fixture_results=False,
        ledger_version=2,
    )
    workflow_path = paths["workflow"]
    ledger_path = paths["ledger"]
    assignments_dir = paths["assignments_dir"]
    sessions_dir = paths["sessions_dir"]
    results_dir = paths["packaged_results_dir"]
    capsules_dir = paths["capsules_dir"]
    outcomes_dir = paths["outcomes_dir"]
    reviews_dir = paths["reviews_dir"]
    decisions_dir = paths["decisions_dir"]
    telemetry_dir = paths["telemetry_dir"]
    artifact_root = workspace
    workflow = load_workflow(workflow_path)
    mission = load_mission(paths["mission"])

    routing_decision = _build_demo_routing_decision(workflow)
    routing_decision_path = decisions_dir / "routing_decision.yaml"
    _write_yaml(routing_decision_path, routing_decision)

    advisor_gate_decision = _build_demo_advisor_gate_decision(workflow)
    advisor_gate_decision_path = decisions_dir / "advisor_gate_decision.yaml"
    _write_yaml(advisor_gate_decision_path, advisor_gate_decision)

    node_ids = ["implement", "review", "commit"]
    steps: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    for node_id in node_ids:
        workflow = load_workflow(workflow_path)
        ledger = load_ledger(ledger_path)
        assignment_id = f"assign-{node_id}-live"
        session_id = f"session-{node_id}-live"
        result_id = f"result-{node_id}-live"

        assignment = export_assignment(
            workflow,
            ledger,
            node_id,
            assignment_id=assignment_id,
        )
        assignment_path = assignments_dir / f"{node_id}_assignment.yaml"
        with assignment_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(assignment.to_dict(), handle, sort_keys=False)
        capsule_payload = assignment.visible_context.get("context_capsule", {})
        capsule_path = capsules_dir / f"{node_id}_context_capsule.yaml"
        _write_yaml(capsule_path, capsule_payload)

        dispatch_packet = compile_dispatch_packet(
            mission,
            workflow,
            load_routing_decision(routing_decision),
            assignment,
            packet_id=f"packet-{session_id}",
        )
        dispatch_packet_path = decisions_dir / f"{node_id}_dispatch_packet.yaml"

        created_event = build_assignment_created_event(
            workflow,
            assignment,
            session_id,
            agent_id,
        )
        ledger = append_ledger_event(ledger, created_event, workflow)
        write_ledger(ledger_path, ledger)

        record = dispatch_session(
            mission,
            workflow,
            dispatch_packet,
            agent_id=agent_id,
            workdir=workspace,
            dispatch_packet_path=dispatch_packet_path,
            timeout_seconds=timeout_seconds,
            isolation_mode="copy",
            cleanup_policy="retain_session_root",
            sandbox_mode="danger-full-access" if node_id == "commit" else "workspace-write",
            target_model=target_model,
            target_provider=target_provider,
            provider_base_url=provider_base_url,
            provider_api_key_env=provider_api_key_env,
            provider_wire_api=provider_wire_api,
            session_id=session_id,
            command_runner=command_runner,
            context_ledger=ledger,
        )
        session_path = sessions_dir / f"{node_id}_session.yaml"
        telemetry_record = _attach_demo_context_telemetry(
            record.to_dict(),
            assignment=assignment,
            node_id=node_id,
        )
        _write_yaml(session_path, telemetry_record)
        context_request_path: Path | None = None
        context_resolution_path: Path | None = None
        context_entries = record.extraction.get("context_requests", [])
        if isinstance(context_entries, list) and context_entries:
            context_entry = context_entries[0]
            if isinstance(context_entry, dict):
                request_payload = context_entry.get("request")
                resolution_payload = context_entry.get("resolution")
                if isinstance(request_payload, dict):
                    context_request_path = capsules_dir / f"{node_id}_context_request.yaml"
                    _write_yaml(context_request_path, request_payload)
                if isinstance(resolution_payload, dict):
                    context_resolution_path = (
                        capsules_dir / f"{node_id}_context_resolution.yaml"
                    )
                    _write_yaml(context_resolution_path, resolution_payload)
        turn_report_payload = _build_demo_turn_report(
            assignment=assignment,
            session_record=telemetry_record,
            packaged_result={},
            node_id=node_id,
        )
        turn_report_path = telemetry_dir / f"{node_id}_turn_report.yaml"
        _write_yaml(turn_report_path, turn_report_payload)

        if record.status != "completed":
            ledger = load_ledger(ledger_path)
            terminal_event = build_session_terminal_event(
                workflow,
                assignment,
                record,
                event_id=f"event-{record.session_id}-{record.status}",
            )
            if terminal_event is not None:
                ledger = append_ledger_event(ledger, terminal_event, workflow)
                write_ledger(ledger_path, ledger)
            failure_step = {
                "node_id": node_id,
                "assignment_path": str(assignment_path),
                "context_capsule_path": str(capsule_path),
                "session_path": str(session_path),
                "turn_report_path": str(turn_report_path),
                "dispatch_packet_path": str(dispatch_packet_path),
                "record_status": record.status,
                "failure_reason": record.exit.get("reason"),
                "ready_after": [],
                "node_state_after": "blocked",
            }
            if context_request_path is not None:
                failure_step["context_request_path"] = str(context_request_path)
            if context_resolution_path is not None:
                failure_step["context_resolution_path"] = str(context_resolution_path)
            steps.append(failure_step)
            failure = {
                "node_id": node_id,
                "session_id": record.session_id,
                "status": record.status,
                "reason": record.exit.get("reason"),
                "session_path": str(session_path),
            }
            break

        _promote_demo_workspace_snapshot(Path(record.workspace["path"]), workspace)

        packaged = package_session_result(
            record,
            assignment,
            artifact_root=artifact_root,
            result_id=result_id,
        )
        result_path = results_dir / f"{node_id}_result.yaml"
        _write_yaml(result_path, packaged.to_dict())

        outcome = node_outcome_from_session(
            assignment,
            record.to_dict(),
            outcome_id=f"outcome-{session_id}",
        )
        outcome_path = outcomes_dir / f"{node_id}_node_outcome.yaml"
        _write_yaml(outcome_path, outcome.to_dict())

        staged = stage_result(
            workflow,
            load_ledger(ledger_path),
            assignment,
            packaged,
            outcome,
        )
        review_decision_payload = _build_demo_review_decision(
            workflow=workflow,
            assignment=assignment,
            packaged_result=packaged.to_dict(),
            node_id=node_id,
            result_id=result_id,
        )
        review_decision_path = reviews_dir / f"{node_id}_review_decision.yaml"
        _write_yaml(review_decision_path, review_decision_payload)
        reviewed = apply_review_decision(
            staged.ledger,
            load_review_decision(review_decision_payload),
            workflow=workflow,
            event_id=f"event-review-{node_id}-live",
            decision_ref=str(review_decision_path),
        )
        verification = packaged.verification
        verification_status = (
            verification.get("status")
            if isinstance(verification.get("status"), str)
            else "unknown"
        )
        accepted = decide_staged_result(
            workflow,
            reviewed,
            assignment,
            packaged,
            outcome,
            policy=DEFAULT_ACCEPTANCE_POLICY,
            verification_status=verification_status,
            review_event_id=f"event-review-{node_id}-live",
            event_id=f"event-outcome-{session_id}-decision",
            validation_rule="reviewed_verified_result_v1",
            created_at=record.finished_at,
        )
        ledger = accepted.ledger
        write_ledger(ledger_path, ledger)

        replay = replay_workflow(workflow, ledger)
        gatekeeper = evaluate_gatekeeper(workflow, ledger)
        steps.append(
            {
                "node_id": node_id,
                "assignment_path": str(assignment_path),
                "context_capsule_path": str(capsule_path),
                "context_request_path": (
                    str(context_request_path) if context_request_path else None
                ),
                "context_resolution_path": (
                    str(context_resolution_path) if context_resolution_path else None
                ),
                "session_path": str(session_path),
                "result_path": str(result_path),
                "node_outcome_path": str(outcome_path),
                "review_decision_path": str(review_decision_path),
                "turn_report_path": str(turn_report_path),
                "dispatch_packet_path": str(dispatch_packet_path),
                "record_status": record.status,
                "emitted_events": (
                    packaged.emitted_events if record.status == "completed" else []
                ),
                "outcome_event_id": f"event-outcome-{session_id}-decision",
                "review_event_id": f"event-review-{node_id}-live",
                "ready_after": gatekeeper.ready,
                "node_state_after": replay.nodes[node_id].state,
            }
        )

    workflow = load_workflow(workflow_path)
    ledger = load_ledger(ledger_path)
    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)
    metrics_summary = summarize_metrics(sessions_dir)
    metrics_summary_path = telemetry_dir / "metrics_summary.yaml"
    _write_yaml(metrics_summary_path, metrics_summary)
    observed_budget = metrics_summary.get("observed_budget", {})
    total_tokens = (
        observed_budget.get("total_tokens_used")
        if isinstance(observed_budget.get("total_tokens_used"), int)
        else 0
    )
    advisor_gate_outcome = build_scored_advisor_outcome(
        load_advisor_gate_decision(advisor_gate_decision),
        outcome_id="advisor-outcome-live-demo",
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        source_decision_ref=str(routing_decision_path.relative_to(workspace)),
        advisor_decision_ref=str(advisor_gate_decision_path.relative_to(workspace)),
        actual_total_tokens=total_tokens,
        rework_count=0,
        broadcast_tokens=0,
        duplicate_context_observed=False,
    )
    advisor_gate_outcome_path = telemetry_dir / "advisor_gate_outcome.yaml"
    _write_yaml(advisor_gate_outcome_path, advisor_gate_outcome.to_dict())
    ledger = apply_advisor_outcome(
        ledger,
        advisor_gate_outcome,
        workflow=workflow,
        outcome_ref=str(advisor_gate_outcome_path.relative_to(workspace)),
    )
    write_ledger(ledger_path, ledger)
    query = f"workflow_path={workflow_path}&ledger_path={ledger_path}"
    manifest_path = telemetry_dir / "m3_integrated_demo_manifest.yaml"
    manifest = {
        "milestone": "runtime-milestone-3",
        "flow_id": "demo-live-session-path",
        "workspace": str(workspace.resolve()),
        "mission_path": str(paths["mission"]),
        "workflow_path": str(workflow_path),
        "ledger_path": str(ledger_path),
        "agent": agent_id,
        "target_model": target_model,
        "target_provider": target_provider,
        "routing_decision_path": str(routing_decision_path),
        "advisor_gate_decision_path": str(advisor_gate_decision_path),
        "advisor_gate_outcome_path": str(advisor_gate_outcome_path),
        "metrics_summary_path": str(metrics_summary_path),
        "workbench_url": f"http://127.0.0.1:5173/?{query}",
        "steps": steps,
        "failure": failure,
        "terminal_complete": replay.terminal_complete,
        "ready": gatekeeper.ready,
        "node_states": {
            node_id: node_state.state
            for node_id, node_state in replay.nodes.items()
        },
    }
    return write_run_bundle(manifest_path, manifest)


def run_advisor_policy_demo(
    workspace: Path,
    *,
    scenario: str,
) -> dict[str, Any]:
    if scenario not in {"skip", "invoke"}:
        raise ProtocolError("Advisor demo scenario must be skip or invoke")
    paths = prepare_demo_workspace(workspace, ledger_version=2)
    workflow_path = paths["workflow"]
    decisions_dir = paths["decisions_dir"]
    telemetry_dir = paths["telemetry_dir"]
    workflow_payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(workflow_payload, dict):
        raise ProtocolError("Advisor demo workflow must be an object")
    if scenario == "invoke":
        workflow_payload["broadcast_policy"] = {"default": "full_ledger"}
    else:
        workflow_payload["mode"] = "single_agent"
        workflow_payload["roles"] = {
            "coder": {"can_emit": ["patch_ready"], "can_consume": []}
        }
        workflow_payload["events"] = {
            "patch_ready": {"producer_roles": ["coder"]}
        }
        workflow_payload["nodes"] = [
            {"id": "implement", "role": "coder", "emits": ["patch_ready"]}
        ]
        workflow_payload["gates"] = []
        workflow_payload["terminal_events"] = ["patch_ready"]
        workflow_payload["broadcast_policy"] = {"default": "filtered_delta"}
    _write_yaml(workflow_path, workflow_payload)

    workflow = load_workflow(workflow_path)
    facts = (
        {
            "node_count": len(workflow.nodes),
            "parallel_width": 1,
            "risk_level": "high",
            "high_risk_node_count": 1,
            "review_or_human_gate_count": len(workflow.gates),
            "estimated_total_tokens": 42000,
            "estimated_context_fanout_tokens": 9200,
            "advisor_expected_tokens": 3300,
            "broadcast_policy": "full_ledger",
            "commit_or_merge_action": True,
            "review_or_approval_gate_present": True,
        }
        if scenario == "invoke"
        else {
            "node_count": len(workflow.nodes),
            "parallel_width": 1,
            "risk_level": "low",
            "high_risk_node_count": 0,
            "review_or_human_gate_count": 0,
            "estimated_total_tokens": 12000,
            "broadcast_policy": "filtered_delta",
            "commit_or_merge_action": False,
        }
    )
    gate_decision = evaluate_advisor_policy(facts)
    gate_decision_path = decisions_dir / f"advisor_gate_{scenario}.yaml"
    _write_yaml(
        gate_decision_path,
        {
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "advisor_gate_decision": gate_decision.to_dict(),
        },
    )
    routing_payload = _build_demo_routing_decision(workflow)
    routing_payload["advisor_gate_decision"] = gate_decision.to_dict()
    routing_path = decisions_dir / f"routing_{scenario}.yaml"
    _write_yaml(routing_path, routing_payload)

    recommendation_path: Path | None = None
    invocation_path: Path | None = None
    disposition_path: Path | None = None
    recommendation_applied: bool | None = None
    invocation = None
    if gate_decision.invoked:
        recommendation_path = decisions_dir / "advisor_recommendation.yaml"
        invocation_path = telemetry_dir / "advisor_invocation.yaml"
        recommendation, invocation = run_advisor_invocation(
            gate_decision,
            facts,
            runner=_deterministic_advisor_fixture_runner,
            invocation_id="advisor-invocation-demo-001",
            gate_decision_ref=str(gate_decision_path.relative_to(workspace)),
            recommendation_ref=str(recommendation_path.relative_to(workspace)),
            started_at="2026-07-03T00:00:00+00:00",
        )
        _write_yaml(recommendation_path, recommendation.to_dict())
        _write_yaml(invocation_path, invocation.to_dict())
        disposition_path = decisions_dir / "advisor_recommendation_disposition.yaml"
        _write_yaml(
            disposition_path,
            {
                "decision_type": "advisor_recommendation_disposition",
                "actor": "orchestrator",
                "decision": "accept",
                "recommendation_ref": str(recommendation_path.relative_to(workspace)),
                "applied_changes": {"broadcast_policy.default": "filtered_delta"},
                "authority": "pre_dispatch_workflow_revision",
            },
        )
        workflow_payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(workflow_payload, dict):
            raise ProtocolError("Advisor demo workflow must be an object")
        workflow_payload["broadcast_policy"] = {"default": "filtered_delta"}
        _write_yaml(workflow_path, workflow_payload)
        recommendation_applied = True

    outcome = build_scored_advisor_outcome(
        gate_decision,
        outcome_id=f"advisor-outcome-{scenario}-demo",
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        source_decision_ref=str(routing_path.relative_to(workspace)),
        advisor_decision_ref=str(gate_decision_path.relative_to(workspace)),
        advisor_recommendation_ref=(
            str(recommendation_path.relative_to(workspace)) if recommendation_path else None
        ),
        advisor_invocation_ref=(
            str(invocation_path.relative_to(workspace)) if invocation_path else None
        ),
        recommendation_applied=recommendation_applied,
        invocation=invocation,
        actual_total_tokens=1480 if invocation else 12000,
        rework_count=0,
        broadcast_tokens=0,
        duplicate_context_observed=False,
    )
    outcome_path = telemetry_dir / f"advisor_outcome_{scenario}.yaml"
    _write_yaml(outcome_path, outcome.to_dict())
    ledger = apply_advisor_outcome(
        load_ledger(paths["ledger"]),
        outcome,
        workflow=load_workflow(workflow_path),
        outcome_ref=str(outcome_path.relative_to(workspace)),
    )
    write_ledger(paths["ledger"], ledger)
    return {
        "scenario": scenario,
        "invoked": gate_decision.invoked,
        "classification": outcome.classification,
        "routing_decision_path": str(routing_path),
        "advisor_gate_decision_path": str(gate_decision_path),
        "advisor_recommendation_path": str(recommendation_path) if recommendation_path else None,
        "advisor_invocation_path": str(invocation_path) if invocation_path else None,
        "advisor_recommendation_disposition_path": (
            str(disposition_path) if disposition_path else None
        ),
        "advisor_outcome_path": str(outcome_path),
        "workflow_path": str(workflow_path),
        "ledger_path": str(paths["ledger"]),
    }


def _deterministic_advisor_fixture_runner(
    decision: Any,
    facts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "recommendation": {
            "advisor": decision.advisor,
            "verdict": "revise",
            "confidence": "medium",
            "p50_tokens": 32000,
            "p90_tokens": 48000,
            "p50_cost_usd": 0.08,
            "p90_cost_usd": 0.14,
            "main_cost_drivers": ["full_ledger broadcast"],
            "main_risk_drivers": ["high-risk commit path"],
            "recommended_changes": [
                "replace full_ledger broadcast with filtered_delta before dispatch"
            ],
        },
        "telemetry_mode": "deterministic_fixture",
        "token_usage": {
            "input_tokens": 1200,
            "output_tokens": 280,
            "total_tokens": 1480,
        },
        "cost_usd": 0.0064,
        "finished_at": "2026-07-03T00:00:01+00:00",
        "capability_scope": "recommendation_only",
        "evaluated_facts": facts,
    }


def run_execution_spine_acceptance(workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    primary_root = workspace / "primary"
    paths = prepare_demo_workspace(
        primary_root,
        include_fixture_results=False,
        ledger_version=2,
    )
    mission = load_mission(paths["mission"])
    workflow = load_workflow(paths["workflow"])
    ledger = load_ledger(paths["ledger"])
    context_artifact_path = paths["artifacts_dir"] / "api-contract.md"
    context_artifact_path.write_text(
        "# API Contract\n\nPreserve the reviewed request/response boundary.\n",
        encoding="utf-8",
    )
    context_artifact = {
        "artifact_id": "artifact-api-contract",
        "path": str(context_artifact_path.relative_to(primary_root)),
        "sha256": sha256_file(context_artifact_path),
        "source_event": "event-accepted-api-contract",
        "created_by": "harness",
        "mutable": False,
    }
    ledger = replace(ledger, artifacts=[context_artifact])
    write_ledger(paths["ledger"], ledger)
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id="assign-execution-spine",
    )
    assignment = replace(assignment, artifact_refs=[context_artifact])
    assignment_path = paths["assignments_dir"] / "execution_spine_assignment.yaml"
    _write_yaml(assignment_path, assignment.to_dict())
    routing_payload = _build_demo_routing_decision(workflow)
    routing_path = paths["decisions_dir"] / "execution_spine_routing.yaml"
    _write_yaml(routing_path, routing_payload)
    packet = compile_dispatch_packet(
        mission,
        workflow,
        load_routing_decision(routing_payload),
        assignment,
        packet_id="packet-execution-spine",
    )
    packet_path = paths["decisions_dir"] / "execution_spine_dispatch.yaml"
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            "session-execution-spine",
            "codex-cli",
        ),
        workflow,
    )
    write_ledger(paths["ledger"], ledger)

    turns = 0

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal turns
        turns += 1
        prompt = kwargs["input"]
        if turns == 1:
            response = (
                "status: context_requested\n"
                "emitted_events: []\n"
                "verification:\n  status: not_run\n"
                "context_request:\n"
                "  missing_information: Need the accepted API contract.\n"
                "  requested_refs: [artifact-api-contract]\n"
                "  expected_value: Preserve the reviewed boundary.\n"
            )
            tool_id = "tool-context-request"
        else:
            if "artifact-api-contract" not in prompt:
                raise ProtocolError("Execution spine continuation omitted granted context")
            response = (
                "status: completed\n"
                "emitted_events: [patch_ready]\n"
                "verification:\n  status: passed\n"
            )
            tool_id = "tool-context-resume"
        stdout = (
            '{"type":"item.completed","timestamp":"2026-07-03T00:00:01Z",'
            f'"item":{{"id":"{tool_id}","type":"command_execution",'
            '"command":"pytest -q"}}\n'
            '{"type":"item.completed","item":{"id":"item_0",'
            '"type":"agent_message","text":'
            + json.dumps(response)
            + '}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    key_name = "BUREAULESS_EXECUTION_SPINE_FIXTURE_KEY"
    previous_key = os.environ.get(key_name)
    os.environ[key_name] = "deterministic-fixture-key"
    try:
        record = dispatch_session(
            mission,
            workflow,
            packet,
            agent_id="codex-cli",
            workdir=primary_root,
            dispatch_packet_path=packet_path,
            target_model="gpt-5",
            target_provider="openai",
            provider_api_key_env=key_name,
            session_id="session-execution-spine",
            command_runner=runner,
            context_ledger=ledger,
        )
    finally:
        if previous_key is None:
            os.environ.pop(key_name, None)
        else:
            os.environ[key_name] = previous_key

    session_path = paths["sessions_dir"] / "execution_spine_session.yaml"
    _write_yaml(session_path, record.to_dict())
    reconstructed_packet, reconstructed_spec = reconstruct_dispatched_session(record)
    bundle_path = paths["telemetry_dir"] / "execution_spine.bundle.yaml"
    bundle = write_session_run_bundle(
        bundle_path,
        mission_path=paths["mission"],
        workflow_path=paths["workflow"],
        ledger_path=paths["ledger"],
        dispatch_packet_path=packet_path,
        session_record_path=session_path,
        packet=packet,
        record=record.to_dict(),
        workspace=primary_root,
    )
    loaded_bundle = load_run_bundle(bundle_path)

    staged = stage_session_record(
        workflow,
        ledger,
        assignment,
        record,
        artifact_root=primary_root,
        result_id="result-execution-spine",
        outcome_id="outcome-execution-spine",
    )
    replay_before_acceptance = replay_workflow(workflow, staged.ledger)
    result_path = paths["packaged_results_dir"] / "execution_spine_result.yaml"
    outcome_path = paths["outcomes_dir"] / "execution_spine_outcome.yaml"
    _write_yaml(result_path, staged.result.to_dict())
    _write_yaml(outcome_path, staged.outcome.to_dict())
    review_payload = _build_demo_review_decision(
        workflow=workflow,
        assignment=assignment,
        packaged_result=staged.result.to_dict(),
        node_id="implement",
        result_id=staged.result.result_id,
    )
    review_path = paths["reviews_dir"] / "execution_spine_review.yaml"
    _write_yaml(review_path, review_payload)
    reviewed = apply_review_decision(
        staged.ledger,
        load_review_decision(review_payload),
        workflow=workflow,
        event_id="event-review-execution-spine",
        decision_ref=str(review_path),
    )
    accepted = decide_staged_result(
        workflow,
        reviewed,
        assignment,
        staged.result,
        staged.outcome,
        policy=DEFAULT_ACCEPTANCE_POLICY,
        verification_status="passed",
        review_event_id="event-review-execution-spine",
        event_id="event-outcome-execution-spine-decision",
        validation_rule="execution_spine_acceptance_v1",
        created_at=record.finished_at,
    )
    write_ledger(paths["ledger"], accepted.ledger)
    replay_after_acceptance = replay_workflow(workflow, accepted.ledger)

    cancellation_paths = prepare_demo_workspace(
        workspace / "cancellation",
        include_fixture_results=False,
        ledger_version=2,
    )
    cancellation_mission = load_mission(cancellation_paths["mission"])
    cancellation_workflow = load_workflow(cancellation_paths["workflow"])
    cancellation_ledger = load_ledger(cancellation_paths["ledger"])
    cancellation_assignment = export_assignment(
        cancellation_workflow,
        cancellation_ledger,
        "implement",
        assignment_id="assign-cancellation-probe",
    )
    cancellation_routing = load_routing_decision(
        _build_demo_routing_decision(cancellation_workflow)
    )
    cancellation_packet = compile_dispatch_packet(
        cancellation_mission,
        cancellation_workflow,
        cancellation_routing,
        cancellation_assignment,
        packet_id="packet-cancellation-probe",
    )
    cancellation_marker = workspace / "cancellation-started.marker"
    cancellation_handle = start_dispatch_session(
        cancellation_mission,
        cancellation_workflow,
        cancellation_packet,
        agent_id="shell-dummy",
        workdir=workspace / "cancellation-source",
        dispatch_packet_path=cancellation_paths["decisions_dir"] / "cancellation_dispatch.yaml",
        shell_command=(
            f"printf started > {shlex.quote(str(cancellation_marker))}; "
            "trap '' TERM; while true; do sleep 1; done"
        ),
        session_id="session-cancellation-probe",
    )
    marker_deadline = time.monotonic() + 2
    while not cancellation_marker.exists() and time.monotonic() < marker_deadline:
        time.sleep(0.01)
    if not cancellation_marker.exists():
        cancellation_handle.cancel("probe_setup_failed", grace_seconds=0.05)
        cancellation_handle.wait(timeout=2)
        raise ProtocolError("Execution spine cancellation probe did not start")
    cancellation_handle.cancel("execution_spine_probe", grace_seconds=0.05)
    cancelled = cancellation_handle.wait(timeout=2)
    cancellation_ledger = append_ledger_event(
        cancellation_ledger,
        build_assignment_created_event(
            cancellation_workflow,
            cancellation_assignment,
            cancelled.session_id,
            cancelled.agent_id,
        ),
        cancellation_workflow,
    )
    cancellation_event = build_session_terminal_event(
        cancellation_workflow,
        cancellation_assignment,
        cancelled,
        event_id="event-cancellation-probe",
    )
    if cancellation_event is None:
        raise ProtocolError("Execution spine cancellation probe lacks terminal evidence")
    cancellation_ledger = append_ledger_event(
        cancellation_ledger,
        cancellation_event,
        cancellation_workflow,
    )
    cancellation_replay = replay_workflow(cancellation_workflow, cancellation_ledger)
    cancellation_session_path = (
        cancellation_paths["sessions_dir"] / "cancellation_probe_session.yaml"
    )
    _write_yaml(cancellation_session_path, cancelled.to_dict())

    advisor_invoked = run_advisor_policy_demo(workspace / "advisor-invoked", scenario="invoke")
    advisor_skipped = run_advisor_policy_demo(workspace / "advisor-skipped", scenario="skip")
    turn_report = record.extraction.get("turn_reports", [{}])[-1]
    context_requests = record.extraction.get("context_requests", [])
    checks = {
        "dispatch_prelaunch": {
            "passed": packet_path.is_file()
            and reconstructed_packet.packet_id == packet.packet_id
            and reconstructed_spec.assignment_id == assignment.assignment_id,
            "packet_path": str(packet_path),
            "packet_sha256": record.dispatch.get("packet_sha256") if record.dispatch else None,
        },
        "bounded_context_continuation": {
            "passed": turns == 2
            and len(context_requests) == 1
            and context_requests[0].get("resumed") is True
            and context_requests[0].get("resolution", {}).get("status") == "granted",
            "context_request_count": len(context_requests),
            "continuation_turn_count": record.outcome_metrics.get("continuation_turn_count"),
        },
        "truthful_turn_report": {
            "passed": turn_report.get("telemetry_mode") == "observed"
            and turn_report.get("tool_calls_since_last_report") == 2
            and len(turn_report.get("source_event_ids", [])) == 2,
            "turn_report": turn_report,
        },
        "authoritative_acceptance": {
            "passed": replay_before_acceptance.nodes["implement"].state == "blocked"
            and any(
                reason.code == "awaiting_acceptance"
                for reason in replay_before_acceptance.nodes["implement"].blocked_reasons
            )
            and replay_after_acceptance.nodes["implement"].state == "completed"
            and accepted.accepted_event_types == ["patch_ready"],
            "decision_event_id": accepted.decision_event.get("event_id"),
            "state_before": replay_before_acceptance.nodes["implement"].state,
            "blocked_reasons_before": [
                reason.code
                for reason in replay_before_acceptance.nodes["implement"].blocked_reasons
            ],
            "state_after": replay_after_acceptance.nodes["implement"].state,
        },
        "cancellation_safety": {
            "passed": cancelled.status == "cancelled"
            and cancelled.result_proposal is None
            and cancellation_replay.nodes["implement"].state == "runnable",
            "session_path": str(cancellation_session_path),
            "forced": cancelled.exit.get("termination", {}).get("forced"),
        },
        "advisor_policy": {
            "passed": advisor_invoked["classification"] == "good_call"
            and advisor_skipped["classification"] == "good_skip",
            "invoked_outcome_path": advisor_invoked["advisor_outcome_path"],
            "skipped_outcome_path": advisor_skipped["advisor_outcome_path"],
        },
        "generic_run_bundle": {
            "passed": loaded_bundle["flow_id"] == "maintained-session-dispatch"
            and loaded_bundle["steps"][0]["context_request_path"] is not None
            and loaded_bundle["steps"][0]["result_path"] is None,
            "bundle_path": bundle["manifest_path"],
            "artifact_count": len(loaded_bundle["artifact_index"]),
        },
        "accepted_linear_replay": {
            "passed": replay_after_acceptance.nodes["review"].state == "runnable"
            and replay_after_acceptance.nodes["implement"].emitted_events
            == ["patch_ready"],
            "ready_after": evaluate_gatekeeper(workflow, accepted.ledger).ready,
        },
    }
    passed = all(check["passed"] is True for check in checks.values())
    report_path = workspace / "execution_spine_acceptance.yaml"
    report = {
        "milestone": "runtime-milestone-3.5",
        "acceptance_id": "rm35-execution-spine-v1",
        "status": "passed" if passed else "failed",
        "checks": checks,
        "artifacts": {
            "mission_path": str(paths["mission"]),
            "workflow_path": str(paths["workflow"]),
            "ledger_path": str(paths["ledger"]),
            "session_path": str(session_path),
            "run_bundle_path": bundle["manifest_path"],
            "result_path": str(result_path),
            "outcome_path": str(outcome_path),
            "review_path": str(review_path),
        },
        "deferred_findings": {
            "REX-001": "Owned by Runtime M4 mutation intake and temporal replay scope."
        },
        "report_path": str(report_path),
    }
    _write_yaml(report_path, report)
    if not passed:
        failed = [name for name, check in checks.items() if check["passed"] is not True]
        raise ProtocolError(
            "Execution spine acceptance failed checks: " + ", ".join(failed)
        )
    return report


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def _build_demo_routing_decision(workflow: Any) -> dict[str, Any]:
    return {
        "decision_type": "routing_decision",
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "selected_mode": workflow.mode,
        "selection_policy_version": "0.1",
        "triggered_rules": [
            "explicit_review_step_required",
            "explicit_commit_step_required",
        ],
        "rejected_modes": [
            {
                "mode": "single_agent",
                "rejected_because": (
                    "The demo keeps implementation, review, and commit as separate "
                    "bounded steps so replay and gate decisions remain inspectable."
                ),
            },
            {
                "mode": "single_agent_with_review",
                "rejected_because": (
                    "The commit action remains a distinct downstream node with its own "
                    "event boundary and outcome record."
                ),
            },
        ],
        "estimated_coordination_ratio": 0.18,
        "budget_confidence": "high",
        "reason": (
            "The demo workflow keeps implementation, review, and commit as separate "
            "bounded nodes so replay, review, and dispatch remain inspectable."
        ),
        "budget_reason": "The staged demo remains well within the small_dag coordination target.",
        "risk_reason": "The commit step stays explicitly gated behind the prior review outcome.",
        "advisor_gate_decision": {
            "invoked": False,
            "policy_version": "0.1",
            "reason": [
                "parallel_width < 3",
                "review_or_human_gate_count == 1",
                "estimated_total_tokens < 80000",
                "estimated_context_fanout_tokens < advisor_expected_tokens * 2",
            ],
            "decision_basis": "first_run_heuristic",
        },
    }


def _build_demo_advisor_gate_decision(workflow: Any) -> dict[str, Any]:
    return {
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "advisor_gate_decision": {
            "invoked": False,
            "policy_version": "0.1",
            "reason": [
                "parallel_width < 3",
                "review_or_human_gate_count == 1",
                "estimated_total_tokens < 80000",
                "estimated_context_fanout_tokens < advisor_expected_tokens * 2",
            ],
            "decision_basis": "first_run_heuristic",
        },
    }


def _build_demo_turn_report(
    *,
    assignment: Any,
    session_record: dict[str, Any],
    packaged_result: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    extraction = session_record.get("extraction", {})
    reports = extraction.get("turn_reports", []) if isinstance(extraction, dict) else []
    if not isinstance(reports, list) or not reports or not isinstance(reports[-1], dict):
        raise ProtocolError(
            f"Session {session_record.get('session_id')} is missing runtime turn-report evidence"
        )
    return dict(reports[-1])


def _attach_demo_context_telemetry(
    record_payload: dict[str, Any],
    *,
    assignment: Any,
    node_id: str,
) -> dict[str, Any]:
    capsule = assignment.visible_context.get("context_capsule", {})
    accepted_facts = capsule.get("accepted_facts", []) if isinstance(capsule, dict) else []
    artifact_refs = assignment.artifact_refs
    record_payload["role"] = assignment.role
    record_payload["task_type"] = node_id
    record_payload["risk_level"] = _demo_risk_level(node_id)
    record_payload["context_delivery"] = {
        "policy_version": capsule.get("policy_version", "context-v1")
        if isinstance(capsule, dict)
        else "context-v1",
        "capsule_tokens": max(
            1,
            len(yaml.safe_dump(capsule if isinstance(capsule, dict) else {}, sort_keys=True)) // 4,
        ),
        "included_fact_ids": [
            finding.get("finding_id")
            for finding in accepted_facts
            if isinstance(finding, dict) and isinstance(finding.get("finding_id"), str)
        ],
        "included_artifact_refs": [
            artifact.get("artifact_id") or artifact.get("ref") or artifact.get("path")
            for artifact in artifact_refs
            if isinstance(artifact, dict)
            and isinstance(
                artifact.get("artifact_id") or artifact.get("ref") or artifact.get("path"),
                str,
            )
        ],
        "disclosure_level": 1,
    }
    extraction = record_payload.get("extraction", {})
    record_payload["context_requests"] = (
        extraction.get("context_requests", []) if isinstance(extraction, dict) else []
    )
    record_payload["outcome"] = {
        "first_pass_success": True,
        "rework_required": False,
    }
    return record_payload


def _build_demo_review_decision(
    *,
    workflow: Any,
    assignment: Any,
    packaged_result: dict[str, Any],
    node_id: str,
    result_id: str,
) -> dict[str, Any]:
    verification = packaged_result.get("verification", {})
    verification_status = (
        verification.get("status")
        if isinstance(verification, dict) and isinstance(verification.get("status"), str)
        else "unknown"
    )
    emitted_events = packaged_result.get("emitted_events", [])
    event_summary = ", ".join(
        event for event in emitted_events if isinstance(event, str)
    ) or "no workflow events"
    evidence_refs = []
    for artifact in packaged_result.get("artifacts", []):
        if isinstance(artifact, dict) and isinstance(artifact.get("artifact_id"), str):
            evidence_refs.append(artifact["artifact_id"])
    return {
        "decision_type": "review_decision",
        "decision_id": f"review-{node_id}-live",
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "reviewed_event": f"event-{result_id}",
        "actor": "orchestrator" if node_id != "commit" else "human",
        "verdict": "approved",
        "reason": (
            f"{node_id} completed with verification status {verification_status} "
            f"and satisfied {event_summary}."
        ),
        "evidence_refs": evidence_refs,
        "accepted_findings": [
            {
                "finding_id": f"finding-{node_id}-live",
                "content": (
                    f"Node {assignment.node_id} completed through {assignment.role} and "
                    f"produced {event_summary} with verification {verification_status}."
                ),
            }
        ],
        "rejected_findings": [],
        "next_action": "continue" if node_id != "commit" else "stop",
    }


def _demo_risk_level(node_id: str) -> str:
    if node_id == "commit":
        return "high"
    if node_id == "review":
        return "medium"
    return "low"


def prepare_mutation_demo_workspace(workspace: Path) -> dict[str, Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    mission_path = workspace / "mission.yaml"
    workflow_path = workspace / "workflow.yaml"
    ledger_path = workspace / "ledger.yaml"
    impact_report = artifacts_dir / "impact-report.md"

    _write_demo_artifact(
        impact_report,
        "# Mutation Impact\n\nThe review step needs a focused verification node.\n",
    )
    mission = {
        "mission_id": "mutation-e2e-demo",
        "goal": "Verify controlled workflow mutation end to end.",
        "status": "active",
        "default_mode": "small_dag",
        "allowed_modes": ["small_dag"],
        "budget": {},
        "models": {},
        "human_gate": {},
    }
    workflow = {
        "workflow_id": "mutation-e2e-demo",
        "mission_id": "mutation-e2e-demo",
        "mode": "small_dag",
        "status": "accepted",
        "reason": "Exercise controlled workflow mutation end to end.",
        "proposed_by": "orchestrator",
        "roles": {
            "builder": {
                "can_emit": ["patch_ready", "verification_ready", "side_complete"],
                "can_consume": ["patch_ready"],
            },
            "reviewer": {
                "can_emit": ["review_complete"],
                "can_consume": ["patch_ready", "verification_ready"],
            },
        },
        "events": {
            "patch_ready": {"producer_roles": ["builder"]},
            "verification_ready": {"producer_roles": ["builder"]},
            "review_complete": {"producer_roles": ["reviewer"]},
            "side_complete": {"producer_roles": ["builder"]},
        },
        "nodes": [
            {
                "id": "prepare",
                "role": "builder",
                "waits_for": [],
                "emits": ["patch_ready"],
            },
            {
                "id": "review",
                "role": "reviewer",
                "waits_for": ["prepare.patch_ready"],
                "emits": ["review_complete"],
            },
            {
                "id": "independent",
                "role": "builder",
                "waits_for": [],
                "emits": ["side_complete"],
            },
        ],
        "gates": [],
        "terminal_events": ["review_complete", "side_complete"],
        "broadcast_policy": {"default": "filtered_delta"},
        "budget_policy": {},
    }
    proposal = {
        "proposal_id": "mutation-demo-001",
        "proposal_type": "workflow_mutation",
        "workflow_id": "mutation-e2e-demo",
        "source": {
            "assignment_id": "assign-review",
            "session_id": "session-review",
            "actor": "worker",
        },
        "reason": "discovered_missing_dependency",
        "rationale": "Review requires a focused verification result.",
        "proposed_changes": {
            "add_nodes": [
                {
                    "id": "verify",
                    "role": "builder",
                    "waits_for": ["prepare.patch_ready"],
                    "emits": ["verification_ready"],
                }
            ],
            "add_edges": [
                {
                    "from_node": "verify",
                    "to_node": "review",
                    "event": "verification_ready",
                }
            ],
            "remove_edges": [
                {
                    "from_node": "prepare",
                    "to_node": "review",
                    "event": "patch_ready",
                }
            ],
            "supersede_assignments": ["assign-review"],
        },
        "evidence_refs": ["artifact-mutation-impact"],
        "requires_approval": "human",
    }
    ledger = {
        "mission_id": "mutation-e2e-demo",
        "ledger_version": 2,
        "current_goal": "Verify controlled workflow mutation end to end.",
        "current_plan_ref": "workflow.yaml",
        "public_findings": [],
        "decisions": [],
        "risks": [],
        "artifacts": [
            {
                "artifact_id": "artifact-mutation-impact",
                "path": "artifacts/impact-report.md",
                "sha256": sha256_file(impact_report),
                "created_by": "review-worker",
                "source_event": "event-mutation-proposed",
                "mutable": False,
            }
        ],
        "broadcasts": [],
        "open_questions": [],
        "event_log": [
            {
                "event_id": "event-prepare-created",
                "event_type": "assignment_created",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-prepare",
                "node_id": "prepare",
                "role": "builder",
            },
            {
                "event_id": "event-result-prepare",
                "event_type": "result_submitted",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-prepare",
                "node_id": "prepare",
                "role": "builder",
                "agent_id": "prepare-worker",
                "result": {
                    "result_id": "result-prepare",
                    "assignment_id": "assign-prepare",
                    "agent_id": "prepare-worker",
                    "status": "completed",
                    "emitted_events": ["patch_ready"],
                    "artifacts": [],
                    "outcome_metrics": {},
                    "verification": {"status": "passed"},
                    "native_log_refs": [],
                    "mutation_proposal_refs": [],
                },
            },
            {
                "event_id": "event-outcome-prepare",
                "event_type": "node_outcome_decided",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-prepare",
                "node_id": "prepare",
                "role": "builder",
                "agent_id": "prepare-worker",
                "session_id": "session-prepare",
                "source_result_event_id": "event-result-prepare",
                "source_outcome_id": "outcome-prepare",
                "outcome_status": "completed",
                "actor": "harness",
                "disposition": "accepted",
                "accepted_event_types": ["patch_ready"],
                "acceptance_policy_version": "acceptance-v1-demo",
                "verification_status": "passed",
                "validation_rule": "fixture_verified_v1",
            },
            {
                "event_id": "event-review-created",
                "event_type": "assignment_created",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-review",
                "node_id": "review",
                "role": "reviewer",
            },
            {
                "event_id": "event-result-review",
                "event_type": "result_submitted",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-review",
                "node_id": "review",
                "role": "reviewer",
                "agent_id": "review-worker",
                "result": {
                    "result_id": "result-review",
                    "assignment_id": "assign-review",
                    "agent_id": "review-worker",
                    "status": "completed",
                    "emitted_events": ["review_complete"],
                    "artifacts": [],
                    "outcome_metrics": {},
                    "verification": {"status": "passed"},
                    "native_log_refs": [],
                    "mutation_proposal_refs": [],
                },
            },
            {
                "event_id": "event-outcome-review",
                "event_type": "node_outcome_decided",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-review",
                "node_id": "review",
                "role": "reviewer",
                "agent_id": "review-worker",
                "session_id": "session-review",
                "source_result_event_id": "event-result-review",
                "source_outcome_id": "outcome-review",
                "outcome_status": "completed",
                "actor": "harness",
                "disposition": "accepted",
                "accepted_event_types": ["review_complete"],
                "acceptance_policy_version": "acceptance-v1-demo",
                "verification_status": "passed",
                "validation_rule": "fixture_verified_v1",
            },
            {
                "event_id": "event-mutation-proposed",
                "event_type": "workflow_mutation_proposed",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "mutation_proposal": proposal,
            },
        ],
    }
    with mission_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(mission, handle, sort_keys=False)
    with workflow_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(workflow, handle, sort_keys=False)
    with ledger_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(ledger, handle, sort_keys=False)

    return {
        "mission": mission_path,
        "workflow": workflow_path,
        "ledger": ledger_path,
        "artifacts_dir": artifacts_dir,
    }


def _write_demo_artifact(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


if __name__ == "__main__":
    raise SystemExit(main())
