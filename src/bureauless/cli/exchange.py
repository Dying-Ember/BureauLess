from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from ..application.acceptance import decide_staged_result
from ..protocol.acceptance import DEFAULT_ACCEPTANCE_POLICY, load_acceptance_policy
from ..protocol.advisors import apply_advisor_outcome, load_advisor_outcome
from ..protocol.assignments import export_assignment, load_assignment, render_assignment_prompt
from ..protocol.dispatch import compile_dispatch_packet, load_dispatch_packet, validate_dispatch_packet
from ..protocol.harness import load_ledger, load_mission, load_workflow
from ..protocol.ledger import require_strict_writable_ledger, write_ledger
from ..protocol.outcomes import load_node_outcome
from ..protocol.results import import_result_proposal, load_result_proposal
from ..protocol.reviews import apply_review_decision, load_review_decision
from ..protocol.routing import load_routing_decision, validate_routing_decision
from ..runtime.sessions import load_session_record, package_session_result
from .common import load_yaml_mapping


def register(subparsers: argparse._SubParsersAction) -> None:
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

    decision_parser = subparsers.add_parser("decision", help="Decision artifact operations")
    decision_subparsers = decision_parser.add_subparsers(dest="decision_command", required=True)
    decision_review_import_parser = decision_subparsers.add_parser(
        "import-review",
        help="Import a review decision artifact into the ledger",
    )
    decision_review_import_parser.add_argument("workflow")
    decision_review_import_parser.add_argument("ledger")
    decision_review_import_parser.add_argument("decision")
    decision_review_import_parser.add_argument("--decision-ref", required=True)
    decision_accept_parser = decision_subparsers.add_parser(
        "accept-outcome",
        help="Apply strict review and verification policy to a staged result",
    )
    decision_accept_parser.add_argument("workflow")
    decision_accept_parser.add_argument("ledger")
    decision_accept_parser.add_argument("assignment")
    decision_accept_parser.add_argument("result")
    decision_accept_parser.add_argument("outcome")
    decision_accept_parser.add_argument("--verification-status", required=True)
    decision_accept_parser.add_argument("--review-event-id")
    decision_accept_parser.add_argument("--policy")
    decision_accept_parser.add_argument("--accepted-event", action="append")
    decision_accept_parser.add_argument("--actor", default="harness")
    decision_accept_parser.add_argument("--event-id")
    decision_accept_parser.add_argument(
        "--validation-rule",
        default="acceptance_policy_v1",
    )
    decision_advisor_import_parser = decision_subparsers.add_parser(
        "import-advisor-outcome",
        help="Import an advisor outcome artifact into the ledger",
    )
    decision_advisor_import_parser.add_argument("workflow")
    decision_advisor_import_parser.add_argument("ledger")
    decision_advisor_import_parser.add_argument("outcome")
    decision_advisor_import_parser.add_argument("--outcome-ref", required=True)
    decision_routing_validate_parser = decision_subparsers.add_parser(
        "validate-routing",
        help="Validate a routing decision artifact against a mission and optional workflow",
    )
    decision_routing_validate_parser.add_argument("mission")
    decision_routing_validate_parser.add_argument("decision")
    decision_routing_validate_parser.add_argument("--workflow")
    decision_dispatch_compile_parser = decision_subparsers.add_parser(
        "compile-dispatch",
        help="Compile a dispatch packet from mission, workflow, routing decision, and assignment",
    )
    decision_dispatch_compile_parser.add_argument("mission")
    decision_dispatch_compile_parser.add_argument("workflow")
    decision_dispatch_compile_parser.add_argument("routing_decision")
    decision_dispatch_compile_parser.add_argument("assignment")
    decision_dispatch_compile_parser.add_argument("--packet-id", required=True)
    decision_dispatch_compile_parser.add_argument("--dispatch-packet")


def handle(args: argparse.Namespace) -> int | None:
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
        require_strict_writable_ledger(ledger, "result import")
        assignment = load_assignment(load_yaml_mapping(Path(args.assignment), "Assignment"))
        result = load_result_proposal(load_yaml_mapping(Path(args.result), "Result"))
        updated = import_result_proposal(workflow, ledger, assignment, result)
        write_ledger(ledger_path, updated)
        print(f"staged: {result.result_id}")
        return 0

    if args.command == "result" and args.result_command == "package":
        assignment = load_assignment(load_yaml_mapping(Path(args.assignment), "Assignment"))
        record = load_session_record(load_yaml_mapping(Path(args.session_record), "Session"))
        artifact_root = Path(args.artifact_root) if args.artifact_root else None
        result = package_session_result(
            record,
            assignment,
            artifact_root=artifact_root,
            result_id=args.result_id,
        )
        print(yaml.safe_dump(result.to_dict(), sort_keys=False))
        return 0

    if args.command == "decision" and args.decision_command == "import-review":
        workflow = load_workflow(Path(args.workflow))
        ledger_path = Path(args.ledger)
        ledger = load_ledger(ledger_path)
        require_strict_writable_ledger(ledger, "review decision import")
        decision = load_review_decision(load_yaml_mapping(Path(args.decision), "Review decision"))
        updated = apply_review_decision(
            ledger,
            decision,
            workflow=workflow,
            decision_ref=args.decision_ref,
        )
        write_ledger(ledger_path, updated)
        print(yaml.safe_dump(updated.event_log[-1], sort_keys=False))
        return 0

    if args.command == "decision" and args.decision_command == "accept-outcome":
        workflow = load_workflow(Path(args.workflow))
        ledger_path = Path(args.ledger)
        ledger = load_ledger(ledger_path)
        require_strict_writable_ledger(ledger, "outcome acceptance")
        assignment = load_assignment(load_yaml_mapping(Path(args.assignment), "Assignment"))
        result = load_result_proposal(load_yaml_mapping(Path(args.result), "Result"))
        outcome = load_node_outcome(load_yaml_mapping(Path(args.outcome), "Node outcome"))
        policy = (
            load_acceptance_policy(
                load_yaml_mapping(Path(args.policy), "Acceptance policy")
            )
            if args.policy
            else DEFAULT_ACCEPTANCE_POLICY
        )
        accepted = decide_staged_result(
            workflow,
            ledger,
            assignment,
            result,
            outcome,
            policy=policy,
            verification_status=args.verification_status,
            review_event_id=args.review_event_id,
            accepted_event_types=args.accepted_event,
            actor=args.actor,
            event_id=args.event_id,
            validation_rule=args.validation_rule,
        )
        write_ledger(ledger_path, accepted.ledger)
        print(yaml.safe_dump(accepted.decision_event, sort_keys=False))
        return 0

    if args.command == "decision" and args.decision_command == "import-advisor-outcome":
        workflow = load_workflow(Path(args.workflow))
        ledger_path = Path(args.ledger)
        ledger = load_ledger(ledger_path)
        require_strict_writable_ledger(ledger, "advisor outcome import")
        outcome = load_advisor_outcome(load_yaml_mapping(Path(args.outcome), "Advisor outcome"))
        updated = apply_advisor_outcome(
            ledger,
            outcome,
            workflow=workflow,
            outcome_ref=args.outcome_ref,
        )
        write_ledger(ledger_path, updated)
        print(yaml.safe_dump(updated.event_log[-1], sort_keys=False))
        return 0

    if args.command == "decision" and args.decision_command == "validate-routing":
        mission = load_mission(Path(args.mission))
        decision = load_routing_decision(load_yaml_mapping(Path(args.decision), "Routing decision"))
        workflow = load_workflow(Path(args.workflow)) if args.workflow else None
        validate_routing_decision(mission, decision, workflow=workflow)
        print(yaml.safe_dump(decision.to_dict(), sort_keys=False))
        return 0

    if args.command == "decision" and args.decision_command == "compile-dispatch":
        mission = load_mission(Path(args.mission))
        workflow = load_workflow(Path(args.workflow))
        routing_decision = load_routing_decision(load_yaml_mapping(Path(args.routing_decision), "Routing decision"))
        assignment = load_assignment(load_yaml_mapping(Path(args.assignment), "Assignment"))
        packet = compile_dispatch_packet(
            mission,
            workflow,
            routing_decision,
            assignment,
            packet_id=args.packet_id,
        )
        if args.dispatch_packet:
            packet_path = Path(args.dispatch_packet)
            with packet_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(packet.to_dict(), handle, sort_keys=False)
            loaded_packet = load_dispatch_packet(packet.to_dict())
            validate_dispatch_packet(mission, workflow, loaded_packet)
        print(yaml.safe_dump(packet.to_dict(), sort_keys=False))
        return 0

    return None
