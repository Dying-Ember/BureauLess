from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from typing import Callable

from ..core import ProtocolError


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    binary: str
    kind: str
    help_args: list[str]
    version_args: list[str]
    non_interactive_markers: list[str]
    model_override_markers: list[str]
    provider_override_markers: list[str]
    config_isolation_markers: list[str]
    working_directory_markers: list[str]
    output_stream_markers: list[str]
    persistence_markers: list[str]
    cancellation: str
    metrics_capability: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "binary": self.binary,
            "kind": self.kind,
            "help_args": self.help_args,
            "version_args": self.version_args,
            "cancellation": self.cancellation,
            "metrics_capability": self.metrics_capability,
        }


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    markers: list[str]
    missing_markers: list[str]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "markers": self.markers,
            "missing_markers": self.missing_markers,
        }


@dataclass(frozen=True)
class DoctorResult:
    agent_id: str
    status: str
    control_level: str
    binary: str
    binary_path: str | None
    version: str | None
    checks: list[DoctorCheck]
    warnings: list[str]
    metrics_capability: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "control_level": self.control_level,
            "binary": self.binary,
            "binary_path": self.binary_path,
            "version": self.version,
            "checks": [check.to_dict() for check in self.checks],
            "warnings": self.warnings,
            "metrics_capability": self.metrics_capability,
        }


AGENT_SPECS: dict[str, AgentSpec] = {
    "codex-cli": AgentSpec(
        agent_id="codex-cli",
        binary="codex",
        kind="local_agent_cli",
        help_args=["exec", "--help"],
        version_args=["--version"],
        non_interactive_markers=["exec"],
        model_override_markers=["--model"],
        provider_override_markers=["--config"],
        config_isolation_markers=["--ignore-user-config"],
        working_directory_markers=["--cd"],
        output_stream_markers=["--json"],
        persistence_markers=["--ephemeral"],
        cancellation="process_kill",
        metrics_capability={
            "wall_time": "required",
            "final_status": "required",
            "changed_files": "required",
            "token_usage": "optional",
            "cost_usage": "optional",
        },
    ),
    "claude-code": AgentSpec(
        agent_id="claude-code",
        binary="claude",
        kind="local_agent_cli",
        help_args=["--help"],
        version_args=["--version"],
        non_interactive_markers=["--print"],
        model_override_markers=["--model"],
        provider_override_markers=["--settings"],
        config_isolation_markers=["--setting-sources", "--bare"],
        working_directory_markers=["--worktree", "--add-dir"],
        output_stream_markers=["--output-format"],
        persistence_markers=["--no-session-persistence"],
        cancellation="process_kill",
        metrics_capability={
            "wall_time": "required",
            "final_status": "required",
            "changed_files": "required",
            "token_usage": "optional",
            "cost_usage": "optional",
        },
    ),
    "opencode": AgentSpec(
        agent_id="opencode",
        binary="opencode",
        kind="local_agent_cli",
        help_args=["run", "--help"],
        version_args=["--version"],
        non_interactive_markers=["run"],
        model_override_markers=["--model"],
        provider_override_markers=["--model"],
        config_isolation_markers=["--pure"],
        working_directory_markers=["--dir"],
        output_stream_markers=["--format"],
        persistence_markers=["--session", "--fork"],
        cancellation="process_kill",
        metrics_capability={
            "wall_time": "required",
            "final_status": "required",
            "changed_files": "required",
            "token_usage": "optional",
            "cost_usage": "optional",
        },
    ),
}


def list_agent_specs() -> list[AgentSpec]:
    return [AGENT_SPECS[agent_id] for agent_id in sorted(AGENT_SPECS)]


def get_agent_spec(agent_id: str) -> AgentSpec:
    try:
        return AGENT_SPECS[agent_id]
    except KeyError as exc:
        raise ProtocolError(f"Unknown agent id: {agent_id}") from exc


def doctor_agent(
    agent_id: str,
    which: Callable[[str], str | None] = shutil.which,
    run_command: Callable[[list[str]], CommandOutput] | None = None,
) -> DoctorResult:
    spec = get_agent_spec(agent_id)
    binary_path = which(spec.binary)
    if binary_path is None:
        return DoctorResult(
            agent_id=spec.agent_id,
            status="unavailable",
            control_level="none",
            binary=spec.binary,
            binary_path=None,
            version=None,
            checks=[],
            warnings=[f"Binary not found on PATH: {spec.binary}"],
            metrics_capability=spec.metrics_capability,
        )

    if run_command is None:
        run_command = _run_command

    help_output = run_command([binary_path, *spec.help_args])
    version_output = run_command([binary_path, *spec.version_args])
    help_text = f"{help_output.stdout}\n{help_output.stderr}"
    version_text = _first_line(f"{version_output.stdout}\n{version_output.stderr}")

    checks = [
        _marker_check("non_interactive", spec.non_interactive_markers, help_text),
        _marker_check("model_override", spec.model_override_markers, help_text),
        _marker_check("provider_override", spec.provider_override_markers, help_text),
        _marker_check("config_isolation", spec.config_isolation_markers, help_text),
        _marker_check("working_directory", spec.working_directory_markers, help_text),
        _marker_check("output_stream", spec.output_stream_markers, help_text),
        _marker_check("session_persistence", spec.persistence_markers, help_text),
    ]
    warnings: list[str] = []
    if help_output.returncode != 0:
        warnings.append(f"Help command exited with {help_output.returncode}")
    if version_output.returncode != 0:
        warnings.append(f"Version command exited with {version_output.returncode}")

    required_names = {
        "non_interactive",
        "model_override",
        "working_directory",
        "output_stream",
    }
    failed_required = [
        check.name
        for check in checks
        if check.name in required_names and check.status != "passed"
    ]
    failed_optional = [
        check.name
        for check in checks
        if check.name not in required_names and check.status != "passed"
    ]

    if help_output.returncode != 0 or failed_required:
        status = "degraded"
        control_level = "low"
    elif failed_optional:
        status = "usable"
        control_level = "medium"
    else:
        status = "usable"
        control_level = "high"

    return DoctorResult(
        agent_id=spec.agent_id,
        status=status,
        control_level=control_level,
        binary=spec.binary,
        binary_path=binary_path,
        version=version_text or None,
        checks=checks,
        warnings=warnings,
        metrics_capability=spec.metrics_capability,
    )


def _marker_check(name: str, markers: list[str], text: str) -> DoctorCheck:
    missing = [marker for marker in markers if marker not in text]
    return DoctorCheck(
        name=name,
        status="passed" if not missing else "failed",
        markers=markers,
        missing_markers=missing,
    )


def _run_command(command: list[str]) -> CommandOutput:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandOutput(returncode=1, stdout="", stderr=str(exc))
    return CommandOutput(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
