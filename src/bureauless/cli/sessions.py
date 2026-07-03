from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from ..application.acceptance import stage_session_record
from ..application.run_bundles import write_session_run_bundle
from ..errors import ProtocolError
from ..protocol.assignments import load_assignment
from ..protocol.dispatch import load_dispatch_packet
from ..protocol.harness import load_ledger, load_mission, load_workflow
from ..protocol.ledger import require_strict_writable_ledger, write_ledger
from ..runtime.sessions import (
    cancel_session_record,
    load_session_record,
    start_dispatch_session,
)
from .common import load_yaml_mapping


def register(subparsers: argparse._SubParsersAction) -> None:
    session_parser = subparsers.add_parser("session", help="Session runtime operations")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    session_run_parser = session_subparsers.add_parser(
        "run",
        help="Validate and execute a dispatch packet in a local session wrapper",
    )
    session_run_parser.add_argument("mission")
    session_run_parser.add_argument("workflow")
    session_run_parser.add_argument("dispatch_packet")
    session_run_parser.add_argument("--ledger")
    session_run_parser.add_argument("--run-bundle")
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
    session_import_parser.add_argument("--result-path")
    session_import_parser.add_argument("--outcome-path")
    session_cancel_parser = session_subparsers.add_parser("cancel", help="Mark a session record as cancelled")
    session_cancel_parser.add_argument("session_record")
    session_cancel_parser.add_argument("--reason", default="cancelled")


def handle(args: argparse.Namespace) -> int | None:
    if args.command == "session" and args.session_command == "run":
        if args.run_bundle and not args.ledger:
            raise ProtocolError("Session run bundle generation requires --ledger")
        mission = load_mission(Path(args.mission))
        workflow = load_workflow(Path(args.workflow))
        packet_path = Path(args.dispatch_packet)
        packet = load_dispatch_packet(load_yaml_mapping(packet_path, "Dispatch packet"))
        context_ledger = load_ledger(Path(args.ledger)) if args.ledger else None
        live_session = start_dispatch_session(
            mission,
            workflow,
            packet,
            agent_id=args.agent,
            workdir=Path(args.workdir),
            dispatch_packet_path=packet_path,
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
            context_ledger=context_ledger,
        )
        try:
            record = live_session.wait()
        except KeyboardInterrupt:
            live_session.cancel("user_interrupt")
            record = live_session.wait()
        output = record.to_dict()
        if args.ledger:
            session_record_path = packet_path.with_name(f"{record.session_id}.session.yaml")
            with session_record_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(record.to_dict(), handle, sort_keys=False)
            bundle_path = (
                Path(args.run_bundle)
                if args.run_bundle
                else session_record_path.with_suffix(".bundle.yaml")
            )
            bundle = write_session_run_bundle(
                bundle_path,
                mission_path=Path(args.mission),
                workflow_path=Path(args.workflow),
                ledger_path=Path(args.ledger),
                dispatch_packet_path=packet_path,
                session_record_path=session_record_path,
                packet=packet,
                record=record.to_dict(),
                workspace=Path(args.workdir),
            )
            output["run_bundle_path"] = bundle["manifest_path"]
        print(yaml.safe_dump(output, sort_keys=False))
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
        require_strict_writable_ledger(ledger, "session import")
        assignment = load_assignment(load_yaml_mapping(Path(args.assignment), "Assignment"))
        record = load_session_record(load_yaml_mapping(Path(args.session_record), "Session"))
        artifact_root = Path(args.artifact_root) if args.artifact_root else None
        staged = stage_session_record(
            workflow,
            ledger,
            assignment,
            record,
            artifact_root=artifact_root,
            result_id=args.result_id,
            outcome_id=args.outcome_id,
        )
        result_path = (
            Path(args.result_path)
            if args.result_path
            else Path(args.session_record).with_suffix(".result.yaml")
        )
        outcome_path = (
            Path(args.outcome_path)
            if args.outcome_path
            else Path(args.session_record).with_suffix(".outcome.yaml")
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        outcome_path.parent.mkdir(parents=True, exist_ok=True)
        with result_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(staged.result.to_dict(), handle, sort_keys=False)
        with outcome_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(staged.outcome.to_dict(), handle, sort_keys=False)
        write_ledger(ledger_path, staged.ledger)
        print(
            yaml.safe_dump(
                {
                    "status": "awaiting_acceptance",
                    "result_event_id": staged.result_event_id,
                    "result_path": str(result_path),
                    "outcome_path": str(outcome_path),
                },
                sort_keys=False,
            )
        )
        return 0

    return None
