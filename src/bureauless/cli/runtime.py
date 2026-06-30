from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

from ..protocol import (
    append_ledger_event,
    compile_workflow,
    load_ledger,
    load_workflow,
    verify_ledger_artifacts,
    write_ledger,
)
from ..runtime import evaluate_gatekeeper, replay_workflow
from .common import load_yaml_event


def register(subparsers: argparse._SubParsersAction) -> None:
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


def handle(args: argparse.Namespace) -> int | None:
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
        event = load_yaml_event(Path(args.event))
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

    return None
