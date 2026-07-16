from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from ..errors import ProtocolError
from ..agents import (
    assess_agent_compatibility,
    assess_dispatch_readiness,
    doctor_agent,
    list_agent_compatibility,
    list_agent_route_evidence,
    list_agent_specs,
    route_agent,
)


def register(subparsers: argparse._SubParsersAction) -> None:
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
    agent_matrix_parser.add_argument(
        "--evidence",
        action="store_true",
        help="Render static Agent×Provider evidence instead of installed-binary doctor results",
    )
    agent_matrix_parser.add_argument(
        "--observations",
        help="Audit runs directory containing verified route-observation.yaml artifacts",
    )
    agent_route_parser = agent_subparsers.add_parser("route", help="Show the runtime route for an agent")
    agent_route_parser.add_argument("agent_id")
    agent_route_parser.add_argument("--provider", dest="target_provider")
    agent_readiness_parser = agent_subparsers.add_parser(
        "readiness",
        help="Evaluate dispatch readiness for an agent against a workspace and isolation mode",
    )
    agent_readiness_parser.add_argument("agent_id")
    agent_readiness_parser.add_argument("--workdir", default=".")
    agent_readiness_parser.add_argument("--isolation-mode", choices=["copy", "worktree"], default="copy")


def handle(args: argparse.Namespace) -> int | None:
    if args.command != "agent":
        return None

    if args.agent_command == "list":
        print(yaml.safe_dump([spec.to_dict() for spec in list_agent_specs()], sort_keys=False))
        return 0

    if args.agent_command == "doctor":
        print(yaml.safe_dump(doctor_agent(args.agent_id).to_dict(), sort_keys=False))
        return 0

    if args.agent_command == "matrix":
        if args.evidence:
            payload = [entry.to_dict() for entry in list_agent_route_evidence(args.agent_id)]
            if args.observations:
                from .audit import load_route_observations

                observations = load_route_observations(Path(args.observations))
                if args.agent_id:
                    observations = [
                        item for item in observations if item.get("agent_id") == args.agent_id
                    ]
                payload = {"routes": payload, "observations": observations}
        elif args.agent_id:
            if args.observations:
                raise ProtocolError("agent matrix --observations requires --evidence")
            payload = assess_agent_compatibility(args.agent_id).to_dict()
        else:
            if args.observations:
                raise ProtocolError("agent matrix --observations requires --evidence")
            payload = [entry.to_dict() for entry in list_agent_compatibility()]
        print(yaml.safe_dump(payload, sort_keys=False))
        return 0

    if args.agent_command == "route":
        print(yaml.safe_dump(route_agent(args.agent_id, args.target_provider).to_dict(), sort_keys=False))
        return 0

    if args.agent_command == "readiness":
        payload = assess_dispatch_readiness(
            args.agent_id,
            Path(args.workdir),
            isolation_mode=args.isolation_mode,
        ).to_dict()
        print(yaml.safe_dump(payload, sort_keys=False))
        return 0

    return None
