from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import yaml

from ..errors import ProtocolError
from .assignments import AssignmentPacket
from .harness import Ledger


@dataclass(frozen=True)
class ContextRequest:
    context_request_id: str
    assignment_id: str
    missing_information: str
    requested_refs: list[str]
    expected_value: str
    continuation_id: str | None = None
    session_id: str | None = None
    request_index: int | None = None
    requested_at: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "context_request_id": self.context_request_id,
            "assignment_id": self.assignment_id,
            "missing_information": self.missing_information,
            "requested_refs": self.requested_refs,
            "expected_value": self.expected_value,
        }
        for field in (
            "continuation_id",
            "session_id",
            "request_index",
            "requested_at",
            "expires_at",
        ):
            value = getattr(self, field)
            if value is not None:
                payload[field] = value
        return payload


@dataclass(frozen=True)
class ContextRequestIntent:
    missing_information: str
    requested_refs: list[str]
    expected_value: str


@dataclass(frozen=True)
class ContextRequestResolution:
    context_request_id: str
    assignment_id: str
    status: str
    policy_version: str
    granted_artifacts: list[dict[str, Any]]
    denied_refs: list[dict[str, str]]
    unavailable_refs: list[dict[str, str]]
    added_tokens_estimate: int
    continuation_id: str | None = None
    session_id: str | None = None
    request_index: int | None = None
    resolved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "context_request_id": self.context_request_id,
            "assignment_id": self.assignment_id,
            "status": self.status,
            "policy_version": self.policy_version,
            "granted_artifacts": self.granted_artifacts,
            "denied_refs": self.denied_refs,
            "unavailable_refs": self.unavailable_refs,
            "added_tokens_estimate": self.added_tokens_estimate,
        }
        for field in ("continuation_id", "session_id", "request_index", "resolved_at"):
            value = getattr(self, field)
            if value is not None:
                payload[field] = value
        return payload


def load_context_request(data: dict[str, Any]) -> ContextRequest:
    return ContextRequest(
        context_request_id=_as_string(data, "context_request_id"),
        assignment_id=_as_string(data, "assignment_id"),
        missing_information=_as_string(data, "missing_information"),
        requested_refs=_as_string_list(data, "requested_refs"),
        expected_value=_as_string(data, "expected_value"),
        continuation_id=_as_optional_string(data.get("continuation_id")),
        session_id=_as_optional_string(data.get("session_id")),
        request_index=_as_optional_positive_int(data.get("request_index")),
        requested_at=_as_optional_string(data.get("requested_at")),
        expires_at=_as_optional_string(data.get("expires_at")),
    )


def load_context_request_intent(data: dict[str, Any]) -> ContextRequestIntent:
    unknown = sorted(set(data) - {"missing_information", "requested_refs", "expected_value"})
    if unknown:
        raise ProtocolError(f"Context request intent has unknown fields: {', '.join(unknown)}")
    return ContextRequestIntent(
        missing_information=_as_string(data, "missing_information"),
        requested_refs=_as_string_list(data, "requested_refs"),
        expected_value=_as_string(data, "expected_value"),
    )


def build_context_request(
    intent: ContextRequestIntent,
    *,
    assignment_id: str,
    session_id: str,
    continuation_id: str,
    request_index: int,
    now: datetime | None = None,
    ttl_seconds: int = 300,
) -> ContextRequest:
    if request_index < 1:
        raise ProtocolError("Context request_index must be >= 1")
    if ttl_seconds < 1:
        raise ProtocolError("Context request ttl_seconds must be >= 1")
    requested_at = now or datetime.now(timezone.utc)
    expires_at = requested_at + timedelta(seconds=ttl_seconds)
    return ContextRequest(
        context_request_id=f"ctxreq-{continuation_id}-{request_index}",
        assignment_id=assignment_id,
        missing_information=intent.missing_information,
        requested_refs=list(intent.requested_refs),
        expected_value=intent.expected_value,
        continuation_id=continuation_id,
        session_id=session_id,
        request_index=request_index,
        requested_at=requested_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )


def resolve_context_request(
    assignment: AssignmentPacket,
    ledger: Ledger,
    request: ContextRequest,
    *,
    max_artifacts: int = 1,
    max_added_tokens: int | None = None,
    now: datetime | None = None,
) -> ContextRequestResolution:
    if request.assignment_id != assignment.assignment_id:
        raise ProtocolError(
            "Context request assignment_id does not match the target assignment"
        )
    if max_artifacts < 1:
        raise ProtocolError("max_artifacts must be at least 1")
    resolved_at = now or datetime.now(timezone.utc)
    if request.expires_at is not None and resolved_at > _parse_datetime(request.expires_at):
        return ContextRequestResolution(
            context_request_id=request.context_request_id,
            assignment_id=request.assignment_id,
            status="expired",
            policy_version=_assignment_policy_version(assignment),
            granted_artifacts=[],
            denied_refs=[],
            unavailable_refs=[],
            added_tokens_estimate=0,
            continuation_id=request.continuation_id,
            session_id=request.session_id,
            request_index=request.request_index,
            resolved_at=resolved_at.isoformat(),
        )

    allowed_refs = _allowed_artifacts(assignment.artifact_refs)
    artifact_records = _ledger_artifacts(ledger.artifacts)
    granted_artifacts: list[dict[str, Any]] = []
    denied_refs: list[dict[str, str]] = []
    unavailable_refs: list[dict[str, str]] = []

    for ref in request.requested_refs:
        allowed = allowed_refs.get(ref)
        if allowed is None:
            denied_refs.append(
                {"requested_ref": ref, "reason": "not_in_assignment_scope"}
            )
            continue
        if len(granted_artifacts) >= max_artifacts:
            denied_refs.append(
                {"requested_ref": ref, "reason": "artifact_budget_exceeded"}
            )
            continue
        materialized = _materialize_allowed_artifact(allowed, artifact_records)
        if materialized is None:
            unavailable_refs.append(
                {"requested_ref": ref, "reason": "artifact_payload_unavailable"}
            )
            continue
        granted_artifacts.append(materialized)

    status = _resolution_status(granted_artifacts, denied_refs, unavailable_refs)
    policy_version = _assignment_policy_version(assignment)
    added_tokens_estimate = sum(
        max(1, len(yaml.safe_dump(item, sort_keys=True)) // 4)
        for item in granted_artifacts
    )
    if max_added_tokens is not None and added_tokens_estimate > max_added_tokens:
        denied_refs.extend(
            {
                "requested_ref": _artifact_identity(artifact),
                "reason": "context_token_budget_exceeded",
            }
            for artifact in granted_artifacts
        )
        granted_artifacts = []
        status = "budget_exceeded"
        added_tokens_estimate = 0
    return ContextRequestResolution(
        context_request_id=request.context_request_id,
        assignment_id=request.assignment_id,
        status=status,
        policy_version=policy_version,
        granted_artifacts=granted_artifacts,
        denied_refs=denied_refs,
        unavailable_refs=unavailable_refs,
        added_tokens_estimate=added_tokens_estimate,
        continuation_id=request.continuation_id,
        session_id=request.session_id,
        request_index=request.request_index,
        resolved_at=resolved_at.isoformat() if request.continuation_id is not None else None,
    )


def build_context_lifecycle_events(
    request: ContextRequest,
    resolution: ContextRequestResolution,
    *,
    mission_id: str,
    workflow_id: str,
    node_id: str,
    role: str,
    resumed: bool,
) -> list[dict[str, Any]]:
    request_event_id = f"event-{request.context_request_id}-requested"
    resolution_event_id = f"event-{request.context_request_id}-resolved"
    common = {
        "mission_id": mission_id,
        "workflow_id": workflow_id,
        "assignment_id": request.assignment_id,
        "node_id": node_id,
        "role": role,
        "session_id": request.session_id,
        "continuation_id": request.continuation_id,
        "context_request_id": request.context_request_id,
        "request_index": request.request_index,
    }
    events = [
        {
            **common,
            "event_id": request_event_id,
            "event_type": "context_requested",
            "request": request.to_dict(),
            "created_at": request.requested_at,
        },
        {
            **common,
            "event_id": resolution_event_id,
            "event_type": "context_resolved",
            "source_event_id": request_event_id,
            "resolution": resolution.to_dict(),
            "status": resolution.status,
            "created_at": resolution.resolved_at,
        },
    ]
    if resumed:
        events.append(
            {
                **common,
                "event_id": f"event-{request.context_request_id}-resumed",
                "event_type": "context_resumed",
                "source_event_id": resolution_event_id,
                "created_at": resolution.resolved_at,
            }
        )
    return events


def _allowed_artifacts(artifact_refs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    allowed: dict[str, dict[str, Any]] = {}
    for artifact in artifact_refs:
        if not isinstance(artifact, dict):
            continue
        for key in ("artifact_id", "path", "ref"):
            value = artifact.get(key)
            if isinstance(value, str) and value:
                allowed[value] = artifact
    return allowed


def _ledger_artifacts(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        for key in ("artifact_id", "path"):
            value = artifact.get(key)
            if isinstance(value, str) and value:
                records[value] = artifact
    return records


def _materialize_allowed_artifact(
    allowed: dict[str, Any],
    artifact_records: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for key in ("artifact_id", "path"):
        value = allowed.get(key)
        if isinstance(value, str) and value:
            artifact = artifact_records.get(value)
            if artifact is not None:
                return dict(artifact)
    return None


def _resolution_status(
    granted_artifacts: list[dict[str, Any]],
    denied_refs: list[dict[str, str]],
    unavailable_refs: list[dict[str, str]],
) -> str:
    if granted_artifacts and not denied_refs and not unavailable_refs:
        return "granted"
    if granted_artifacts:
        return "partially_granted"
    if denied_refs and not unavailable_refs:
        return "denied"
    return "unavailable"


def _assignment_policy_version(assignment: AssignmentPacket) -> str:
    visible_context = assignment.visible_context
    capsule = visible_context.get("context_capsule")
    if isinstance(capsule, dict):
        policy_version = capsule.get("policy_version")
        if isinstance(policy_version, str) and policy_version:
            return policy_version
    return "unknown"


def _artifact_identity(artifact: dict[str, Any]) -> str:
    for field in ("artifact_id", "path", "ref"):
        value = artifact.get(field)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("Context request expires_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProtocolError("Context request expires_at must include timezone")
    return parsed


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Context request field {key!r} must be a non-empty string")
    return value


def _as_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProtocolError(f"Context request field {key!r} must be a list of strings")
    return value


def _as_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProtocolError("Optional context request fields must be non-empty strings")
    return value


def _as_optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 1:
        raise ProtocolError("Context request request_index must be >= 1")
    return value
