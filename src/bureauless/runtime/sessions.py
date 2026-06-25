from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from uuid import uuid4

import yaml

from ..core import ProtocolError
from ..protocol.artifacts import sha256_file
from ..protocol.assignments import AssignmentPacket
from ..protocol.harness import Workflow
from ..protocol.results import ResultProposal, load_result_proposal
from ..runtime_workspace import (
    WorkspaceReadiness,
    assess_workspace_isolation,
    git_environment,
    probe_git_worktree,
)


SUPPORTED_SESSION_AGENTS = {"fake", "shell-dummy"}


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
    session_id: str | None = None,
) -> SessionSpec:
    if agent_id not in SUPPORTED_SESSION_AGENTS:
        raise ProtocolError(f"Unsupported session agent: {agent_id}")
    if isolation_mode not in {"copy", "worktree"}:
        raise ProtocolError(f"Unsupported isolation_mode: {isolation_mode}")
    if agent_id == "shell-dummy" and not dry_run and not shell_command:
        raise ProtocolError("shell-dummy session requires --shell-command")
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
    )


def run_session(spec: SessionSpec, assignment: AssignmentPacket) -> SessionRecord:
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
        review_status=base.review_status,
    )


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
    outcome_metrics = _merge_outcome_metrics(
        _base_outcome_metrics(wall_time_ms=wall_time_ms),
        _as_mapping(extraction, "outcome_metrics", default={}),
    )
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    try:
        payload = yaml.safe_load(stripped)
    except yaml.YAMLError as exc:
        return _empty_shell_dummy_extraction("wrapper_failed_to_extract", [str(exc)])

    if not isinstance(payload, dict):
        return _empty_shell_dummy_extraction(
            "wrapper_failed_to_extract",
            ["structured output must decode to a YAML object"],
        )

    extraction = _empty_shell_dummy_extraction("extracted", [])
    extraction["contract"] = "shell_dummy_v1"
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
    if (
        extraction["status"] == "extracted"
        and not any(field in outcome_metrics for field in ("input_tokens", "output_tokens", "total_tokens"))
    ):
        extraction["warnings"].append(
            f"{spec.agent_id} output for {assignment.assignment_id} omitted token usage fields"
        )
    return extraction


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
    stdout: str,
    stderr: str,
) -> dict[str, str]:
    session_root = Path(_as_string(workspace, "session_root"))
    logs_dir = session_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "stdout.log"
    stderr_path = logs_dir / "stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    retained_paths = list(_string_list_value(workspace.get("retained_paths")))
    for path in (str(stdout_path), str(stderr_path)):
        if path not in retained_paths:
            retained_paths.append(path)
    workspace["retained_paths"] = retained_paths
    return {
        "stdout": stdout,
        "stderr": stderr,
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
