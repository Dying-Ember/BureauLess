from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from ..errors import ProtocolError
from ..protocol.artifacts import sha256_file
from ..protocol.dispatch import DispatchPacket


OPTIONAL_TOP_LEVEL_PATHS = (
    "routing_decision_path",
    "advisor_gate_decision_path",
    "advisor_gate_outcome_path",
    "metrics_summary_path",
)
OPTIONAL_STEP_PATHS = (
    "context_request_path",
    "context_resolution_path",
    "result_path",
    "node_outcome_path",
    "review_decision_path",
)
REQUIRED_STEP_PATHS = (
    "assignment_path",
    "context_capsule_path",
    "session_path",
    "turn_report_path",
    "dispatch_packet_path",
)


def write_run_bundle(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    existing_revision = 0
    existing_bundle_id: str | None = None
    if path.is_file():
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            if isinstance(existing.get("bundle_revision"), int):
                existing_revision = existing["bundle_revision"]
            if isinstance(existing.get("bundle_id"), str) and existing["bundle_id"]:
                existing_bundle_id = existing["bundle_id"]
    normalized.setdefault("schema_version", 1)
    if existing_bundle_id is not None:
        normalized["bundle_id"] = existing_bundle_id
    else:
        normalized.setdefault("bundle_id", f"run-bundle-{uuid4()}")
    normalized["bundle_revision"] = existing_revision + 1
    normalized["generated_at"] = datetime.now(timezone.utc).isoformat()
    for field in OPTIONAL_TOP_LEVEL_PATHS:
        normalized.setdefault(field, None)
    steps = normalized.get("steps", [])
    if isinstance(steps, list):
        normalized["steps"] = [
            _normalize_step(step) if isinstance(step, dict) else step for step in steps
        ]
    normalized["artifact_index"] = _build_artifact_index(normalized)
    validate_run_bundle(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(normalized, handle, sort_keys=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {**normalized, "manifest_path": str(path)}


def load_run_bundle(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProtocolError("Artifact session manifest YAML must be an object")
    validate_run_bundle(payload)
    _verify_artifact_index(payload)
    return {**payload, "manifest_path": str(path)}


def write_session_run_bundle(
    path: Path,
    *,
    mission_path: Path,
    workflow_path: Path,
    ledger_path: Path,
    dispatch_packet_path: Path,
    session_record_path: Path,
    packet: DispatchPacket,
    record: dict[str, Any],
    workspace: Path,
    ready: list[str] | None = None,
    node_states: dict[str, str] | None = None,
) -> dict[str, Any]:
    artifact_dir = path.parent / f"{path.stem}_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    assignment_path = artifact_dir / "assignment.yaml"
    capsule_path = artifact_dir / "context_capsule.yaml"
    routing_path = artifact_dir / "routing_decision.yaml"
    turn_report_path = artifact_dir / "turn_report.yaml"
    _write_yaml(assignment_path, packet.assignment.to_dict())
    capsule = packet.assignment.visible_context.get("context_capsule", {})
    _write_yaml(capsule_path, capsule if isinstance(capsule, dict) else {})
    _write_yaml(routing_path, packet.routing_decision.to_dict())
    extraction = record.get("extraction", {})
    reports = extraction.get("turn_reports", []) if isinstance(extraction, dict) else []
    if not isinstance(reports, list) or not reports or not isinstance(reports[-1], dict):
        raise ProtocolError("Session run bundle requires runtime turn-report evidence")
    _write_yaml(turn_report_path, reports[-1])

    context_request_path: Path | None = None
    context_resolution_path: Path | None = None
    context_entries = extraction.get("context_requests", []) if isinstance(extraction, dict) else []
    if isinstance(context_entries, list) and context_entries and isinstance(context_entries[0], dict):
        request = context_entries[0].get("request")
        resolution = context_entries[0].get("resolution")
        if isinstance(request, dict):
            context_request_path = artifact_dir / "context_request.yaml"
            _write_yaml(context_request_path, request)
        if isinstance(resolution, dict):
            context_resolution_path = artifact_dir / "context_resolution.yaml"
            _write_yaml(context_resolution_path, resolution)

    dispatch = record.get("dispatch", {})
    session_spec = dispatch.get("session_spec", {}) if isinstance(dispatch, dict) else {}
    result = record.get("result_proposal", {})
    target_model = _first_string(
        session_spec.get("target_model") if isinstance(session_spec, dict) else None,
        result.get("effective_model") if isinstance(result, dict) else None,
        "unknown",
    )
    target_provider = _first_string(
        session_spec.get("target_provider") if isinstance(session_spec, dict) else None,
        result.get("effective_provider") if isinstance(result, dict) else None,
        "unknown",
    )
    node_state = (node_states or {}).get(packet.assignment.node_id, "session_completed_unstaged")
    step = {
        "node_id": packet.assignment.node_id,
        "assignment_path": str(assignment_path),
        "context_capsule_path": str(capsule_path),
        "context_request_path": str(context_request_path) if context_request_path else None,
        "context_resolution_path": (
            str(context_resolution_path) if context_resolution_path else None
        ),
        "session_path": str(session_record_path),
        "result_path": None,
        "node_outcome_path": None,
        "review_decision_path": None,
        "turn_report_path": str(turn_report_path),
        "dispatch_packet_path": str(dispatch_packet_path),
        "record_status": _first_string(record.get("status"), "unknown"),
        "failure_reason": (
            None
            if record.get("status") == "completed"
            else _first_string(
                record.get("exit", {}).get("reason")
                if isinstance(record.get("exit"), dict)
                else None,
                "unknown",
            )
        ),
        "ready_after": ready or [],
        "node_state_after": node_state,
    }
    return write_run_bundle(
        path,
        {
            "milestone": "runtime-milestone-3.5",
            "flow_id": "maintained-session-dispatch",
            "workspace": str(workspace.resolve()),
            "mission_path": str(mission_path),
            "workflow_path": str(workflow_path),
            "ledger_path": str(ledger_path),
            "agent": _first_string(record.get("agent_id"), "unknown"),
            "target_model": target_model,
            "target_provider": target_provider,
            "routing_decision_path": str(routing_path),
            "advisor_gate_decision_path": None,
            "advisor_gate_outcome_path": None,
            "metrics_summary_path": str(session_record_path),
            "workbench_url": f"http://127.0.0.1:5173/?artifact_manifest_path={path}",
            "steps": [step],
            "failure": (
                None
                if record.get("status") == "completed"
                else {
                    "node_id": packet.assignment.node_id,
                    "session_id": record.get("session_id"),
                    "status": record.get("status"),
                    "reason": step["failure_reason"],
                    "session_path": str(session_record_path),
                }
            ),
            "terminal_complete": False,
            "ready": ready or [],
            "node_states": node_states or {packet.assignment.node_id: node_state},
        },
    )


def validate_run_bundle(manifest: dict[str, Any]) -> None:
    for field in (
        "milestone",
        "flow_id",
        "workspace",
        "mission_path",
        "workflow_path",
        "ledger_path",
        "agent",
        "target_model",
        "target_provider",
        "workbench_url",
    ):
        _require_string(manifest, field, "Artifact session manifest")
    if manifest.get("schema_version", 1) != 1:
        raise ProtocolError("Artifact session manifest schema_version must be 1")
    revision = manifest.get("bundle_revision", 1)
    if not isinstance(revision, int) or revision < 1:
        raise ProtocolError("Artifact session manifest bundle_revision must be >= 1")
    for field in OPTIONAL_TOP_LEVEL_PATHS:
        _require_optional_string(manifest, field, "Artifact session manifest")
    _require_string_list(manifest, "ready", "Artifact session manifest")
    _require_bool(manifest, "terminal_complete", "Artifact session manifest")
    _require_optional_mapping(manifest, "failure", "Artifact session manifest")
    _require_string_mapping(manifest, "node_states", "Artifact session manifest")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise ProtocolError("Artifact session manifest field 'steps' must be a list of objects")
    for index, step in enumerate(steps):
        _validate_step(step, index=index)
    artifact_index = manifest.get("artifact_index", [])
    if not isinstance(artifact_index, list) or not all(
        isinstance(item, dict) for item in artifact_index
    ):
        raise ProtocolError("Artifact session manifest artifact_index must be a list")


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(step)
    for field in OPTIONAL_STEP_PATHS:
        normalized.setdefault(field, None)
    return normalized


def _validate_step(step: dict[str, Any], *, index: int) -> None:
    prefix = f"Artifact session manifest steps[{index}]"
    for field in ("node_id", "record_status", "node_state_after", *REQUIRED_STEP_PATHS):
        _require_string(step, field, prefix)
    _require_string_list(step, "ready_after", prefix)
    for field in OPTIONAL_STEP_PATHS:
        _require_optional_string(step, field, prefix)
    _require_optional_string(step, "failure_reason", prefix)
    attempts = step.get("attempts")
    if attempts is not None:
        if not isinstance(attempts, list) or not all(
            isinstance(attempt, dict) for attempt in attempts
        ):
            raise ProtocolError(f"{prefix} field 'attempts' must be a list of objects")
        for attempt_index, attempt in enumerate(attempts):
            attempt_prefix = f"{prefix}.attempts[{attempt_index}]"
            for field in (
                "session_id",
                "record_status",
                *REQUIRED_STEP_PATHS,
            ):
                _require_string(attempt, field, attempt_prefix)
            _require_optional_string(attempt, "protocol_error", attempt_prefix)


def _build_artifact_index(manifest: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[tuple[str, str]] = []
    for field in OPTIONAL_TOP_LEVEL_PATHS:
        value = manifest.get(field)
        if isinstance(value, str) and value:
            refs.append((field, value))
    for index, step in enumerate(manifest.get("steps", [])):
        if not isinstance(step, dict):
            continue
        for field in (*REQUIRED_STEP_PATHS, *OPTIONAL_STEP_PATHS):
            value = step.get(field)
            if isinstance(value, str) and value:
                refs.append((f"steps[{index}].{field}", value))
        for attempt_index, attempt in enumerate(step.get("attempts", [])):
            if not isinstance(attempt, dict):
                continue
            for field in REQUIRED_STEP_PATHS:
                value = attempt.get(field)
                if isinstance(value, str) and value:
                    refs.append(
                        (f"steps[{index}].attempts[{attempt_index}].{field}", value)
                    )
    result = []
    for field, value in refs:
        artifact_path = Path(value)
        if artifact_path.is_file():
            result.append(
                {"field": field, "path": value, "sha256": sha256_file(artifact_path)}
            )
    return result


def _verify_artifact_index(manifest: dict[str, Any]) -> None:
    for item in manifest.get("artifact_index", []):
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ProtocolError("Run bundle artifact index entries require path and sha256")
        artifact_path = Path(path)
        if not artifact_path.is_file():
            raise ProtocolError(f"Run bundle indexed artifact does not exist: {path}")
        if sha256_file(artifact_path) != digest:
            raise ProtocolError(f"Run bundle indexed artifact hash mismatch: {path}")


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def _first_string(*values: Any) -> str:
    return next((value for value in values if isinstance(value, str) and value), "unknown")


def _require_string(data: dict[str, Any], field: str, prefix: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{prefix} field {field!r} must be a non-empty string")
    return value


def _require_optional_string(data: dict[str, Any], field: str, prefix: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{prefix} field {field!r} must be a non-empty string when present")
    return value


def _require_bool(data: dict[str, Any], field: str, prefix: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ProtocolError(f"{prefix} field {field!r} must be boolean")
    return value


def _require_string_list(data: dict[str, Any], field: str, prefix: str) -> list[str]:
    value = data.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProtocolError(f"{prefix} field {field!r} must be a list of non-empty strings")
    return value


def _require_optional_mapping(data: dict[str, Any], field: str, prefix: str) -> dict[str, Any] | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProtocolError(f"{prefix} field {field!r} must be an object when present")
    return value


def _require_string_mapping(data: dict[str, Any], field: str, prefix: str) -> dict[str, str]:
    value = data.get(field)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key and isinstance(item, str) and item
        for key, item in value.items()
    ):
        raise ProtocolError(f"{prefix} field {field!r} must be an object of non-empty strings")
    return value
