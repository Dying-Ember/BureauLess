from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

from ..agents import doctor_agent, list_agent_specs
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

    session_parser = subparsers.add_parser("session", help="Session runtime operations")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    session_run_parser = session_subparsers.add_parser("run", help="Run an assignment in a local session wrapper")
    session_run_parser.add_argument("assignment")
    session_run_parser.add_argument("--agent", required=True, choices=["fake", "shell-dummy"])
    session_run_parser.add_argument("--workdir", default=".")
    session_run_parser.add_argument("--timeout-seconds", type=float, default=30.0)
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

        if args.command == "agent" and args.agent_command == "list":
            print(yaml.safe_dump([spec.to_dict() for spec in list_agent_specs()], sort_keys=False))
            return 0

        if args.command == "agent" and args.agent_command == "doctor":
            print(yaml.safe_dump(doctor_agent(args.agent_id).to_dict(), sort_keys=False))
            return 0

        if args.command == "session" and args.session_command == "run":
            assignment = load_assignment(_load_yaml_mapping(Path(args.assignment), "Assignment"))
            spec = create_session_spec(
                assignment=assignment,
                agent_id=args.agent,
                workdir=Path(args.workdir),
                timeout_seconds=args.timeout_seconds,
                dry_run=args.dry_run,
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


if __name__ == "__main__":
    raise SystemExit(main())
