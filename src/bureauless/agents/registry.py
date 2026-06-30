from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable

from ..errors import ProtocolError
from ..runtime_workspace import WorkspaceReadiness, assess_workspace_isolation


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
class ProviderProfile:
    provider_id: str
    kind: str
    default_api_key_env: str | None
    requires_base_url: bool
    supports_base_url_override: bool
    default_wire_api: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind,
            "default_api_key_env": self.default_api_key_env,
            "requires_base_url": self.requires_base_url,
            "supports_base_url_override": self.supports_base_url_override,
            "default_wire_api": self.default_wire_api,
        }


@dataclass(frozen=True)
class AgentBinding:
    agent_id: str
    provider_id: str
    model: str
    api_key_env: str | None
    base_url: str | None
    wire_api: str | None
    codex_config_overrides: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "provider_id": self.provider_id,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "wire_api": self.wire_api,
            "codex_config_overrides": self.codex_config_overrides,
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


@dataclass(frozen=True)
class AgentCompatibility:
    agent_id: str
    compatibility_state: str
    control_level: str
    binary_path: str | None
    version: str | None
    capabilities: dict[str, str]
    reasons: list[str]
    warnings: list[str]
    metrics_capability: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "compatibility_state": self.compatibility_state,
            "control_level": self.control_level,
            "binary_path": self.binary_path,
            "version": self.version,
            "capabilities": self.capabilities,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "metrics_capability": self.metrics_capability,
        }


@dataclass(frozen=True)
class DispatchReadiness:
    agent_id: str
    readiness_state: str
    compatibility_state: str
    control_level: str
    binary_path: str | None
    version: str | None
    isolation: WorkspaceReadiness
    reasons: list[str]
    warnings: list[str]
    capabilities: dict[str, str]
    metrics_capability: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "readiness_state": self.readiness_state,
            "compatibility_state": self.compatibility_state,
            "control_level": self.control_level,
            "binary_path": self.binary_path,
            "version": self.version,
            "isolation": self.isolation.to_dict(),
            "reasons": self.reasons,
            "warnings": self.warnings,
            "capabilities": self.capabilities,
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

PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        provider_id="openai",
        kind="codex_builtin_openai",
        default_api_key_env="OPENAI_API_KEY",
        requires_base_url=False,
        supports_base_url_override=True,
    ),
    "openai-compatible": ProviderProfile(
        provider_id="openai-compatible",
        kind="codex_custom_openai_compatible",
        default_api_key_env=None,
        requires_base_url=True,
        supports_base_url_override=True,
        default_wire_api="responses",
    ),
}

AGENT_PROVIDER_BINDINGS: dict[str, set[str]] = {
    "codex-cli": {"openai", "openai-compatible"},
}


def list_agent_specs() -> list[AgentSpec]:
    return [AGENT_SPECS[agent_id] for agent_id in sorted(AGENT_SPECS)]


def get_agent_spec(agent_id: str) -> AgentSpec:
    try:
        return AGENT_SPECS[agent_id]
    except KeyError as exc:
        raise ProtocolError(f"Unknown agent id: {agent_id}") from exc


def list_provider_profiles() -> list[ProviderProfile]:
    return [PROVIDER_PROFILES[provider_id] for provider_id in sorted(PROVIDER_PROFILES)]


def get_provider_profile(provider_id: str) -> ProviderProfile:
    try:
        return PROVIDER_PROFILES[provider_id]
    except KeyError as exc:
        raise ProtocolError(f"Unknown provider id: {provider_id}") from exc


def resolve_agent_binding(
    agent_id: str,
    *,
    target_model: str,
    target_provider: str,
    provider_base_url: str | None = None,
    provider_api_key_env: str | None = None,
    provider_wire_api: str | None = None,
) -> AgentBinding:
    model = target_model.strip()
    if not model:
        raise ProtocolError("target_model must be a non-empty string")

    supported_providers = AGENT_PROVIDER_BINDINGS.get(agent_id)
    if supported_providers is None:
        raise ProtocolError(f"Agent does not support runtime provider bindings: {agent_id}")

    if target_provider not in supported_providers:
        allowed = ", ".join(sorted(supported_providers))
        raise ProtocolError(
            f"Provider {target_provider!r} is not supported for agent {agent_id!r}; allowed: {allowed}"
        )

    profile = get_provider_profile(target_provider)
    base_url = provider_base_url.strip() if isinstance(provider_base_url, str) else None
    if profile.requires_base_url and not base_url:
        raise ProtocolError(f"Provider {target_provider!r} requires provider_base_url")

    api_key_env = provider_api_key_env.strip() if isinstance(provider_api_key_env, str) else None
    if api_key_env is None:
        api_key_env = profile.default_api_key_env
    if target_provider == "openai-compatible" and not api_key_env:
        raise ProtocolError("Provider 'openai-compatible' requires provider_api_key_env")

    wire_api = provider_wire_api.strip() if isinstance(provider_wire_api, str) else None
    if wire_api is None:
        wire_api = profile.default_wire_api

    config_overrides: dict[str, Any] = {"model_provider": "openai"}
    if target_provider == "openai":
        if base_url:
            config_overrides["openai_base_url"] = base_url
    else:
        custom_provider_id = "bureauless"
        config_overrides = {
            "model_provider": custom_provider_id,
            f"model_providers.{custom_provider_id}.name": custom_provider_id,
            f"model_providers.{custom_provider_id}.base_url": base_url,
            f"model_providers.{custom_provider_id}.requires_openai_auth": True,
        }
        if wire_api:
            config_overrides[f"model_providers.{custom_provider_id}.wire_api"] = wire_api

    return AgentBinding(
        agent_id=agent_id,
        provider_id=profile.provider_id,
        model=model,
        api_key_env=api_key_env,
        base_url=base_url,
        wire_api=wire_api,
        codex_config_overrides=config_overrides,
    )


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


def assess_agent_compatibility(
    agent_id: str,
    which: Callable[[str], str | None] = shutil.which,
    run_command: Callable[[list[str]], CommandOutput] | None = None,
) -> AgentCompatibility:
    spec = get_agent_spec(agent_id)
    doctor = doctor_agent(agent_id, which=which, run_command=run_command)

    if doctor.status == "unavailable":
        return AgentCompatibility(
            agent_id=doctor.agent_id,
            compatibility_state="manual_only",
            control_level=doctor.control_level,
            binary_path=doctor.binary_path,
            version=doctor.version,
            capabilities={
                "non_interactive_execution": "none",
                "model_override": "none",
                "provider_override": "none",
                "config_isolation": "none",
                "working_directory_control": "none",
                "output_capture": "none",
                "timeout_control": "none",
                "cancellation_control": "none",
                "metrics_visibility": "none",
            },
            reasons=["binary_unavailable"],
            warnings=doctor.warnings,
            metrics_capability=doctor.metrics_capability,
        )

    checks = {check.name: check for check in doctor.checks}
    capabilities = {
        "non_interactive_execution": _check_level(checks["non_interactive"]),
        "model_override": _check_level(checks["model_override"]),
        "provider_override": _check_level(checks["provider_override"]),
        "config_isolation": _check_level(checks["config_isolation"]),
        "working_directory_control": _check_level(checks["working_directory"]),
        "output_capture": _check_level(checks["output_stream"], fallback="weak"),
        "timeout_control": "strong" if doctor.binary_path else "none",
        "cancellation_control": _cancellation_level(spec, doctor),
        "metrics_visibility": _metrics_visibility_level(spec),
    }

    core_capabilities = {
        "non_interactive_execution",
        "model_override",
        "provider_override",
        "config_isolation",
        "working_directory_control",
        "output_capture",
        "timeout_control",
        "cancellation_control",
    }
    reasons = [
        capability
        for capability, level in capabilities.items()
        if level != "strong"
        and capability in core_capabilities
    ]
    hard_failures = {
        "non_interactive_execution",
        "model_override",
        "working_directory_control",
    }
    if any(capabilities[name] == "none" for name in hard_failures):
        compatibility_state = "manual_only"
    elif any(capabilities[name] != "strong" for name in core_capabilities):
        compatibility_state = "limited"
    else:
        compatibility_state = "dispatchable"

    return AgentCompatibility(
        agent_id=doctor.agent_id,
        compatibility_state=compatibility_state,
        control_level=doctor.control_level,
        binary_path=doctor.binary_path,
        version=doctor.version,
        capabilities=capabilities,
        reasons=reasons,
        warnings=doctor.warnings,
        metrics_capability=doctor.metrics_capability,
    )


def list_agent_compatibility(
    which: Callable[[str], str | None] = shutil.which,
    run_command: Callable[[list[str]], CommandOutput] | None = None,
) -> list[AgentCompatibility]:
    return [
        assess_agent_compatibility(spec.agent_id, which=which, run_command=run_command)
        for spec in list_agent_specs()
    ]


def assess_dispatch_readiness(
    agent_id: str,
    workdir: Path,
    isolation_mode: str = "copy",
    *,
    which: Callable[[str], str | None] = shutil.which,
    run_command: Callable[[list[str]], CommandOutput] | None = None,
) -> DispatchReadiness:
    compatibility = assess_agent_compatibility(
        agent_id,
        which=which,
        run_command=run_command,
    )
    isolation = assess_workspace_isolation(workdir, isolation_mode=isolation_mode)
    reasons = list(compatibility.reasons)
    reasons.extend(isolation.reasons)
    warnings = [*compatibility.warnings, *isolation.warnings]

    if isolation.status != "ready":
        readiness_state = "blocked"
    elif compatibility.compatibility_state == "dispatchable":
        readiness_state = "dispatchable"
    else:
        readiness_state = "manual_only"

    return DispatchReadiness(
        agent_id=compatibility.agent_id,
        readiness_state=readiness_state,
        compatibility_state=compatibility.compatibility_state,
        control_level=compatibility.control_level,
        binary_path=compatibility.binary_path,
        version=compatibility.version,
        isolation=isolation,
        reasons=reasons,
        warnings=warnings,
        capabilities=compatibility.capabilities,
        metrics_capability=compatibility.metrics_capability,
    )


def _marker_check(name: str, markers: list[str], text: str) -> DoctorCheck:
    missing = [marker for marker in markers if marker not in text]
    return DoctorCheck(
        name=name,
        status="passed" if not missing else "failed",
        markers=markers,
        missing_markers=missing,
    )


def _check_level(check: DoctorCheck, fallback: str | None = None) -> str:
    if not check.markers:
        return fallback or "none"
    if not check.missing_markers:
        return "strong"
    if len(check.missing_markers) < len(check.markers):
        return "weak"
    return fallback or "none"


def _cancellation_level(spec: AgentSpec, doctor: DoctorResult) -> str:
    if doctor.binary_path is None:
        return "none"
    if spec.cancellation == "process_kill":
        return "strong"
    if spec.cancellation:
        return "weak"
    return "none"


def _metrics_visibility_level(spec: AgentSpec) -> str:
    token_support = spec.metrics_capability.get("token_usage")
    cost_support = spec.metrics_capability.get("cost_usage")
    if token_support in {"required", "optional"} and cost_support in {"required", "optional"}:
        return "strong" if token_support == "required" and cost_support == "required" else "weak"
    if token_support in {"required", "optional"} or cost_support in {"required", "optional"}:
        return "weak"
    return "none"


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
