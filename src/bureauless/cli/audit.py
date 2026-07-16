from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from ..agents.registry import doctor_agent, get_agent_spec, get_provider_profile, route_agent
from ..errors import ProtocolError
from ..protocol.assignments import export_assignment
from ..protocol.dispatch import compile_dispatch_packet
from ..protocol.harness import load_ledger, load_mission, load_workflow
from ..protocol.routing import load_routing_decision
from ..runtime.sessions import (
    load_session_record,
    run_independent_verification,
    start_dispatch_session,
)
from .common import load_yaml_mapping


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("audit", help="Minimal coding-agent audit workflow")
    commands = parser.add_subparsers(dest="audit_command", required=True)

    init = commands.add_parser("init", help="Create a single-agent audit control plane")
    init.add_argument("--workspace", default=".")
    init.add_argument("--task", required=True, help="Bounded task for the coding agent")

    run = commands.add_parser(
        "run",
        help="Execute one registered agent through the canonical audit contract",
    )
    run.add_argument("--workspace", default=".")
    run.add_argument("--agent", required=True)
    run.add_argument("--target-model", required=True)
    run.add_argument("--target-provider", required=True)
    run.add_argument("--provider-base-url")
    run.add_argument("--provider-api-key-env")
    run.add_argument("--provider-wire-api")
    run.add_argument(
        "--route-instance-id",
        default="unidentified",
        help="Opaque endpoint-instance label; do not put a URL or credential here",
    )
    run.add_argument(
        "--cohort-id",
        help="Opaque benchmark cohort shared only by deliberately comparable trials",
    )
    run.add_argument("--timeout-seconds", type=float, default=120.0)
    run.add_argument("--verify-command")
    run.add_argument("--verify-timeout-seconds", type=float, default=120.0)
    run.add_argument("--isolation-mode", choices=["copy", "worktree"], default="copy")
    run.add_argument("--cleanup-policy", default="retain_session_root")
    run.add_argument(
        "--sandbox-mode",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="workspace-write",
    )
    run.add_argument("--session-id")
    run.add_argument("--dry-run", action="store_true")

    report = commands.add_parser("report", help="Render a session record as a Markdown audit report")
    report.add_argument("session_record")
    report.add_argument("--output")

    archive = commands.add_parser("archive", help="Store a versioned audit snapshot for a session record")
    archive.add_argument("session_record")
    archive.add_argument("--workspace", default=".")

    verify = commands.add_parser("verify", help="Verify an archived session snapshot")
    verify.add_argument("manifest")

    observations = commands.add_parser(
        "observations",
        help="List and verify append-only route observations from audit runs",
    )
    observations.add_argument("--workspace", default=".")

    contribution = commands.add_parser(
        "contribution",
        help="Compare an identity-matched baseline and capability trial",
    )
    contribution.add_argument("baseline_session")
    contribution.add_argument("candidate_session")
    contribution.add_argument("--capability-id", required=True)
    contribution.add_argument("--invoked", choices=["true", "false"], required=True)
    contribution.add_argument(
        "--result-used", choices=["true", "false", "unknown"], default="unknown"
    )
    contribution.add_argument("--output")


def handle(args: argparse.Namespace) -> int | None:
    if args.command == "audit" and args.audit_command == "init":
        paths = initialize(Path(args.workspace), args.task)
        print(yaml.safe_dump({key: str(value) for key, value in paths.items()}, sort_keys=False))
        return 0

    if args.command == "audit" and args.audit_command == "run":
        paths = run_audit(
            Path(args.workspace),
            agent_id=args.agent,
            target_model=args.target_model,
            target_provider=args.target_provider,
            provider_base_url=args.provider_base_url,
            provider_api_key_env=args.provider_api_key_env,
            provider_wire_api=args.provider_wire_api,
            route_instance_id=args.route_instance_id,
            cohort_id=args.cohort_id,
            timeout_seconds=args.timeout_seconds,
            verify_command=args.verify_command,
            verify_timeout_seconds=args.verify_timeout_seconds,
            isolation_mode=args.isolation_mode,
            cleanup_policy=args.cleanup_policy,
            sandbox_mode=args.sandbox_mode,
            session_id=args.session_id,
            dry_run=args.dry_run,
        )
        print(yaml.safe_dump(paths, sort_keys=False))
        return 0

    if args.command == "audit" and args.audit_command == "report":
        session_path = Path(args.session_record)
        record = load_session_record(load_yaml_mapping(session_path, "Session"))
        output = Path(args.output) if args.output else session_path.with_suffix(".audit.md")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_report(record.to_dict()), encoding="utf-8")
        print(f"report: {output}")
        return 0

    if args.command == "audit" and args.audit_command == "archive":
        paths = archive_session(Path(args.session_record), Path(args.workspace))
        print(yaml.safe_dump({key: str(value) for key, value in paths.items()}, sort_keys=False))
        return 0

    if args.command == "audit" and args.audit_command == "verify":
        print(yaml.safe_dump(verify_archive(Path(args.manifest)), sort_keys=False))
        return 0

    if args.command == "audit" and args.audit_command == "observations":
        root = Path(args.workspace) / ".bureauless" / "runs"
        print(yaml.safe_dump(load_route_observations(root), sort_keys=False))
        return 0

    if args.command == "audit" and args.audit_command == "contribution":
        baseline_path = Path(args.baseline_session)
        candidate_path = Path(args.candidate_session)
        output = (
            Path(args.output)
            if args.output
            else candidate_path.with_name("capability-contribution.yaml")
        )
        if output.exists():
            raise ProtocolError(f"Capability contribution already exists: {output}")
        contribution = build_capability_contribution(
            baseline_path,
            candidate_path,
            capability_id=args.capability_id,
            invoked=args.invoked == "true",
            result_used=(
                args.result_used == "true"
                if args.result_used != "unknown"
                else "unknown"
            ),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_yaml(output, contribution)
        print(yaml.safe_dump({"contribution": str(output)}, sort_keys=False))
        return 0

    return None


def initialize(workspace: Path, task: str) -> dict[str, Path]:
    task = task.strip()
    if not task:
        raise ProtocolError("Audit task must not be empty")

    root = workspace / ".bureauless"
    paths = {
        "mission": root / "mission.yaml",
        "workflow": root / "workflow.yaml",
        "ledger": root / "ledger.yaml",
    }
    existing = [path for path in paths.values() if path.exists()]
    if existing:
        raise ProtocolError(f"Audit control plane already exists: {existing[0]}")

    root.mkdir(parents=True, exist_ok=True)
    _write_yaml(
        paths["mission"],
        {
            "mission_id": "audit",
            "goal": task,
            "status": "planning",
            "default_mode": "single_agent",
            "allowed_modes": ["single_agent"],
            "budget": {},
            "models": {},
            "human_gate": {"required_for": ["acceptance"]},
        },
    )
    _write_yaml(
        paths["workflow"],
        {
            "workflow_id": "audit-single-agent-001",
            "mission_id": "audit",
            "proposed_by": "human",
            "status": "accepted",
            "mode": "single_agent",
            "reason": "A bounded coding task starts with one worker and human acceptance.",
            "roles": {"worker": {"can_emit": ["task_completed"], "can_consume": []}},
            "events": {"task_completed": {"producer_roles": ["worker"]}},
            "nodes": [{"id": "implement", "role": "worker", "waits_for": [], "emits": ["task_completed"]}],
            "gates": [],
            "terminal_events": ["task_completed"],
            "broadcast_policy": {"default": "filtered_delta"},
            "budget_policy": {},
        },
    )
    _write_yaml(
        paths["ledger"],
        {
            "mission_id": "audit",
            "ledger_version": 2,
            "current_goal": task,
            "current_plan_ref": ".bureauless/workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        },
    )
    load_mission(paths["mission"])
    load_workflow(paths["workflow"])
    load_ledger(paths["ledger"])
    return paths


def run_audit(
    workspace: Path,
    *,
    agent_id: str,
    target_model: str,
    target_provider: str,
    provider_base_url: str | None = None,
    provider_api_key_env: str | None = None,
    provider_wire_api: str | None = None,
    route_instance_id: str = "unidentified",
    cohort_id: str | None = None,
    timeout_seconds: float = 120.0,
    verify_command: str | None = None,
    verify_timeout_seconds: float = 120.0,
    isolation_mode: str = "copy",
    cleanup_policy: str = "retain_session_root",
    sandbox_mode: str = "workspace-write",
    session_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    route_instance_id = route_instance_id.strip()
    if not route_instance_id:
        raise ProtocolError("route_instance_id must be a non-empty opaque label")
    if cohort_id is not None:
        cohort_id = cohort_id.strip()
        if not cohort_id:
            raise ProtocolError("cohort_id must be a non-empty opaque label")
    root = workspace / ".bureauless"
    mission_path = root / "mission.yaml"
    workflow_path = root / "workflow.yaml"
    ledger_path = root / "ledger.yaml"
    mission = load_mission(mission_path)
    workflow = load_workflow(workflow_path)
    ledger = load_ledger(ledger_path)

    resolved_session_id = session_id or f"session-{uuid4()}"
    run_root = root / "runs" / resolved_session_id
    run_root.mkdir(parents=True, exist_ok=False)
    assignment = export_assignment(
        workflow,
        ledger,
        "implement",
        assignment_id=f"assign-{resolved_session_id}",
        mission=mission,
    )
    routing = load_routing_decision(
        {
            "decision_type": "routing_decision",
            "mission_id": mission.mission_id,
            "workflow_id": workflow.workflow_id,
            "selected_mode": "single_agent",
            "selection_policy_version": "audit-single-agent-v1",
            "triggered_rules": ["bounded_single_agent_audit"],
            "rejected_modes": [],
            "estimated_coordination_ratio": 0.0,
            "budget_confidence": "high",
            "reason": "Run one registered agent under the canonical observation contract.",
            "advisor_gate_decision": {
                "invoked": False,
                "policy_version": "audit-single-agent-v1",
                "reason": ["single bounded worker"],
                "decision_basis": "explicit_audit_mode",
            },
        }
    )
    packet = compile_dispatch_packet(
        mission,
        workflow,
        routing,
        assignment,
        packet_id=f"packet-{resolved_session_id}",
    )
    assignment_path = run_root / "assignment.yaml"
    routing_path = run_root / "routing.yaml"
    registration_path = run_root / "registration.yaml"
    dispatch_path = run_root / "dispatch.yaml"
    _write_yaml(assignment_path, assignment.to_dict())
    _write_yaml(routing_path, routing.to_dict())
    registered_route = route_agent(agent_id, target_provider).to_dict()
    doctor = None if dry_run else doctor_agent(agent_id).to_dict()
    registration = {
        "agent": get_agent_spec(agent_id).to_dict(),
        "provider": get_provider_profile(target_provider).to_dict(),
        "route": registered_route,
        "doctor": doctor,
        "verification_freshness": _verification_freshness(registered_route, doctor),
        "route_instance_id": route_instance_id,
    }
    _write_yaml(registration_path, registration)

    live_session = start_dispatch_session(
        mission,
        workflow,
        packet,
        agent_id=agent_id,
        workdir=workspace,
        dispatch_packet_path=dispatch_path,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        isolation_mode=isolation_mode,
        cleanup_policy=cleanup_policy,
        sandbox_mode=sandbox_mode,
        target_model=target_model,
        target_provider=target_provider,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        provider_wire_api=provider_wire_api,
        session_id=resolved_session_id,
        context_ledger=ledger,
    )
    try:
        record = live_session.wait()
    except KeyboardInterrupt:
        live_session.cancel("user_interrupt")
        record = live_session.wait()
    record = replace(
        record,
        dispatch={**(record.dispatch or {}), "agent_registration": registration},
    )

    session_path = run_root / "session.yaml"
    report_path = run_root / "report.md"
    observation_path = run_root / "route-observation.yaml"
    verification_path: Path | None = None
    audit_evidence = dict(record.audit_evidence)
    if verify_command and not dry_run:
        verification_path = run_root / "verification.yaml"
        verification = run_independent_verification(
            verify_command,
            Path(record.workspace["path"]),
            timeout_seconds=verify_timeout_seconds,
        )
        _write_yaml(verification_path, verification)
        audit_evidence["independent_verification"] = {
            "source": "harness",
            "status": verification["status"],
            "exit_code": verification["exit_code"],
            "command_sha256": verification["command_sha256"],
            "workspace_state_ref": record.workspace.get("post_state_ref"),
            "evidence_ref": verification_path.name,
            "evidence_sha256": hashlib.sha256(verification_path.read_bytes()).hexdigest(),
        }
    else:
        audit_evidence["independent_verification"] = {
            "source": "harness",
            "status": "not_run",
            "reason": "dry_run" if dry_run and verify_command else "not_requested",
        }
    audit_evidence["benchmark_identity"] = {
        "schema": "bureauless_benchmark_identity_v1",
        "cohort_id": cohort_id or f"unassigned:{record.session_id}",
        "cohort_declared": cohort_id is not None,
        "trial_id": record.session_id,
        "task_sha256": _sha256_payload(
            {
                "mission_goal": mission.goal,
                "workflow_id": workflow.workflow_id,
                "node_id": assignment.node_id,
                "role": assignment.role,
                "assignment_goal": assignment.goal,
                "expected_events": assignment.expected_events,
                "forbidden_actions": assignment.forbidden_actions,
            }
        ),
        "workspace_baseline_ref": record.workspace.get("pre_state_ref"),
        "acceptance_contract_sha256": audit_evidence[
            "independent_verification"
        ].get("command_sha256"),
    }
    for point in audit_evidence.get("decision_points", []):
        if point.get("decision_type") != "dispatch":
            continue
        later_outcome = dict(point.get("later_outcome") or {})
        later_outcome["independent_verification_status"] = audit_evidence[
            "independent_verification"
        ]["status"]
        point["later_outcome"] = later_outcome
    record = replace(record, audit_evidence=audit_evidence)
    _write_yaml(session_path, record.to_dict())
    report_path.write_text(render_report(record.to_dict()), encoding="utf-8")
    _write_yaml(
        observation_path,
        build_route_observation(record.to_dict(), session_path, report_path),
    )
    archive = archive_session(session_path, workspace)
    return {
        "status": record.status,
        "session_id": record.session_id,
        "agent_id": record.agent_id,
        "assignment": str(assignment_path),
        "routing": str(routing_path),
        "registration": str(registration_path),
        "dispatch": str(dispatch_path),
        "session": str(session_path),
        "report": str(report_path),
        "route_observation": str(observation_path),
        "verification": str(verification_path) if verification_path else None,
        "archive_manifest": str(archive["manifest"]),
    }


def build_route_observation(
    record: dict[str, Any],
    session_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    registration = _mapping(_mapping(record.get("dispatch")).get("agent_registration"))
    route = _mapping(registration.get("route"))
    doctor = _mapping(registration.get("doctor"))
    result = _mapping(record.get("result_proposal"))
    extraction = _mapping(record.get("extraction"))
    verification = _mapping(result.get("verification"))
    verification_source = "result_proposal"
    if not verification:
        verification = _mapping(extraction.get("verification"))
        verification_source = "extraction" if verification else "not_observed"
    independent = _mapping(
        _mapping(record.get("audit_evidence")).get("independent_verification")
    )
    benchmark_identity = _mapping(
        _mapping(record.get("audit_evidence")).get("benchmark_identity")
    )
    if independent.get("status") not in (None, "not_run"):
        verification = independent
        verification_source = "harness"
    metrics = _mapping(record.get("outcome_metrics"))
    return {
        "schema": "bureauless_route_observation_v1",
        "observation_id": f"route-observation-{record['session_id']}",
        "observed_at": record["finished_at"],
        "session_id": record["session_id"],
        "agent_id": record["agent_id"],
        "runtime_version": doctor.get("version"),
        "route_instance_id": registration.get("route_instance_id", "unidentified"),
        "route": {
            key: route.get(key)
            for key in (
                "target_provider",
                "route_kind",
                "endpoint_family",
                "wire_api",
                "session_adapter",
                "runtime_contract_support",
                "adapter_support",
            )
        },
        "benchmark_identity": benchmark_identity,
        "outcome": {
            "session_status": record["status"],
            "exit_reason": _mapping(record.get("exit")).get("reason"),
            "verification_status": verification.get("status", "not_run"),
            "verification_source": verification_source,
            "independent_verification_status": independent.get("status", "not_run"),
            "changed_files_count": metrics.get("changed_files_count"),
            "diff_record_count": len(record.get("diff_refs", [])),
            "usage_source": metrics.get("usage_source", "unavailable"),
            "cost_source": metrics.get("cost_source", "unavailable"),
        },
        "evidence": {
            "session": session_path.name,
            "session_sha256": hashlib.sha256(session_path.read_bytes()).hexdigest(),
            "report": report_path.name,
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        },
    }


def load_route_observations(root: Path) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for observation_path in sorted(root.rglob("route-observation.yaml")):
        actual = load_yaml_mapping(observation_path, "Route observation")
        if actual.get("schema") != "bureauless_route_observation_v1":
            raise ProtocolError(f"Unsupported route observation schema: {observation_path}")
        session_path = observation_path.with_name("session.yaml")
        report_path = observation_path.with_name("report.md")
        record = load_session_record(load_yaml_mapping(session_path, "Observed session"))
        expected = build_route_observation(record.to_dict(), session_path, report_path)
        if actual != expected:
            raise ProtocolError(f"Route observation does not match session evidence: {observation_path}")
        observations.append(actual)
    return sorted(
        observations,
        key=lambda item: (str(item.get("observed_at")), str(item.get("observation_id"))),
    )


def build_capability_contribution(
    baseline_path: Path,
    candidate_path: Path,
    *,
    capability_id: str,
    invoked: bool,
    result_used: bool | str = "unknown",
) -> dict[str, Any]:
    capability_id = capability_id.strip()
    if not capability_id:
        raise ProtocolError("capability_id must be a non-empty string")
    if result_used not in (True, False, "unknown"):
        raise ProtocolError("result_used must be true, false, or unknown")
    baseline = load_session_record(load_yaml_mapping(baseline_path, "Baseline session"))
    candidate = load_session_record(load_yaml_mapping(candidate_path, "Candidate session"))
    baseline_identity = _mapping(baseline.audit_evidence.get("benchmark_identity"))
    candidate_identity = _mapping(candidate.audit_evidence.get("benchmark_identity"))
    if not baseline_identity or not candidate_identity:
        raise ProtocolError("Both sessions require benchmark_identity")
    if not baseline_identity.get("cohort_declared") or not candidate_identity.get(
        "cohort_declared"
    ):
        raise ProtocolError("Capability comparison requires an explicitly declared cohort")
    identity_fields = (
        "cohort_id",
        "task_sha256",
        "workspace_baseline_ref",
        "acceptance_contract_sha256",
    )
    mismatches = [
        key
        for key in identity_fields
        if baseline_identity.get(key) != candidate_identity.get(key)
    ]
    if mismatches:
        raise ProtocolError(
            "Capability comparison identity mismatch: " + ", ".join(mismatches)
        )
    if not baseline_identity.get("workspace_baseline_ref"):
        raise ProtocolError("Capability comparison requires a measured workspace baseline")
    if not baseline_identity.get("acceptance_contract_sha256"):
        raise ProtocolError("Capability comparison requires an independent acceptance contract")
    if baseline.session_id == candidate.session_id:
        raise ProtocolError("Capability comparison requires two distinct trials")

    baseline_metrics = baseline.outcome_metrics
    candidate_metrics = candidate.outcome_metrics
    baseline_verification = _mapping(
        baseline.audit_evidence.get("independent_verification")
    )
    candidate_verification = _mapping(
        candidate.audit_evidence.get("independent_verification")
    )
    return {
        "schema": "bureauless_capability_contribution_v1",
        "capability_contribution": {
            "capability_id": capability_id,
            "invoked": invoked,
            "result_used": result_used,
            "measurable_delta": {
                "wall_time_ms": _numeric_delta(
                    baseline_metrics.get("wall_time_ms"),
                    candidate_metrics.get("wall_time_ms"),
                    provenance="harness",
                ),
                "changed_files_count": _numeric_delta(
                    baseline_metrics.get("changed_files_count"),
                    candidate_metrics.get("changed_files_count"),
                    provenance="harness",
                ),
                "independent_verification": {
                    "baseline": baseline_verification.get("status", "not_run"),
                    "candidate": candidate_verification.get("status", "not_run"),
                    "provenance": "harness",
                },
                "total_tokens": _conditional_metric_delta(
                    baseline_metrics,
                    candidate_metrics,
                    "total_tokens",
                    "usage_source",
                ),
                "cost_usd": _conditional_metric_delta(
                    baseline_metrics,
                    candidate_metrics,
                    "cost_usd",
                    "cost_source",
                ),
            },
        },
        "causal_claim": "not_established",
        "attestation": {
            "invoked": "operator_asserted",
            "result_used": "operator_asserted" if result_used != "unknown" else "unknown",
        },
        "comparison_identity": {
            key: baseline_identity.get(key) for key in identity_fields
        },
        "baseline": {
            "session_id": baseline.session_id,
            "path": str(baseline_path),
            "sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        },
        "candidate": {
            "session_id": candidate.session_id,
            "path": str(candidate_path),
            "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        },
    }


def _numeric_delta(
    baseline: object,
    candidate: object,
    *,
    provenance: str,
) -> dict[str, Any]:
    if not isinstance(baseline, (int, float)) or not isinstance(candidate, (int, float)):
        return {"eligibility": "unavailable", "provenance": provenance}
    return {
        "eligibility": "comparable",
        "baseline": baseline,
        "candidate": candidate,
        "delta": candidate - baseline,
        "provenance": provenance,
    }


def _conditional_metric_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    metric: str,
    source_field: str,
) -> dict[str, Any]:
    baseline_source = baseline.get(source_field, "unavailable")
    candidate_source = candidate.get(source_field, "unavailable")
    if baseline_source != candidate_source or baseline_source == "unavailable":
        return {
            "eligibility": "unavailable",
            "baseline_source": baseline_source,
            "candidate_source": candidate_source,
        }
    delta = _numeric_delta(
        baseline.get(metric), candidate.get(metric), provenance=str(baseline_source)
    )
    if delta["eligibility"] == "comparable":
        delta["eligibility"] = "conditional"
    return delta


def archive_session(session_path: Path, workspace: Path) -> dict[str, Path]:
    source = session_path.resolve()
    payload = source.read_bytes()
    record = load_session_record(load_yaml_mapping(source, "Session"))
    session_id = record.session_id
    if Path(session_id).name != session_id or session_id in {".", ".."}:
        raise ProtocolError("Session id cannot be used as an audit archive path")

    archive_root = workspace / ".bureauless" / "audits" / _audit_day(record.finished_at) / session_id
    archive_root.mkdir(parents=True, exist_ok=False)
    snapshot = archive_root / "session.yaml"
    snapshot.write_bytes(payload)
    report = archive_root / "report.md"
    report.write_text(render_report(record.to_dict()), encoding="utf-8")
    report_payload = report.read_bytes()
    extra_artifacts: list[dict[str, str]] = []
    for name in ("route-observation.yaml", "verification.yaml"):
        extra_source = source.with_name(name)
        if not extra_source.is_file():
            continue
        extra_payload = extra_source.read_bytes()
        (archive_root / name).write_bytes(extra_payload)
        extra_artifacts.append(
            {"path": name, "sha256": hashlib.sha256(extra_payload).hexdigest()}
        )
    manifest = archive_root / "manifest.yaml"
    _write_yaml(
        manifest,
        {
            "schema": "bureauless_audit_snapshot_v3",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source_session": str(source),
            "source_sha256": hashlib.sha256(payload).hexdigest(),
            "report_sha256": hashlib.sha256(report_payload).hexdigest(),
            "session_id": session_id,
            "record": "session.yaml",
            "report": "report.md",
            "artifacts": extra_artifacts,
        },
    )
    return {"archive": archive_root, "manifest": manifest, "session": snapshot, "report": report}


def verify_archive(manifest_path: Path) -> dict[str, str]:
    manifest = load_yaml_mapping(manifest_path, "Audit manifest")
    schema = manifest.get("schema")
    if schema not in {
        "bureauless_audit_snapshot_v1",
        "bureauless_audit_snapshot_v2",
        "bureauless_audit_snapshot_v3",
    }:
        raise ProtocolError("Unsupported audit snapshot schema")
    record_name = manifest.get("record")
    report_name = manifest.get("report")
    expected_sha = manifest.get("source_sha256")
    expected_report_sha = manifest.get("report_sha256")
    if not all(
        isinstance(value, str) and value not in {".", ".."} and Path(value).name == value
        for value in (record_name, report_name)
    ):
        raise ProtocolError("Audit manifest contains an unsafe artifact path")
    if not isinstance(expected_sha, str):
        raise ProtocolError("Audit manifest is missing source_sha256")
    if schema in {"bureauless_audit_snapshot_v2", "bureauless_audit_snapshot_v3"} and not isinstance(expected_report_sha, str):
        raise ProtocolError("Audit manifest is missing report_sha256")
    root = manifest_path.parent
    snapshot = root / record_name
    report = root / report_name
    payload = snapshot.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha:
        raise ProtocolError("Archived session hash does not match manifest")
    load_session_record(load_yaml_mapping(snapshot, "Archived session"))
    if not report.is_file():
        raise ProtocolError("Archived audit report is missing")
    if isinstance(expected_report_sha, str) and hashlib.sha256(report.read_bytes()).hexdigest() != expected_report_sha:
        raise ProtocolError("Archived audit report hash does not match manifest")
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ProtocolError("Audit manifest artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ProtocolError("Audit manifest artifact must be an object")
        name = artifact.get("path")
        expected = artifact.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(expected, str)
        ):
            raise ProtocolError("Audit manifest contains an invalid artifact")
        artifact_path = root / name
        if not artifact_path.is_file():
            raise ProtocolError(f"Archived audit artifact is missing: {name}")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != expected:
            raise ProtocolError(f"Archived audit artifact hash does not match manifest: {name}")
    return {"status": "verified", "session": str(snapshot), "report": str(report)}


def render_report(record: dict[str, Any]) -> str:
    metrics = _mapping(record.get("outcome_metrics"))
    result = _mapping(record.get("result_proposal"))
    verification = _mapping(result.get("verification"))
    if not verification:
        verification = _mapping(_mapping(record.get("extraction")).get("verification"))
    changed_files = metrics.get("changed_files_count", "unavailable")
    total_tokens = metrics.get("total_tokens", "unavailable")
    cost = metrics.get("cost_usd", "unavailable")
    model = result.get("effective_model", "unavailable")
    provider = result.get("effective_provider", "unavailable")
    review_status = result.get("review_status")
    if not isinstance(review_status, str) or not review_status:
        review_status = "not_run" if record.get("status") == "dry_run" else "not_recorded"
    model_identity = _mapping(result.get("model_identity"))
    metric_provenance = _mapping(result.get("metric_provenance"))
    route_evidence = _mapping(result.get("route_evidence"))
    registration = _mapping(_mapping(record.get("dispatch")).get("agent_registration"))
    registered_route = _mapping(registration.get("route"))
    doctor = _mapping(registration.get("doctor"))
    audit_evidence = _mapping(record.get("audit_evidence"))
    independent_verification = _mapping(
        audit_evidence.get("independent_verification")
    )
    benchmark_identity = _mapping(audit_evidence.get("benchmark_identity"))
    decision_points = _mapping_list(audit_evidence.get("decision_points"))
    side_effects = _mapping_list(audit_evidence.get("side_effects"))
    side_effect_coverage = _mapping(audit_evidence.get("side_effect_coverage"))
    capability_contributions = _mapping_list(
        audit_evidence.get("capability_contributions")
    )
    lines = [
        "# BureauLess audit report",
        "",
        f"- Session: `{record['session_id']}`",
        f"- Assignment: `{record['assignment_id']}`",
        f"- Agent: `{record['agent_id']}`",
        f"- Status: `{record['status']}`",
        f"- Started: `{record['started_at']}`",
        f"- Finished: `{record['finished_at']}`",
        f"- Model: `{model}`",
        f"- Provider: `{provider}`",
        f"- Adapter: `{_display(registered_route.get('session_adapter'))}`",
        f"- Runtime version: `{_display(doctor.get('version'))}`",
        f"- Route verification freshness: `{_display(registration.get('verification_freshness'))}`",
        f"- Benchmark cohort: `{_display(benchmark_identity.get('cohort_id'))}`",
        f"- Task contract: `{_display(benchmark_identity.get('task_sha256'))}`",
        f"- Workspace baseline: `{_display(benchmark_identity.get('workspace_baseline_ref'))}`",
        "",
        "## Evidence",
        "",
        f"- Changed files: `{changed_files}`",
        f"- Diff records: `{len(record.get('diff_refs', []))}`",
        f"- Agent-reported verification: `{verification.get('status', 'not_run')}`",
        f"- Independent verification: `{independent_verification.get('status', 'not_run')}`",
        f"- Total tokens: `{total_tokens}`",
        f"- Cost USD: `{cost}`",
        f"- Review status: `{review_status}`",
        "",
        "## Model identity",
        "",
        f"- Requested: `{_display(model_identity.get('requested', model))}`",
        f"- CLI reported: `{_display(model_identity.get('cli_reported'))}`",
        f"- Provider reported: `{_display(model_identity.get('provider_reported'))}`",
        f"- Independently attested: `{_display(model_identity.get('independently_attested'))}`",
        "",
        "## Route evidence",
        "",
        f"- Runtime contract support: `{_display(route_evidence.get('runtime_contract_support'))}`",
        f"- Adapter support: `{_display(route_evidence.get('adapter_support'))}`",
        f"- Tested route support: `{_display(route_evidence.get('tested_route_support'))}`",
        f"- This session's route support: `{_display(route_evidence.get('session_route_support'))}`",
        f"- Verification levels: `{_display(route_evidence.get('verification_levels'))}`",
        "",
        "## Metric provenance",
        "",
        f"- Wall time: `{_display(metric_provenance.get('wall_time'))}`",
        f"- File delta: `{_display(metric_provenance.get('file_delta'))}`",
        f"- Token usage: `{_display(metric_provenance.get('token_usage'))}`",
        f"- Monetary cost: `{_display(metric_provenance.get('monetary_cost'))}`",
        f"- Tool timeline: `{_display(metric_provenance.get('tool_timeline'))}`",
        f"- Comparison eligibility: `{_display(metric_provenance.get('comparison_eligibility'))}`",
        "",
        "## Governance evidence",
        "",
        f"- Decision points: `{len(decision_points)}`",
        f"- Side effects: `{_display([_side_effect_label(item) for item in side_effects])}`",
        f"- Side-effect coverage: `{_display({key: _mapping(value).get('status') for key, value in side_effect_coverage.items()})}`",
        f"- Capability contributions: `{len(capability_contributions)}`",
    ]
    return "\n".join(lines) + "\n"


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _side_effect_label(effect: dict[str, Any]) -> str:
    return ":".join(
        str(effect.get(key, "unknown")) for key in ("type", "source", "verified")
    )


def _display(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "unavailable"
    if isinstance(value, dict):
        return ", ".join(f"{key}={item}" for key, item in value.items()) or "unavailable"
    return str(value)


def _verification_freshness(
    route: dict[str, Any],
    doctor: dict[str, Any] | None,
) -> str:
    if doctor is None:
        return "not_checked"
    verified_version = route.get("verified_runtime_version")
    if not isinstance(verified_version, str):
        return "route_unverified"
    installed_version = doctor.get("version")
    if not isinstance(installed_version, str):
        return "installed_version_unknown"
    return "matching" if verified_version in installed_version else "version_drift"


def _audit_day(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return "undated"


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def _sha256_payload(payload: dict[str, Any]) -> str:
    encoded = yaml.safe_dump(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
