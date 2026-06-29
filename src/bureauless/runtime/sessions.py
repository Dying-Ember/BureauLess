from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable
from uuid import uuid4

import yaml

from ..agents import resolve_agent_binding
from ..core import ProtocolError
from ..protocol.artifacts import sha256_file
from ..protocol.assignments import AssignmentPacket
from ..protocol.assignments import render_assignment_prompt
from ..protocol.harness import Workflow
from ..protocol.ledger import append_ledger_event
from ..protocol.outcomes import (
    build_node_outcome_decision_event,
    node_outcome_from_session,
    reconcile_node_outcome_state,
)
from ..protocol.results import ResultProposal, load_result_proposal
from ..protocol.results import import_result_proposal
from ..runtime_workspace import (
    WorkspaceReadiness,
    assess_workspace_isolation,
    git_environment,
    probe_git_worktree,
)


SUPPORTED_SESSION_AGENTS = {"fake", "shell-dummy", "codex-cli"}

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SessionSpec:
    session_id: str
    assignment_id: str
    agent_id: str
    workdir: str
    timeout_seconds: float
    dry_run: bool
    isolation_mode: str
    cleanup_policy: str
    shell_command: str | None = None
    target_model: str | None = None
    target_provider: str | None = None
    provider_base_url: str | None = None
    provider_api_key_env: str | None = None
    provider_wire_api: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "agent_id": self.agent_id,
            "workdir": self.workdir,
            "timeout_seconds": self.timeout_seconds,
            "dry_run": self.dry_run,
            "isolation_mode": self.isolation_mode,
            "cleanup_policy": self.cleanup_policy,
            "shell_command": self.shell_command,
            "target_model": self.target_model,
            "target_provider": self.target_provider,
            "provider_base_url": self.provider_base_url,
            "provider_api_key_env": self.provider_api_key_env,
            "provider_wire_api": self.provider_wire_api,
        }


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    assignment_id: str
    agent_id: str
    status: str
    started_at: str
    finished_at: str
    exit: dict[str, Any]
    native_logs: dict[str, str]
    diff_refs: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    workspace: dict[str, Any]
    outcome_metrics: dict[str, Any]
    extraction: dict[str, Any]
    result_proposal: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit": self.exit,
            "native_logs": self.native_logs,
            "diff_refs": self.diff_refs,
            "artifacts": self.artifacts,
            "workspace": self.workspace,
            "outcome_metrics": self.outcome_metrics,
            "extraction": self.extraction,
            "result_proposal": self.result_proposal,
        }


def create_session_spec(
    assignment: AssignmentPacket,
    agent_id: str,
    workdir: Path,
    timeout_seconds: float = 30.0,
    dry_run: bool = False,
    isolation_mode: str = "copy",
    cleanup_policy: str = "retain_session_root",
    shell_command: str | None = None,
    target_model: str | None = None,
    target_provider: str | None = None,
    provider_base_url: str | None = None,
    provider_api_key_env: str | None = None,
    provider_wire_api: str | None = None,
    session_id: str | None = None,
) -> SessionSpec:
    if agent_id not in SUPPORTED_SESSION_AGENTS:
        raise ProtocolError(f"Unsupported session agent: {agent_id}")
    if isolation_mode not in {"copy", "worktree"}:
        raise ProtocolError(f"Unsupported isolation_mode: {isolation_mode}")
    if agent_id == "shell-dummy" and not dry_run and not shell_command:
        raise ProtocolError("shell-dummy session requires --shell-command")
    if agent_id == "codex-cli":
        if target_model is None or target_provider is None:
            raise ProtocolError("codex-cli session requires target_model and target_provider")
        resolve_agent_binding(
            agent_id,
            target_model=target_model,
            target_provider=target_provider,
            provider_base_url=provider_base_url,
            provider_api_key_env=provider_api_key_env,
            provider_wire_api=provider_wire_api,
        )
    return SessionSpec(
        session_id=session_id or f"session-{uuid4()}",
        assignment_id=assignment.assignment_id,
        agent_id=agent_id,
        workdir=str(workdir),
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        isolation_mode=isolation_mode,
        cleanup_policy=cleanup_policy,
        shell_command=shell_command,
        target_model=target_model,
        target_provider=target_provider,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        provider_wire_api=provider_wire_api,
    )


def run_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    *,
    command_runner: CommandRunner | None = None,
) -> SessionRecord:
    if assignment.assignment_id != spec.assignment_id:
        raise ProtocolError("Session assignment_id does not match assignment packet")

    started_at = _now()
    started_monotonic = time.monotonic()

    if spec.dry_run:
        base_metrics = _base_outcome_metrics(wall_time_ms=0)
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="dry_run",
            started_at=started_at,
            finished_at=started_at,
            exit={"code": 0, "reason": "dry_run"},
            native_logs={"stdout": "", "stderr": ""},
            diff_refs=[],
            artifacts=[],
            workspace=_unprepared_workspace_record(spec),
            outcome_metrics=base_metrics,
            extraction={
                "contract": "none",
                "status": "dry_run",
                "warnings": [],
                "parsed_fields": [],
                "missing_fields": [],
            },
            result_proposal=None,
        )

    if spec.agent_id == "fake":
        wall_time_ms = max(1, int((time.monotonic() - started_monotonic) * 1000))
        outcome_metrics = _base_outcome_metrics(wall_time_ms=wall_time_ms)
        outcome_metrics["patch_bytes"] = 0
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status="completed",
            effective_model="fake",
            effective_provider="fixture",
            emitted_events=assignment.expected_events,
            artifacts=[],
            outcome_metrics=outcome_metrics,
            verification={"status": "not_run"},
            native_log_refs=[],
            mutation_proposal_refs=[],
            review_status=None,
        )
        finished_at = _now()
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": 0, "reason": "completed"},
            native_logs={"stdout": "fake session completed", "stderr": ""},
            diff_refs=[],
            artifacts=[],
            workspace=_unprepared_workspace_record(spec),
            outcome_metrics=result.outcome_metrics,
            extraction={
                "contract": "fake_session_v1",
                "status": "synthetic",
                "warnings": [
                    "fake agent does not emit native token or cost usage",
                ],
                "parsed_fields": [
                    "effective_model",
                    "effective_provider",
                    "emitted_events",
                    "verification.status",
                ],
                "missing_fields": [
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cost_usd",
                ],
            },
            result_proposal=result.to_dict(),
        )

    if spec.agent_id == "codex-cli":
        return _run_codex_cli_session(
            spec,
            assignment,
            started_at,
            started_monotonic,
            command_runner=command_runner,
        )

    return _run_shell_dummy_session(spec, assignment, started_at, started_monotonic)


def cancel_session_record(record: SessionRecord, reason: str = "cancelled") -> SessionRecord:
    finished_at = _now()
    return replace(
        record,
        status="cancelled",
        finished_at=finished_at,
        exit={"code": None, "reason": reason},
        result_proposal=None,
    )


def supersede_session_record(
    record: SessionRecord,
    reason: str = "superseded",
) -> SessionRecord:
    finished_at = _now()
    return replace(
        record,
        status="superseded",
        finished_at=finished_at,
        exit={"code": None, "reason": reason},
        result_proposal=None,
    )


def build_assignment_created_event(
    workflow: Workflow,
    assignment: AssignmentPacket,
    session_id: str,
    agent_id: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id or f"event-{assignment.assignment_id}-created",
        "event_type": "assignment_created",
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "assignment_id": assignment.assignment_id,
        "node_id": assignment.node_id,
        "role": assignment.role,
        "agent_id": agent_id,
        "session_id": session_id,
        "created_at": _now(),
    }


def build_session_terminal_event(
    workflow: Workflow,
    assignment: AssignmentPacket,
    record: SessionRecord,
    event_id: str | None = None,
    superseded_by: str | None = None,
) -> dict[str, Any] | None:
    event_type = _terminal_event_type(record.status)
    if event_type is None:
        return None

    payload = {
        "event_id": event_id or f"event-{assignment.assignment_id}-{event_type}",
        "event_type": event_type,
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "assignment_id": assignment.assignment_id,
        "node_id": assignment.node_id,
        "role": assignment.role,
        "agent_id": record.agent_id,
        "session_id": record.session_id,
        "created_at": record.finished_at,
        "reason": record.exit.get("reason"),
        "exit": record.exit,
    }
    if superseded_by is not None:
        payload["superseded_by"] = superseded_by
    return payload


def load_session_record(data: dict[str, Any]) -> SessionRecord:
    return SessionRecord(
        session_id=_as_string(data, "session_id"),
        assignment_id=_as_string(data, "assignment_id"),
        agent_id=_as_string(data, "agent_id"),
        status=_as_string(data, "status"),
        started_at=_as_string(data, "started_at"),
        finished_at=_as_string(data, "finished_at"),
        exit=_as_mapping(data, "exit"),
        native_logs=_as_mapping(data, "native_logs"),
        diff_refs=_as_mapping_list(data, "diff_refs", default=[]),
        artifacts=_as_mapping_list(data, "artifacts", default=[]),
        workspace=_as_mapping(data, "workspace", default={}),
        outcome_metrics=_as_mapping(data, "outcome_metrics", default={}),
        extraction=_as_mapping(data, "extraction", default={}),
        result_proposal=data.get("result_proposal"),
    )


def package_session_result(
    record: SessionRecord,
    assignment: AssignmentPacket,
    artifact_root: Path | None = None,
    result_id: str | None = None,
) -> ResultProposal:
    if record.assignment_id != assignment.assignment_id:
        raise ProtocolError("Session record assignment_id does not match assignment packet")
    if record.status != "completed":
        raise ProtocolError(f"Cannot package session result from status {record.status!r}")
    if not isinstance(record.result_proposal, dict):
        raise ProtocolError("Session record is missing an import-ready result proposal payload")

    base = load_result_proposal(record.result_proposal)
    if base.assignment_id != assignment.assignment_id:
        raise ProtocolError("Session result proposal assignment_id does not match assignment packet")
    if base.agent_id != record.agent_id:
        raise ProtocolError("Session result proposal agent_id does not match session record")

    packaged_result_id = result_id or base.result_id
    source_event = f"event-{packaged_result_id}"
    package_root, workspace_root = _packaging_roots(record, artifact_root)
    artifacts = [
        _normalize_packaged_artifact(
            artifact,
            package_root=package_root,
            workspace_root=workspace_root,
            source_event=source_event,
            created_by=record.agent_id,
            fallback_id=f"artifact-{packaged_result_id}-{index:03d}",
        )
        for index, artifact in enumerate(base.artifacts or record.artifacts, start=1)
    ]
    native_log_refs = _package_native_log_refs(
        record,
        package_root,
        source_event,
        packaged_result_id,
    )

    return ResultProposal(
        result_id=packaged_result_id,
        assignment_id=base.assignment_id,
        agent_id=base.agent_id,
        status=base.status,
        effective_model=base.effective_model,
        effective_provider=base.effective_provider,
        emitted_events=list(base.emitted_events),
        artifacts=artifacts,
        outcome_metrics=dict(base.outcome_metrics),
        verification=dict(base.verification),
        native_log_refs=native_log_refs,
        mutation_proposal_refs=list(base.mutation_proposal_refs),
        review_status=base.review_status,
    )


def import_session_record(
    workflow: Workflow,
    ledger: Any,
    assignment: AssignmentPacket,
    record: SessionRecord,
    *,
    artifact_root: Path | None = None,
    result_id: str | None = None,
    outcome_id: str | None = None,
    decision_event_id: str | None = None,
    actor: str = "harness",
    disposition: str = "accepted",
    accepted_event_types: list[str] | None = None,
    validation_rule: str | None = None,
) -> Any:
    result = package_session_result(
        record,
        assignment,
        artifact_root=artifact_root,
        result_id=result_id,
    )
    updated = import_result_proposal(workflow, ledger, assignment, result)
    outcome = reconcile_node_outcome_state(
        node_outcome_from_session(
            assignment,
            record.to_dict(),
            outcome_id=outcome_id,
        ),
        _accepted_workspace_ref_for_node(ledger, assignment.node_id),
    )
    accepted_event_types = accepted_event_types or result.emitted_events
    if outcome.status in {"stale", "needs_review"}:
        accepted_event_types = []
    decision_event = build_node_outcome_decision_event(
        outcome,
        event_id=decision_event_id or f"event-{outcome.outcome_id}-decision",
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        actor=actor,
        disposition=disposition,
        accepted_event_types=accepted_event_types,
        validation_rule=validation_rule,
        created_at=record.finished_at,
    )
    return append_ledger_event(updated, decision_event, workflow)


def _run_shell_dummy_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    try:
        completed = subprocess.run(
            ["bash", "-lc", spec.shell_command or ""],
            cwd=workdir,
            check=False,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = _now()
        native_logs = _persist_native_logs(workspace, exc.stdout or "", exc.stderr or "")
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="timed_out",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": None, "reason": "timed_out"},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction={
                "contract": "shell_dummy_v1",
                "status": "timed_out",
                "warnings": [],
                "parsed_fields": [],
                "missing_fields": [],
            },
            result_proposal=None,
        )
    except OSError as exc:
        finished_at = _now()
        native_logs = _persist_native_logs(workspace, "", str(exc))
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": 1, "reason": "launch_failed"},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction={
                "contract": "shell_dummy_v1",
                "status": "launch_failed",
                "warnings": [str(exc)],
                "parsed_fields": [],
                "missing_fields": [],
            },
            result_proposal=None,
        )

    finished_at = _now()
    wall_time_ms = max(1, int((time.monotonic() - started_monotonic) * 1000))
    status = "completed" if completed.returncode == 0 else "failed"
    native_logs = _persist_native_logs(workspace, completed.stdout, completed.stderr)
    extraction = _extract_shell_dummy_output(spec, assignment, completed.stdout)
    baseline_metrics, baseline_diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    outcome_metrics = _merge_outcome_metrics(
        _merge_outcome_metrics(_base_outcome_metrics(wall_time_ms=wall_time_ms), baseline_metrics),
        _as_mapping(extraction, "outcome_metrics", default={}),
    )
    if not extraction["diff_refs"] and baseline_diff_refs:
        extraction["diff_refs"] = baseline_diff_refs
    result_proposal = None
    if completed.returncode == 0:
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status=_string_value(extraction.get("result_status"), default="completed"),
            effective_model=_string_or_none(extraction.get("effective_model")),
            effective_provider=_string_or_none(extraction.get("effective_provider")),
            emitted_events=_string_list_value(extraction.get("emitted_events")),
            artifacts=_as_mapping_list(extraction, "artifacts", default=[]),
            outcome_metrics=outcome_metrics,
            verification=_as_mapping(extraction, "verification", default={"status": "not_run"}),
            native_log_refs=_as_mapping_list(extraction, "native_log_refs", default=[]),
            mutation_proposal_refs=_string_list_value(
                extraction.get("mutation_proposal_refs")
            ),
            review_status=_string_or_none(extraction.get("review_status")),
        )
        result_proposal = result.to_dict()

    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        exit={"code": completed.returncode, "reason": status},
        native_logs=native_logs,
        diff_refs=_as_mapping_list(extraction, "diff_refs", default=[]),
        artifacts=_as_mapping_list(extraction, "artifacts", default=[]),
        workspace=workspace,
        outcome_metrics=outcome_metrics,
        extraction=extraction,
        result_proposal=result_proposal,
    )


def _run_codex_cli_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
    *,
    command_runner: CommandRunner | None = None,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    binding = resolve_agent_binding(
        spec.agent_id,
        target_model=_as_string({"target_model": spec.target_model}, "target_model"),
        target_provider=_as_string({"target_provider": spec.target_provider}, "target_provider"),
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
    )
    env = _build_codex_environment(binding)
    codex_home = _prepare_codex_home(workspace, binding, env)
    command = _build_codex_command(spec, binding, workdir)
    prompt = _render_codex_assignment_prompt(assignment)

    try:
        try:
            completed = _run_command_runner(
                command_runner,
                command,
                cwd=workdir,
                env=env,
                timeout=spec.timeout_seconds,
                input_text=prompt,
            )
        finally:
            _cleanup_codex_home(codex_home)
    except subprocess.TimeoutExpired as exc:
        finished_at = _now()
        native_logs = _persist_native_logs(workspace, exc.stdout or "", exc.stderr or "")
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        extraction = _empty_agent_extraction("timed_out", [])
        extraction["contract"] = "codex_exec_v1"
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="timed_out",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": None, "reason": "timed_out"},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction=extraction,
            result_proposal=None,
        )
    except OSError as exc:
        finished_at = _now()
        native_logs = _persist_native_logs(workspace, "", str(exc))
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        extraction = _empty_agent_extraction("launch_failed", [str(exc)])
        extraction["contract"] = "codex_exec_v1"
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": 1, "reason": "launch_failed"},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction=extraction,
            result_proposal=None,
        )

    finished_at = _now()
    wall_time_ms = max(1, int((time.monotonic() - started_monotonic) * 1000))
    status = "completed" if completed.returncode == 0 else "failed"
    native_logs = _persist_native_logs(workspace, completed.stdout, completed.stderr)
    diff_metrics, diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    codex_metrics, codex_extraction = _extract_codex_jsonl(completed.stdout)
    outcome_metrics = _merge_outcome_metrics(
        _merge_outcome_metrics(_base_outcome_metrics(wall_time_ms=wall_time_ms), diff_metrics),
        codex_metrics,
    )
    extraction = _empty_agent_extraction("native_stream_captured", [])
    extraction["contract"] = "codex_exec_v1"
    extraction["parsed_fields"] = ["effective_model", "effective_provider"]
    extraction["effective_model"] = binding.model
    extraction["effective_provider"] = binding.provider_id
    extraction["warnings"].extend(codex_extraction.get("warnings", []))
    extraction["parsed_fields"].extend(_string_list_value(codex_extraction.get("parsed_fields")))
    assistant_text = _string_or_none(codex_extraction.get("assistant_text"))
    if assistant_text is not None:
        extraction["assistant_text"] = assistant_text
    for field in (
        "result_status",
        "review_status",
        "emitted_events",
        "artifacts",
        "verification",
        "native_log_refs",
        "mutation_proposal_refs",
    ):
        if field in codex_extraction:
            extraction[field] = codex_extraction[field]
    extraction["diff_refs"] = diff_refs
    extraction["outcome_metrics"] = outcome_metrics
    extraction["missing_fields"] = _missing_usage_fields(outcome_metrics)
    result_proposal = None
    if completed.returncode == 0:
        result_status = _string_or_none(codex_extraction.get("result_status")) or "completed"
        review_status = _string_or_none(codex_extraction.get("review_status"))
        result_proposal = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status=result_status,
            effective_model=binding.model,
            effective_provider=binding.provider_id,
            emitted_events=_string_list_value(codex_extraction.get("emitted_events")),
            artifacts=_mapping_list_value(codex_extraction.get("artifacts")),
            outcome_metrics=outcome_metrics,
            verification=_mapping_value(
                codex_extraction.get("verification"),
                default={"status": "not_run"},
            ),
            native_log_refs=_mapping_list_value(codex_extraction.get("native_log_refs")),
            mutation_proposal_refs=_string_list_value(
                codex_extraction.get("mutation_proposal_refs")
            ),
            review_status=review_status,
        ).to_dict()

    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        exit={"code": completed.returncode, "reason": status},
        native_logs=native_logs,
        diff_refs=diff_refs,
        artifacts=[],
        workspace=workspace,
        outcome_metrics=outcome_metrics,
        extraction=extraction,
        result_proposal=result_proposal,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_codex_assignment_prompt(assignment: AssignmentPacket) -> str:
    return "\n\n".join(
        [
            render_assignment_prompt(assignment),
            "\n".join(
                [
                    "## Output Contract",
                    "Return a YAML object as your final answer.",
                    "Required fields:",
                    "- status: completed | blocked | completed_with_proposal",
                    "- emitted_events: list of workflow events you actually satisfied",
                    "- verification: object with at least status",
                    "Optional fields:",
                    "- review_status",
                    "- mutation_proposal_refs",
                    "- artifacts",
                    "Use plain YAML scalars only. Do not use markdown backticks or code fences inside values.",
                    "Do not wrap the YAML in code fences.",
                ]
            ),
        ]
    )


def _terminal_event_type(status: str) -> str | None:
    if status == "timed_out":
        return "worker_timeout"
    if status == "cancelled":
        return "assignment_cancelled"
    if status == "superseded":
        return "assignment_superseded"
    return None


def _extract_shell_dummy_output(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    stdout: str,
) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        return _empty_shell_dummy_extraction("agent_does_not_emit_usage", [])

    if not _looks_structured(stripped):
        return _empty_shell_dummy_extraction("agent_does_not_emit_usage", [])

    extraction = _extract_structured_output(
        stripped,
        extracted_status="extracted",
        contract_name="shell_dummy_v1",
    )
    outcome_metrics = _mapping_value(extraction.get("outcome_metrics"))
    if (
        extraction["status"] == "extracted"
        and not any(field in outcome_metrics for field in ("input_tokens", "output_tokens", "total_tokens"))
    ):
        extraction["warnings"].append(
            f"{spec.agent_id} output for {assignment.assignment_id} omitted token usage fields"
        )
    return extraction


def _extract_structured_output(
    text: str,
    *,
    extracted_status: str,
    contract_name: str,
) -> dict[str, Any]:
    payload, parse_error = _parse_structured_yaml(text)
    if parse_error is not None:
        extraction = _empty_shell_dummy_extraction(
            "wrapper_failed_to_extract",
            [str(parse_error)],
        )
        extraction["contract"] = contract_name
        return extraction

    if not isinstance(payload, dict):
        extraction = _empty_shell_dummy_extraction(
            "wrapper_failed_to_extract",
            ["structured output must decode to a YAML object"],
        )
        extraction["contract"] = contract_name
        return extraction

    extraction = _empty_shell_dummy_extraction(extracted_status, [])
    extraction["contract"] = contract_name
    extraction["parsed_fields"] = []

    result_status = _string_or_none(payload.get("status"))
    if result_status is not None:
        extraction["result_status"] = result_status
        extraction["parsed_fields"].append("status")

    for field in ("effective_model", "effective_provider", "review_status"):
        value = _string_or_none(payload.get(field))
        if value is not None:
            extraction[field] = value
            extraction["parsed_fields"].append(field)

    emitted_events = _string_list_or_none(payload.get("emitted_events"))
    if emitted_events is not None:
        extraction["emitted_events"] = emitted_events
        extraction["parsed_fields"].append("emitted_events")

    artifacts = _mapping_list_or_none(payload.get("artifacts"))
    if artifacts is not None:
        extraction["artifacts"] = artifacts
        extraction["parsed_fields"].append("artifacts")

    verification = payload.get("verification")
    if isinstance(verification, dict):
        extraction["verification"] = verification
        extraction["parsed_fields"].append("verification")

    native_log_refs = _mapping_list_or_none(payload.get("native_log_refs"))
    if native_log_refs is not None:
        extraction["native_log_refs"] = native_log_refs
        extraction["parsed_fields"].append("native_log_refs")

    mutation_proposal_refs = _string_list_or_none(
        payload.get("mutation_proposal_refs")
    )
    if mutation_proposal_refs is not None:
        extraction["mutation_proposal_refs"] = mutation_proposal_refs
        extraction["parsed_fields"].append("mutation_proposal_refs")

    diff_refs = _mapping_list_or_none(payload.get("diff_refs"))
    if diff_refs is not None:
        extraction["diff_refs"] = diff_refs
        extraction["parsed_fields"].append("diff_refs")

    changed_files = _string_list_or_none(payload.get("changed_files"))
    patch = payload.get("patch") if isinstance(payload.get("patch"), str) else None

    outcome_metrics = {}
    if isinstance(payload.get("outcome_metrics"), dict):
        outcome_metrics = dict(payload["outcome_metrics"])
        extraction["parsed_fields"].append("outcome_metrics")

    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
        "cost_source",
        "cost_confidence",
        "usage_confidence",
        "changed_files_count",
        "patch_bytes",
    ):
        if field in payload:
            outcome_metrics[field] = payload[field]
            extraction["parsed_fields"].append(field)

    if "changed_files_count" not in outcome_metrics and changed_files is not None:
        outcome_metrics["changed_files_count"] = len(changed_files)
        extraction["parsed_fields"].append("changed_files")

    if "patch_bytes" not in outcome_metrics and patch is not None:
        outcome_metrics["patch_bytes"] = len(patch.encode("utf-8"))
        extraction["parsed_fields"].append("patch")

    if "total_tokens" not in outcome_metrics:
        input_tokens = outcome_metrics.get("input_tokens")
        output_tokens = outcome_metrics.get("output_tokens")
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            outcome_metrics["total_tokens"] = input_tokens + output_tokens

    if patch is not None and not extraction["diff_refs"]:
        extraction["diff_refs"] = [
            {
                "kind": "inline_patch",
                "bytes": outcome_metrics.get("patch_bytes", len(patch.encode("utf-8"))),
            }
        ]
        extraction["parsed_fields"].append("diff_refs.inline_patch")

    extraction["outcome_metrics"] = outcome_metrics
    extraction["missing_fields"] = _missing_usage_fields(outcome_metrics)
    return extraction


def _parse_structured_yaml(text: str) -> tuple[dict[str, Any] | Any, yaml.YAMLError | None]:
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as exc:
        sanitized = text.replace("`", "'")
        if sanitized != text:
            try:
                return yaml.safe_load(sanitized), None
            except yaml.YAMLError:
                pass
        return None, exc


def _prepare_session_workspace(spec: SessionSpec, source_root: Path) -> dict[str, Any]:
    session_root = source_root / ".bureauless" / "sessions" / spec.session_id
    session_root.mkdir(parents=True, exist_ok=True)
    workspace_path = session_root / "workspace"
    warnings: list[str] = []
    actual_mode = spec.isolation_mode

    if spec.isolation_mode == "worktree":
        worktree_result = _prepare_git_worktree(source_root, workspace_path)
        if worktree_result["ok"]:
            actual_mode = "worktree"
        else:
            warnings.extend(_string_list_value(worktree_result.get("warnings")))
            actual_mode = "copy"

    if actual_mode == "copy":
        _prepare_copy_workspace(source_root, workspace_path)

    return {
        "mode": actual_mode,
        "requested_mode": spec.isolation_mode,
        "source_root": str(source_root),
        "path": str(workspace_path),
        "session_root": str(session_root),
        "cleanup_policy": spec.cleanup_policy,
        "retained_paths": [str(workspace_path)],
        "warnings": warnings,
    }


def _prepare_copy_workspace(source_root: Path, workspace_path: Path) -> None:
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    shutil.copytree(
        source_root,
        workspace_path,
        ignore=shutil.ignore_patterns(".bureauless"),
    )


def _prepare_git_worktree(source_root: Path, workspace_path: Path) -> dict[str, Any]:
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    probe = probe_git_worktree(source_root)
    if not probe["ok"]:
        return probe
    env = git_environment(source_root)
    add = subprocess.run(
        ["git", "worktree", "add", "--detach", str(workspace_path), "HEAD"],
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if add.returncode != 0:
        warning = add.stderr.strip() or add.stdout.strip() or "git worktree add failed"
        return {"ok": False, "warnings": [warning]}
    return {"ok": True, "warnings": []}


def _persist_native_logs(
    workspace: dict[str, Any],
    stdout: str | bytes,
    stderr: str | bytes,
) -> dict[str, str]:
    session_root = Path(_as_string(workspace, "session_root"))
    logs_dir = session_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "stdout.log"
    stderr_path = logs_dir / "stderr.log"
    stdout_text = _text_value(stdout)
    stderr_text = _text_value(stderr)
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    retained_paths = list(_string_list_value(workspace.get("retained_paths")))
    for path in (str(stdout_path), str(stderr_path)):
        if path not in retained_paths:
            retained_paths.append(path)
    workspace["retained_paths"] = retained_paths
    return {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _empty_shell_dummy_extraction(status: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "contract": "shell_dummy_v1",
        "status": status,
        "warnings": warnings,
        "parsed_fields": [],
        "missing_fields": [
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_usd",
        ],
        "emitted_events": [],
        "artifacts": [],
        "verification": {"status": "not_run"},
        "native_log_refs": [],
        "diff_refs": [],
        "outcome_metrics": {},
    }


def _empty_agent_extraction(status: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "contract": "agent_session_v1",
        "status": status,
        "warnings": warnings,
        "parsed_fields": [],
        "missing_fields": [
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_usd",
        ],
        "emitted_events": [],
        "artifacts": [],
        "verification": {"status": "not_run"},
        "native_log_refs": [],
        "diff_refs": [],
        "outcome_metrics": {},
    }


def _base_outcome_metrics(wall_time_ms: int) -> dict[str, Any]:
    return {
        "wall_time_ms": wall_time_ms,
        "changed_files_count": 0,
        "usage_confidence": "none",
        "cost_source": "agent_not_supported",
        "cost_confidence": "none",
    }


def _merge_outcome_metrics(
    base_metrics: dict[str, Any],
    extracted_metrics: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base_metrics)
    merged.update(extracted_metrics)
    if (
        "total_tokens" not in merged
        and isinstance(merged.get("input_tokens"), int)
        and isinstance(merged.get("output_tokens"), int)
    ):
        merged["total_tokens"] = merged["input_tokens"] + merged["output_tokens"]
    return merged


def _build_codex_environment(binding: Any) -> dict[str, str]:
    env = os.environ.copy()
    if binding.api_key_env:
        value = env.get(binding.api_key_env)
        if value is None:
            raise ProtocolError(
                f"Session provider_api_key_env is not set in the environment: {binding.api_key_env}"
            )
        env["OPENAI_API_KEY"] = value
    return env


def _prepare_codex_home(
    workspace: dict[str, Any],
    binding: Any,
    env: dict[str, str],
) -> Path:
    session_root = Path(_as_string(workspace, "session_root"))
    codex_home = session_root / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    auth_payload = {"OPENAI_API_KEY": env.get("OPENAI_API_KEY")}
    (codex_home / "auth.json").write_text(
        json.dumps(auth_payload),
        encoding="utf-8",
    )
    env["CODEX_HOME"] = str(codex_home)
    return codex_home


def _cleanup_codex_home(codex_home: Path) -> None:
    shutil.rmtree(codex_home, ignore_errors=True)


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)


def _build_codex_command(spec: SessionSpec, binding: Any, workdir: Path) -> list[str]:
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "--ignore-user-config",
        "--ephemeral",
        "--cd",
        str(workdir),
        "--sandbox",
        "workspace-write",
        "--model",
        binding.model,
    ]
    for key, value in binding.codex_config_overrides.items():
        command.extend(["-c", f"{key}={_toml_literal(value)}"])
    return command


def _run_command_runner(
    command_runner: CommandRunner | None,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    input_text: str,
) -> subprocess.CompletedProcess[str]:
    runner = command_runner or subprocess.run
    return runner(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        input=input_text,
    )


def _collect_workspace_diff(workdir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    changed_files_count = 0
    patch_bytes = 0
    diff_refs: list[dict[str, Any]] = []

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode == 0:
        changed_files_count = len([line for line in status.stdout.splitlines() if line.strip()])

    patch = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if patch.returncode == 0 and patch.stdout:
        patch_bytes = len(patch.stdout.encode("utf-8"))
        diff_refs.append({"kind": "inline_patch", "bytes": patch_bytes})

    metrics: dict[str, Any] = {"changed_files_count": changed_files_count}
    if patch_bytes:
        metrics["patch_bytes"] = patch_bytes
    return metrics, diff_refs


@dataclass(frozen=True)
class WorkspaceBaseline:
    files: dict[str, str]
    git_dirty: bool


def _capture_workspace_baseline(workdir: Path) -> WorkspaceBaseline:
    return WorkspaceBaseline(
        files=_snapshot_workspace_files(workdir),
        git_dirty=_workspace_git_dirty(workdir),
    )


def _set_workspace_state_refs(
    workspace: dict[str, Any],
    pre_files: dict[str, str],
    post_files: dict[str, str] | None = None,
) -> None:
    workspace["pre_state_ref"] = _workspace_state_ref(pre_files)
    workspace["post_state_ref"] = _workspace_state_ref(post_files or pre_files)


def _workspace_state_ref(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, file_hash in sorted(files.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("utf-8"))
        digest.update(b"\0")
    return f"workspace:{digest.hexdigest()}"


def _collect_workspace_delta(
    workdir: Path,
    baseline: WorkspaceBaseline,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    current_files = _snapshot_workspace_files(workdir)
    changed_files = {
        path
        for path in set(baseline.files) | set(current_files)
        if baseline.files.get(path) != current_files.get(path)
    }
    metrics: dict[str, Any] = {"changed_files_count": len(changed_files)}
    if baseline.git_dirty:
        return metrics, []

    diff_metrics, diff_refs = _collect_workspace_diff(workdir)
    patch_bytes = diff_metrics.get("patch_bytes", 0)

    added_files = sorted(set(current_files) - set(baseline.files))
    if added_files:
        added_patch_bytes = _collect_untracked_patch_bytes(workdir, added_files)
        patch_bytes += added_patch_bytes

    if patch_bytes:
        metrics["patch_bytes"] = patch_bytes
        if not diff_refs:
            diff_refs = [{"kind": "inline_patch", "bytes": patch_bytes}]
        elif added_files:
            diff_refs = [{"kind": "inline_patch", "bytes": patch_bytes}]
    return metrics, diff_refs


def _extract_codex_jsonl(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    extraction: dict[str, Any] = {"warnings": [], "parsed_fields": []}
    assistant_text: str | None = None

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            extraction["warnings"].append("codex_jsonl_line_unparseable")
            continue
        if not isinstance(payload, dict):
            continue

        item = payload.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = _string_or_none(item.get("text"))
            if text is not None:
                assistant_text = text

        if payload.get("type") != "turn.completed":
            continue
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        if isinstance(usage.get("input_tokens"), int):
            metrics["input_tokens"] = usage["input_tokens"]
            extraction["parsed_fields"].append("usage.input_tokens")
        if isinstance(usage.get("output_tokens"), int):
            metrics["output_tokens"] = usage["output_tokens"]
            extraction["parsed_fields"].append("usage.output_tokens")
        if isinstance(usage.get("cached_input_tokens"), int):
            metrics["cached_input_tokens"] = usage["cached_input_tokens"]
            extraction["parsed_fields"].append("usage.cached_input_tokens")
        if isinstance(usage.get("reasoning_output_tokens"), int):
            metrics["reasoning_output_tokens"] = usage["reasoning_output_tokens"]
            extraction["parsed_fields"].append("usage.reasoning_output_tokens")

    if "input_tokens" in metrics or "output_tokens" in metrics:
        metrics["usage_confidence"] = "high"
    if assistant_text is not None:
        extraction["assistant_text"] = assistant_text
        extraction["parsed_fields"].append("item.agent_message.text")
        if _looks_structured(assistant_text.strip()):
            structured = _extract_structured_output(
                assistant_text.strip(),
                extracted_status="extracted",
                contract_name="codex_exec_v1",
            )
            extraction["warnings"].extend(_string_list_value(structured.get("warnings")))
            extraction["parsed_fields"].extend(_string_list_value(structured.get("parsed_fields")))
            for field in (
                "result_status",
                "review_status",
                "emitted_events",
                "artifacts",
                "verification",
                "native_log_refs",
                "mutation_proposal_refs",
            ):
                if field in structured:
                    extraction[field] = structured[field]
            structured_metrics = _mapping_value(structured.get("outcome_metrics"))
            if structured_metrics:
                extraction["outcome_metrics"] = structured_metrics
                for key, value in structured_metrics.items():
                    metrics.setdefault(key, value)
    return metrics, extraction


def _snapshot_workspace_files(workdir: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for root, dirnames, filenames in os.walk(workdir):
        root_path = Path(root)
        rel_root = root_path.relative_to(workdir)
        dirnames[:] = [
            name
            for name in dirnames
            if (rel_root / name).as_posix() not in {".git", ".bureauless"}
        ]
        for filename in filenames:
            rel_path = (rel_root / filename).as_posix()
            if rel_path.startswith(".git/") or rel_path.startswith(".bureauless/"):
                continue
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            snapshot[rel_path] = sha256_file(file_path)
    return snapshot


def _workspace_git_dirty(workdir: Path) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        return False
    return any(line.strip() for line in status.stdout.splitlines())


def _collect_untracked_patch_bytes(workdir: Path, added_files: list[str]) -> int:
    total = 0
    for rel_path in added_files:
        file_path = workdir / rel_path
        diff = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--no-ext-diff", "--", "/dev/null", str(file_path)],
            cwd=workdir,
            check=False,
            capture_output=True,
            text=False,
        )
        if diff.stdout:
            total += len(diff.stdout)
    return total


def _missing_usage_fields(outcome_metrics: dict[str, Any]) -> list[str]:
    missing = []
    for field in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"):
        if field not in outcome_metrics:
            missing.append(field)
    return missing


def _looks_structured(text: str) -> bool:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return False
    if first_line.startswith("{"):
        return True
    key, separator, remainder = first_line.partition(":")
    return bool(separator and key and remainder is not None)


def _unprepared_workspace_record(spec: SessionSpec) -> dict[str, Any]:
    source_root = str(Path(spec.workdir).resolve())
    return {
        "mode": "none",
        "requested_mode": spec.isolation_mode,
        "source_root": source_root,
        "path": source_root,
        "session_root": "",
        "cleanup_policy": spec.cleanup_policy,
        "retained_paths": [],
        "warnings": [],
    }


def _packaging_roots(record: SessionRecord, artifact_root: Path | None) -> tuple[Path, Path]:
    if artifact_root is not None:
        root = artifact_root.resolve()
        return root, root
    session_root = _string_or_none(record.workspace.get("session_root"))
    workspace_path = _string_or_none(record.workspace.get("path"))
    if session_root is not None and workspace_path is not None:
        return Path(session_root).resolve(), Path(workspace_path).resolve()
    workspace_path = _string_or_none(record.workspace.get("path"))
    if workspace_path is not None:
        root = Path(workspace_path).resolve()
        return root, root
    source_root = _string_or_none(record.workspace.get("source_root"))
    if source_root is not None:
        root = Path(source_root).resolve()
        return root, root
    raise ProtocolError("Packaging requires an artifact_root or a session workspace path")


def _accepted_workspace_ref_for_node(ledger: Any, node_id: str) -> str | None:
    projection = ledger.projection if hasattr(ledger, "projection") else {}
    projected_cursor = _string_or_none(projection.get("through_event_id"))
    event_log = getattr(ledger, "event_log", [])
    last_event_id = (
        _string_or_none(event_log[-1].get("event_id")) if event_log else None
    )
    projected = _string_or_none(projection.get("accepted_workspace_ref"))
    if projected is not None and projected_cursor == last_event_id:
        latest_node_event = next(
            (
                event
                for event in reversed(event_log)
                if event.get("event_type") == "node_outcome_decided"
                and event.get("node_id") == node_id
                and event.get("disposition") in {"accepted", "partially_accepted"}
            ),
            None,
        )
        if latest_node_event is not None:
            post_state_ref = _string_or_none(latest_node_event.get("post_state_ref"))
            if post_state_ref is not None:
                return post_state_ref
    for event in reversed(event_log):
        if event.get("event_type") != "node_outcome_decided":
            continue
        if event.get("node_id") != node_id:
            continue
        if event.get("disposition") not in {"accepted", "partially_accepted"}:
            continue
        post_state_ref = _string_or_none(event.get("post_state_ref"))
        if post_state_ref is not None:
            return post_state_ref
    return None


def _normalize_packaged_artifact(
    artifact: dict[str, Any],
    *,
    package_root: Path,
    workspace_root: Path,
    source_event: str,
    created_by: str,
    fallback_id: str,
) -> dict[str, Any]:
    artifact_path = _string_or_none(artifact.get("path"))
    if artifact_path is None:
        raise ProtocolError("Session artifact is missing required field: path")
    resolved_path, relative_path = _resolve_artifact_path(
        package_root,
        artifact_path,
        candidate_roots=[workspace_root, package_root],
    )
    if not resolved_path.exists():
        raise ProtocolError(f"Session artifact file is missing: {relative_path}")

    actual_hash = sha256_file(resolved_path)
    recorded_hash = _string_or_none(artifact.get("sha256"))
    if recorded_hash is not None and recorded_hash != actual_hash:
        raise ProtocolError(f"Session artifact hash does not match file contents: {relative_path}")

    return {
        "artifact_id": _string_or_none(artifact.get("artifact_id")) or fallback_id,
        "path": relative_path,
        "sha256": actual_hash,
        "created_by": _string_or_none(artifact.get("created_by")) or created_by,
        "source_event": source_event,
        "mutable": False,
    }


def _package_native_log_refs(
    record: SessionRecord,
    package_root: Path,
    source_event: str,
    result_id: str,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for kind in ("stdout", "stderr"):
        path_key = f"{kind}_path"
        native_path = _string_or_none(record.native_logs.get(path_key))
        if native_path is None:
            continue
        resolved_path, relative_path = _resolve_artifact_path(package_root, native_path)
        if not resolved_path.exists():
            raise ProtocolError(f"Native log file is missing: {relative_path}")
        refs.append(
            {
                "artifact_id": f"artifact-{result_id}-native-{kind}",
                "kind": kind,
                "path": relative_path,
                "sha256": sha256_file(resolved_path),
                "created_by": record.agent_id,
                "source_event": source_event,
                "mutable": False,
            }
        )
    return refs


def _resolve_artifact_path(
    root: Path,
    artifact_path: str,
    candidate_roots: list[Path] | None = None,
) -> tuple[Path, str]:
    candidate = Path(artifact_path)
    resolved_path: Path | None = None
    if candidate.is_absolute():
        resolved_path = candidate.resolve()
    else:
        for candidate_root in candidate_roots or [root]:
            trial = (candidate_root / candidate).resolve()
            try:
                trial.relative_to(root)
            except ValueError:
                continue
            if trial.exists():
                resolved_path = trial
                break
        if resolved_path is None:
            resolved_path = ((candidate_roots or [root])[0] / candidate).resolve()
    try:
        relative_path = str(resolved_path.relative_to(root))
    except ValueError as exc:
        raise ProtocolError(f"Artifact path escapes packaging root: {artifact_path}") from exc
    return resolved_path, relative_path


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"Session field {key!r} must be a string")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Session field {key!r} must be an object")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Session field {key!r} must be a list of objects")
    return value


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _text_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def _string_value(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _string_list_value(value: Any) -> list[str]:
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def _string_list_or_none(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return None


def _mapping_list_or_none(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    return None


def _mapping_value(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return default or {}


def _mapping_list_value(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) and all(isinstance(item, dict) for item in value) else []
