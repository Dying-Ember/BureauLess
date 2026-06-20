from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .core import (
    ProtocolError,
    create_run_record,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_review_status,
    write_run_record,
)
from .harness import compile_workflow, load_mission, load_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents-swarm")
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


if __name__ == "__main__":
    raise SystemExit(main())
