from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

import yaml

from ..agents import (
    assess_agent_compatibility,
    assess_dispatch_readiness,
    doctor_agent,
    list_agent_compatibility,
    list_agent_specs,
)
from ..core import (
    ProtocolError,
    create_run_record,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_review_status,
    write_run_record,
)
from ..protocol import (
    append_ledger_event,
    compile_workflow,
    export_assignment,
    import_result_proposal,
    load_assignment,
    load_ledger,
    load_mission,
    load_result_proposal,
    load_workflow,
    render_assignment_prompt,
    sha256_file,
    verify_ledger_artifacts,
    write_ledger,
)
from ..runtime import (
    evaluate_gatekeeper,
    replay_workflow,
    summarize_metrics,
)
from ..runtime.sessions import (
    cancel_session_record,
    create_session_spec,
    load_session_record,
    package_session_result,
    run_session,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bureauless")
    parser.add_argument("--runs-dir", default="runs", help="Directory for YAML run records")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a YAML DAG file")
    validate_parser.add_argument("dag")

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

    workflow_parser = subparsers.add_parser("workflow", help="Workflow operations")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_compile_parser = workflow_subparsers.add_parser("compile", help="Compile a workflow YAML file")
    workflow_compile_parser.add_argument("workflow")

    ledger_parser = subparsers.add_parser("ledger", help="Ledger operations")
    ledger_subparsers = ledger_parser.add_subparsers(dest="ledger_command", required=True)
    ledger_validate_parser = ledger_subparsers.add_parser("validate", help="Validate a ledger YAML file")
    ledger_validate_parser.add_argument("ledger")
    ledger_append_parser = ledger_subparsers.add_parser("append", help="Append an event YAML file to a ledger")
    ledger_append_parser.add_argument("ledger")
    ledger_append_parser.add_argument("event")
    ledger_append_parser.add_argument("--workflow")
    ledger_replay_parser = ledger_subparsers.add_parser("replay", help="Replay workflow state from ledger events")
    ledger_replay_parser.add_argument("workflow")
    ledger_replay_parser.add_argument("ledger")

    gatekeeper_parser = subparsers.add_parser("gatekeeper", help="Gatekeeper operations")
    gatekeeper_subparsers = gatekeeper_parser.add_subparsers(dest="gatekeeper_command", required=True)
    gatekeeper_ready_parser = gatekeeper_subparsers.add_parser("ready", help="List runnable workflow nodes")
    gatekeeper_ready_parser.add_argument("workflow")
    gatekeeper_ready_parser.add_argument("ledger")

    artifact_parser = subparsers.add_parser("artifact", help="Artifact operations")
    artifact_subparsers = artifact_parser.add_subparsers(dest="artifact_command", required=True)
    artifact_verify_parser = artifact_subparsers.add_parser("verify", help="Verify ledger artifact hashes")
    artifact_verify_parser.add_argument("ledger")
    artifact_verify_parser.add_argument("--root", default=".")

    assignment_parser = subparsers.add_parser("assignment", help="Assignment operations")
    assignment_subparsers = assignment_parser.add_subparsers(dest="assignment_command", required=True)
    assignment_export_parser = assignment_subparsers.add_parser("export", help="Export a bounded assignment packet")
    assignment_export_parser.add_argument("workflow")
    assignment_export_parser.add_argument("ledger")
    assignment_export_parser.add_argument("node_id")
    assignment_export_parser.add_argument("--assignment-id")
    assignment_export_parser.add_argument("--prompt", action="store_true")
    assignment_export_parser.add_argument("--force", action="store_true")

    result_parser = subparsers.add_parser("result", help="Result proposal operations")
    result_subparsers = result_parser.add_subparsers(dest="result_command", required=True)
    result_package_parser = result_subparsers.add_parser(
        "package",
        help="Package a completed session record into an import-ready result proposal",
    )
    result_package_parser.add_argument("assignment")
    result_package_parser.add_argument("session_record")
    result_package_parser.add_argument("--artifact-root")
    result_package_parser.add_argument("--result-id")
    result_import_parser = result_subparsers.add_parser("import", help="Import a result proposal into the ledger")
    result_import_parser.add_argument("workflow")
    result_import_parser.add_argument("ledger")
    result_import_parser.add_argument("assignment")
    result_import_parser.add_argument("result")

    agent_parser = subparsers.add_parser("agent", help="Agent runtime operations")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)
    agent_subparsers.add_parser("list", help="List supported agent runtimes")
    agent_doctor_parser = agent_subparsers.add_parser("doctor", help="Inspect an agent runtime control surface")
    agent_doctor_parser.add_argument("agent_id")
    agent_matrix_parser = agent_subparsers.add_parser(
        "matrix",
        help="Summarize agent compatibility for semi-automatic runtime control",
    )
    agent_matrix_parser.add_argument("agent_id", nargs="?")
    agent_readiness_parser = agent_subparsers.add_parser(
        "readiness",
        help="Evaluate dispatch readiness for an agent against a workspace and isolation mode",
    )
    agent_readiness_parser.add_argument("agent_id")
    agent_readiness_parser.add_argument("--workdir", default=".")
    agent_readiness_parser.add_argument("--isolation-mode", choices=["copy", "worktree"], default="copy")

    session_parser = subparsers.add_parser("session", help="Session runtime operations")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    session_run_parser = session_subparsers.add_parser("run", help="Run an assignment in a local session wrapper")
    session_run_parser.add_argument("assignment")
    session_run_parser.add_argument("--agent", required=True, choices=["fake", "shell-dummy"])
    session_run_parser.add_argument("--workdir", default=".")
    session_run_parser.add_argument("--timeout-seconds", type=float, default=30.0)
    session_run_parser.add_argument("--isolation-mode", choices=["copy", "worktree"], default="copy")
    session_run_parser.add_argument("--cleanup-policy", default="retain_session_root")
    session_run_parser.add_argument("--dry-run", action="store_true")
    session_run_parser.add_argument("--shell-command")
    session_run_parser.add_argument("--session-id")
    session_cancel_parser = session_subparsers.add_parser("cancel", help="Mark a session record as cancelled")
    session_cancel_parser.add_argument("session_record")
    session_cancel_parser.add_argument("--reason", default="cancelled")

    metrics_parser = subparsers.add_parser("metrics", help="Outcome metrics operations")
    metrics_subparsers = metrics_parser.add_subparsers(dest="metrics_command", required=True)
    metrics_summarize_parser = metrics_subparsers.add_parser("summarize", help="Summarize session or ledger metrics")
    metrics_summarize_parser.add_argument("path")
    metrics_summarize_parser.add_argument("--price-snapshot")

    ready_parser = subparsers.add_parser("ready", help="List ready task nodes from a YAML DAG")
    ready_parser.add_argument("dag")

    prompt_parser = subparsers.add_parser("prompt", help="Render a task prompt from a YAML DAG")
    prompt_parser.add_argument("dag")
    prompt_parser.add_argument("task_id")

    record_parser = subparsers.add_parser("record", help="Write a YAML run record")
    record_parser.add_argument("dag")
    record_parser.add_argument("task_id")
    record_parser.add_argument("--model", required=True)
    record_parser.add_argument("--status", required=True)
    record_parser.add_argument("--input-commit")
    record_parser.add_argument("--output-commit")
    record_parser.add_argument("--changed-file", action="append", default=[])
    record_parser.add_argument("--verification")
    record_parser.add_argument("--review-status")
    record_parser.add_argument("--notes")

    review_parser = subparsers.add_parser("review", help="Update a run review status")
    review_parser.add_argument("dag")
    review_parser.add_argument("task_id")
    review_parser.add_argument("--status", required=True)
    review_parser.add_argument("--run-id")

    args = parser.parse_args(argv)
    runs_dir = Path(args.runs_dir)

    try:
        if args.command == "validate":
            dag = load_dag(Path(args.dag))
            print(f"valid: {dag.project} ({len(dag.nodes)} nodes)")
            return 0

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

        if args.command == "workflow" and args.workflow_command == "compile":
            workflow = load_workflow(Path(args.workflow))
            result = compile_workflow(workflow)
            if result.ok:
                print(f"compiled: {workflow.workflow_id}")
                return 0
            for error in result.errors:
                location = f" node={error.node_id}" if error.node_id else ""
                print(f"{error.code}{location}: {error.message}", file=sys.stderr)
            return 1

        if args.command == "ledger" and args.ledger_command == "validate":
            ledger = load_ledger(Path(args.ledger))
            print(f"valid: {ledger.mission_id} ({len(ledger.event_log)} events)")
            return 0

        if args.command == "ledger" and args.ledger_command == "append":
            ledger_path = Path(args.ledger)
            ledger = load_ledger(ledger_path)
            workflow = load_workflow(Path(args.workflow)) if args.workflow else None
            event = _load_yaml_event(Path(args.event))
            updated = append_ledger_event(ledger, event, workflow)
            write_ledger(ledger_path, updated)
            print(f"appended: {event['event_id']}")
            return 0

        if args.command == "ledger" and args.ledger_command == "replay":
            workflow = load_workflow(Path(args.workflow))
            ledger = load_ledger(Path(args.ledger))
            print(yaml.safe_dump(replay_workflow(workflow, ledger).to_dict(), sort_keys=False))
            return 0

        if args.command == "gatekeeper" and args.gatekeeper_command == "ready":
            workflow = load_workflow(Path(args.workflow))
            ledger = load_ledger(Path(args.ledger))
            result = evaluate_gatekeeper(workflow, ledger)
            for node_id in result.ready:
                print(node_id)
            return 0

        if args.command == "artifact" and args.artifact_command == "verify":
            ledger = load_ledger(Path(args.ledger))
            results = verify_ledger_artifacts(ledger, Path(args.root))
            print(yaml.safe_dump([result.to_dict() for result in results], sort_keys=False))
            return 0

        if args.command == "assignment" and args.assignment_command == "export":
            workflow = load_workflow(Path(args.workflow))
            ledger = load_ledger(Path(args.ledger))
            assignment = export_assignment(
                workflow=workflow,
                ledger=ledger,
                node_id=args.node_id,
                assignment_id=args.assignment_id,
                force=args.force,
            )
            if args.prompt:
                print(render_assignment_prompt(assignment))
            else:
                print(yaml.safe_dump(assignment.to_dict(), sort_keys=False))
            return 0

        if args.command == "result" and args.result_command == "import":
            ledger_path = Path(args.ledger)
            workflow = load_workflow(Path(args.workflow))
            ledger = load_ledger(ledger_path)
            assignment = load_assignment(_load_yaml_mapping(Path(args.assignment), "Assignment"))
            result = load_result_proposal(_load_yaml_mapping(Path(args.result), "Result"))
            updated = import_result_proposal(workflow, ledger, assignment, result)
            write_ledger(ledger_path, updated)
            print(f"imported: {result.result_id}")
            return 0

        if args.command == "result" and args.result_command == "package":
            assignment = load_assignment(_load_yaml_mapping(Path(args.assignment), "Assignment"))
            record = load_session_record(_load_yaml_mapping(Path(args.session_record), "Session"))
            artifact_root = Path(args.artifact_root) if args.artifact_root else None
            result = package_session_result(
                record,
                assignment,
                artifact_root=artifact_root,
                result_id=args.result_id,
            )
            print(yaml.safe_dump(result.to_dict(), sort_keys=False))
            return 0

        if args.command == "agent" and args.agent_command == "list":
            print(yaml.safe_dump([spec.to_dict() for spec in list_agent_specs()], sort_keys=False))
            return 0

        if args.command == "agent" and args.agent_command == "doctor":
            print(yaml.safe_dump(doctor_agent(args.agent_id).to_dict(), sort_keys=False))
            return 0

        if args.command == "agent" and args.agent_command == "matrix":
            if args.agent_id:
                payload = assess_agent_compatibility(args.agent_id).to_dict()
            else:
                payload = [entry.to_dict() for entry in list_agent_compatibility()]
            print(yaml.safe_dump(payload, sort_keys=False))
            return 0

        if args.command == "agent" and args.agent_command == "readiness":
            payload = assess_dispatch_readiness(
                args.agent_id,
                Path(args.workdir),
                isolation_mode=args.isolation_mode,
            ).to_dict()
            print(yaml.safe_dump(payload, sort_keys=False))
            return 0

        if args.command == "session" and args.session_command == "run":
            assignment = load_assignment(_load_yaml_mapping(Path(args.assignment), "Assignment"))
            spec = create_session_spec(
                assignment=assignment,
                agent_id=args.agent,
                workdir=Path(args.workdir),
                timeout_seconds=args.timeout_seconds,
                dry_run=args.dry_run,
                isolation_mode=args.isolation_mode,
                cleanup_policy=args.cleanup_policy,
                shell_command=args.shell_command,
                session_id=args.session_id,
            )
            record = run_session(spec, assignment)
            print(yaml.safe_dump(record.to_dict(), sort_keys=False))
            return 0

        if args.command == "session" and args.session_command == "cancel":
            session_path = Path(args.session_record)
            record = load_session_record(_load_yaml_mapping(session_path, "Session"))
            cancelled = cancel_session_record(record, reason=args.reason)
            with session_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(cancelled.to_dict(), handle, sort_keys=False)
            print(f"cancelled: {cancelled.session_id}")
            return 0

        if args.command == "metrics" and args.metrics_command == "summarize":
            snapshot_path = Path(args.price_snapshot) if args.price_snapshot else None
            print(yaml.safe_dump(summarize_metrics(Path(args.path), snapshot_path), sort_keys=False))
            return 0

        if args.command == "ready":
            dag = load_dag(Path(args.dag))
            records = load_run_records(runs_dir)
            nodes = ready_nodes(dag, records)
            for node in nodes:
                print(
                    f"{node.id}\t{node.recommended_model}\t{node.risk_level}\t{node.review_gate}"
                )
            return 0

        if args.command == "prompt":
            dag = load_dag(Path(args.dag))
            print(render_prompt(dag, args.task_id))
            return 0

        if args.command == "record":
            dag = load_dag(Path(args.dag))
            record = create_run_record(
                dag=dag,
                task_id=args.task_id,
                model=args.model,
                status=args.status,
                input_commit=args.input_commit,
                output_commit=args.output_commit,
                changed_files=args.changed_file,
                verification_result=args.verification,
                review_status=args.review_status,
                notes=args.notes,
            )
            path = write_run_record(runs_dir, record)
            print(path)
            return 0

        if args.command == "review":
            dag = load_dag(Path(args.dag))
            path = update_review_status(
                dag=dag,
                runs_dir=runs_dir,
                task_id=args.task_id,
                review_status=args.status,
                run_id=args.run_id,
            )
            print(path)
            return 0
    except (OSError, ProtocolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unhandled command: {args.command}")
    return 2


def _load_yaml_event(path: Path) -> dict:
    return _load_yaml_mapping(path, "Ledger event")


def _load_yaml_mapping(path: Path, label: str) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ProtocolError(f"{label} document must be an object")
    return data


def build_demo_golden_path(workspace: Path) -> dict:
    paths = prepare_demo_workspace(workspace)
    mission_path = paths["mission"]
    workflow_path = paths["workflow"]
    ledger_path = paths["ledger"]
    assignments_dir = paths["assignments_dir"]
    results_dir = paths["results_dir"]

    implement_assignment = assignments_dir / "implement_assignment.yaml"
    review_assignment = assignments_dir / "review_assignment.yaml"
    commit_assignment = assignments_dir / "commit_assignment.yaml"

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
                "expects": {"stdout_contains": "imported: result-implement"},
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
                "expects": {"stdout_contains": "imported: result-review"},
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
                "expects": {"stdout_contains": "imported: result-commit"},
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


def prepare_demo_workspace(workspace: Path) -> dict[str, Path]:
    source_root = _repo_root() / "examples" / "missions" / "demo"
    if not source_root.exists():
        raise ProtocolError(f"Demo mission fixture root does not exist: {source_root}")

    workspace.mkdir(parents=True, exist_ok=True)
    workflows_dir = workspace / "workflows"
    results_dir = workspace / "results"
    artifacts_dir = workspace / "artifacts"
    assignments_dir = workspace / "generated" / "assignments"
    sessions_dir = workspace / "generated" / "sessions"
    packaged_results_dir = workspace / "generated" / "results"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    assignments_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    packaged_results_dir.mkdir(parents=True, exist_ok=True)

    mission_path = workspace / "mission.yaml"
    workflow_path = workflows_dir / "coder_reviewer_committer.yaml"
    ledger_path = workspace / "ledger.yaml"
    shutil.copy2(source_root / "mission.yaml", mission_path)
    shutil.copy2(source_root / "workflows" / "coder_reviewer_committer.yaml", workflow_path)
    shutil.copy2(source_root / "ledger.yaml", ledger_path)

    _write_demo_artifact(
        artifacts_dir / "implement_patch.diff",
        "--- a/src/demo.py\n+++ b/src/demo.py\n@@\n-print('old')\n+print('new')\n",
    )
    _write_demo_artifact(
        artifacts_dir / "review_report.md",
        "# Review Report\n\nPatch reviewed and approved.\n",
    )
    _write_demo_artifact(
        artifacts_dir / "commit_note.md",
        "# Commit Note\n\nCommit created after review approval.\n",
    )

    _write_demo_result(
        results_dir / "implement_result.yaml",
        result_id="result-implement",
        assignment_id="assign-implement",
        emitted_events=["patch_ready"],
        changed_files_count=1,
        artifacts=[
            _demo_artifact_payload(
                artifacts_dir / "implement_patch.diff",
                artifact_id="artifact-implement-patch",
                created_by="coder",
                source_event="event-result-implement",
            )
        ],
    )
    _write_demo_result(
        results_dir / "review_result.yaml",
        result_id="result-review",
        assignment_id="assign-review",
        emitted_events=["review_approved"],
        changed_files_count=0,
        artifacts=[
            _demo_artifact_payload(
                artifacts_dir / "review_report.md",
                artifact_id="artifact-review-report",
                created_by="reviewer",
                source_event="event-result-review",
            )
        ],
    )
    _write_demo_result(
        results_dir / "commit_result.yaml",
        result_id="result-commit",
        assignment_id="assign-commit",
        emitted_events=["commit_created"],
        changed_files_count=1,
        artifacts=[
            _demo_artifact_payload(
                artifacts_dir / "commit_note.md",
                artifact_id="artifact-commit-note",
                created_by="committer",
                source_event="event-result-commit",
            )
        ],
    )

    return {
        "mission": mission_path,
        "workflow": workflow_path,
        "ledger": ledger_path,
        "results_dir": results_dir,
        "artifacts_dir": artifacts_dir,
        "assignments_dir": assignments_dir,
        "sessions_dir": sessions_dir,
        "packaged_results_dir": packaged_results_dir,
    }


def prepare_mutation_demo_workspace(workspace: Path) -> dict[str, Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workspace / "workflow.yaml"
    ledger_path = workspace / "ledger.yaml"
    impact_report = artifacts_dir / "impact-report.md"

    _write_demo_artifact(
        impact_report,
        "# Mutation Impact\n\nThe review step needs a focused verification node.\n",
    )
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
        "ledger_version": 1,
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
                "event_id": "event-prepare-ready",
                "event_type": "patch_ready",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-prepare",
                "node_id": "prepare",
                "role": "builder",
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
                "event_id": "event-review-complete",
                "event_type": "review_complete",
                "mission_id": "mutation-e2e-demo",
                "workflow_id": "mutation-e2e-demo",
                "assignment_id": "assign-review",
                "node_id": "review",
                "role": "reviewer",
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
    with workflow_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(workflow, handle, sort_keys=False)
    with ledger_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(ledger, handle, sort_keys=False)

    return {
        "workflow": workflow_path,
        "ledger": ledger_path,
        "artifacts_dir": artifacts_dir,
    }


def _write_demo_result(
    path: Path,
    *,
    result_id: str,
    assignment_id: str,
    emitted_events: list[str],
    changed_files_count: int,
    artifacts: list[dict[str, str]],
) -> None:
    payload = {
        "result_id": result_id,
        "assignment_id": assignment_id,
        "agent_id": "manual-demo-worker",
        "status": "completed",
        "emitted_events": emitted_events,
        "artifacts": artifacts,
        "outcome_metrics": {
            "wall_time_ms": 1000,
            "changed_files_count": changed_files_count,
            "usage_confidence": "none",
        },
        "verification": {"status": "passed"},
        "native_log_refs": [],
    }
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def _write_demo_artifact(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


def _demo_artifact_payload(
    path: Path,
    *,
    artifact_id: str,
    created_by: str,
    source_event: str,
) -> dict[str, str | bool]:
    return {
        "artifact_id": artifact_id,
        "path": f"artifacts/{path.name}" if path.parent.name == "artifacts" else str(path),
        "sha256": sha256_file(path),
        "created_by": created_by,
        "source_event": source_event,
        "mutable": False,
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


if __name__ == "__main__":
    raise SystemExit(main())
