from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from ..agents import (
    assess_agent_compatibility,
    assess_dispatch_readiness,
    doctor_agent,
    list_agent_compatibility,
    list_agent_specs,
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
        if args.agent_id:
            payload = assess_agent_compatibility(args.agent_id).to_dict()
        else:
            payload = [entry.to_dict() for entry in list_agent_compatibility()]
        print(yaml.safe_dump(payload, sort_keys=False))
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
