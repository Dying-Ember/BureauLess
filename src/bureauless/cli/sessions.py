from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from ..protocol.assignments import load_assignment
from ..protocol.harness import load_ledger, load_workflow
from ..protocol.ledger import write_ledger
from ..runtime.sessions import (
    cancel_session_record,
    create_session_spec,
    import_session_record,
    load_session_record,
    run_session,
)
from .common import load_yaml_mapping


def register(subparsers: argparse._SubParsersAction) -> None:
    session_parser = subparsers.add_parser("session", help="Session runtime operations")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    session_run_parser = session_subparsers.add_parser("run", help="Run an assignment in a local session wrapper")
    session_run_parser.add_argument("assignment")
    session_run_parser.add_argument("--agent", required=True, choices=["fake", "shell-dummy", "codex-cli"])
    session_run_parser.add_argument("--workdir", default=".")
    session_run_parser.add_argument("--timeout-seconds", type=float, default=30.0)
    session_run_parser.add_argument("--isolation-mode", choices=["copy", "worktree"], default="copy")
    session_run_parser.add_argument("--cleanup-policy", default="retain_session_root")
    session_run_parser.add_argument("--dry-run", action="store_true")
    session_run_parser.add_argument("--shell-command")
    session_run_parser.add_argument("--target-model")
    session_run_parser.add_argument("--target-provider")
    session_run_parser.add_argument("--provider-base-url")
    session_run_parser.add_argument("--provider-api-key-env")
    session_run_parser.add_argument("--provider-wire-api")
    session_run_parser.add_argument("--session-id")
    session_import_parser = session_subparsers.add_parser(
        "import",
        help="Package a completed session, import the result, and append a node outcome decision",
    )
    session_import_parser.add_argument("workflow")
    session_import_parser.add_argument("ledger")
    session_import_parser.add_argument("assignment")
    session_import_parser.add_argument("session_record")
    session_import_parser.add_argument("--artifact-root")
    session_import_parser.add_argument("--result-id")
    session_import_parser.add_argument("--outcome-id")
    session_import_parser.add_argument("--decision-event-id")
    session_import_parser.add_argument("--actor", default="harness")
    session_import_parser.add_argument(
        "--disposition",
        choices=["accepted", "partially_accepted", "rejected"],
        default="accepted",
    )
    session_import_parser.add_argument("--validation-rule")
    session_cancel_parser = session_subparsers.add_parser("cancel", help="Mark a session record as cancelled")
    session_cancel_parser.add_argument("session_record")
    session_cancel_parser.add_argument("--reason", default="cancelled")


def handle(args: argparse.Namespace) -> int | None:
    if args.command == "session" and args.session_command == "run":
        assignment = load_assignment(load_yaml_mapping(Path(args.assignment), "Assignment"))
        spec = create_session_spec(
            assignment=assignment,
            agent_id=args.agent,
            workdir=Path(args.workdir),
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
            isolation_mode=args.isolation_mode,
            cleanup_policy=args.cleanup_policy,
            shell_command=args.shell_command,
            target_model=args.target_model,
            target_provider=args.target_provider,
            provider_base_url=args.provider_base_url,
            provider_api_key_env=args.provider_api_key_env,
            provider_wire_api=args.provider_wire_api,
            session_id=args.session_id,
        )
        record = run_session(spec, assignment)
        print(yaml.safe_dump(record.to_dict(), sort_keys=False))
        return 0

    if args.command == "session" and args.session_command == "cancel":
        session_path = Path(args.session_record)
        record = load_session_record(load_yaml_mapping(session_path, "Session"))
        cancelled = cancel_session_record(record, reason=args.reason)
        with session_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(cancelled.to_dict(), handle, sort_keys=False)
        print(f"cancelled: {cancelled.session_id}")
        return 0

    if args.command == "session" and args.session_command == "import":
        workflow = load_workflow(Path(args.workflow))
        ledger_path = Path(args.ledger)
        ledger = load_ledger(ledger_path)
        assignment = load_assignment(load_yaml_mapping(Path(args.assignment), "Assignment"))
        record = load_session_record(load_yaml_mapping(Path(args.session_record), "Session"))
        artifact_root = Path(args.artifact_root) if args.artifact_root else None
        updated = import_session_record(
            workflow,
            ledger,
            assignment,
            record,
            artifact_root=artifact_root,
            result_id=args.result_id,
            outcome_id=args.outcome_id,
            decision_event_id=args.decision_event_id,
            actor=args.actor,
            disposition=args.disposition,
            validation_rule=args.validation_rule,
        )
        write_ledger(ledger_path, updated)
        print(yaml.safe_dump(updated.event_log[-2:], sort_keys=False))
        return 0

    return None
