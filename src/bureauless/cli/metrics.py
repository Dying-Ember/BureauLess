from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from ..runtime import summarize_metrics


def register(subparsers: argparse._SubParsersAction) -> None:
    metrics_parser = subparsers.add_parser("metrics", help="Outcome metrics operations")
    metrics_subparsers = metrics_parser.add_subparsers(dest="metrics_command", required=True)
    metrics_summarize_parser = metrics_subparsers.add_parser("summarize", help="Summarize session or ledger metrics")
    metrics_summarize_parser.add_argument("path")
    metrics_summarize_parser.add_argument("--price-snapshot")


def handle(args: argparse.Namespace) -> int | None:
    if args.command == "metrics" and args.metrics_command == "summarize":
        snapshot_path = Path(args.price_snapshot) if args.price_snapshot else None
        print(yaml.safe_dump(summarize_metrics(Path(args.path), snapshot_path), sort_keys=False))
        return 0
    return None
