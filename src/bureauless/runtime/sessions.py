from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time
from typing import Any
from uuid import uuid4

from ..core import ProtocolError
from ..protocol.assignments import AssignmentPacket
from ..protocol.results import ResultProposal


SUPPORTED_SESSION_AGENTS = {"fake", "shell-dummy"}


@dataclass(frozen=True)
class SessionSpec:
    session_id: str
    assignment_id: str
    agent_id: str
    workdir: str
    timeout_seconds: float
    dry_run: bool
    shell_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "agent_id": self.agent_id,
            "workdir": self.workdir,
            "timeout_seconds": self.timeout_seconds,
            "dry_run": self.dry_run,
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
    outcome_metrics: dict[str, Any]
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
            "outcome_metrics": self.outcome_metrics,
            "result_proposal": self.result_proposal,
        }


def create_session_spec(
    assignment: AssignmentPacket,
    agent_id: str,
    workdir: Path,
    timeout_seconds: float = 30.0,
    dry_run: bool = False,
    shell_command: str | None = None,
    session_id: str | None = None,
) -> SessionSpec:
    if agent_id not in SUPPORTED_SESSION_AGENTS:
        raise ProtocolError(f"Unsupported session agent: {agent_id}")
    if agent_id == "shell-dummy" and not dry_run and not shell_command:
        raise ProtocolError("shell-dummy session requires --shell-command")
    return SessionSpec(
        session_id=session_id or f"session-{uuid4()}",
        assignment_id=assignment.assignment_id,
        agent_id=agent_id,
        workdir=str(workdir),
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        shell_command=shell_command,
    )


def run_session(spec: SessionSpec, assignment: AssignmentPacket) -> SessionRecord:
    if assignment.assignment_id != spec.assignment_id:
        raise ProtocolError("Session assignment_id does not match assignment packet")

    started_at = _now()
    started_monotonic = time.monotonic()

    if spec.dry_run:
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
            outcome_metrics={"wall_time_ms": 0, "changed_files_count": 0},
            result_proposal=None,
        )

    if spec.agent_id == "fake":
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status="completed",
            emitted_events=assignment.expected_events,
            artifacts=[],
            outcome_metrics={
                "wall_time_ms": max(1, int((time.monotonic() - started_monotonic) * 1000)),
                "changed_files_count": 0,
            },
            verification={"status": "not_run"},
            native_log_refs=[],
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
            outcome_metrics=result.outcome_metrics,
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
        outcome_metrics=_as_mapping(data, "outcome_metrics", default={}),
        result_proposal=data.get("result_proposal"),
    )


def _run_shell_dummy_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
) -> SessionRecord:
    workdir = Path(spec.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
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
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="timed_out",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": None, "reason": "timed_out"},
            native_logs={"stdout": exc.stdout or "", "stderr": exc.stderr or ""},
            diff_refs=[],
            artifacts=[],
            outcome_metrics={
                "wall_time_ms": max(1, int((time.monotonic() - started_monotonic) * 1000)),
                "changed_files_count": 0,
            },
            result_proposal=None,
        )
    except OSError as exc:
        finished_at = _now()
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": 1, "reason": "launch_failed"},
            native_logs={"stdout": "", "stderr": str(exc)},
            diff_refs=[],
            artifacts=[],
            outcome_metrics={
                "wall_time_ms": max(1, int((time.monotonic() - started_monotonic) * 1000)),
                "changed_files_count": 0,
            },
            result_proposal=None,
        )

    finished_at = _now()
    status = "completed" if completed.returncode == 0 else "failed"
    result_proposal = None
    if completed.returncode == 0:
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status="completed",
            emitted_events=assignment.expected_events,
            artifacts=[],
            outcome_metrics={
                "wall_time_ms": max(1, int((time.monotonic() - started_monotonic) * 1000)),
                "changed_files_count": 0,
            },
            verification={"status": "not_run"},
            native_log_refs=[],
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
        native_logs={"stdout": completed.stdout, "stderr": completed.stderr},
        diff_refs=[],
        artifacts=[],
        outcome_metrics={
            "wall_time_ms": max(1, int((time.monotonic() - started_monotonic) * 1000)),
            "changed_files_count": 0,
        },
        result_proposal=result_proposal,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
