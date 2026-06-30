from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from ..core import ProtocolError
from .assignments import AssignmentPacket
from .harness import Ledger


@dataclass(frozen=True)
class ContextRequest:
    context_request_id: str
    assignment_id: str
    missing_information: str
    requested_refs: list[str]
    expected_value: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_request_id": self.context_request_id,
            "assignment_id": self.assignment_id,
            "missing_information": self.missing_information,
            "requested_refs": self.requested_refs,
            "expected_value": self.expected_value,
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_request_id": self.context_request_id,
            "assignment_id": self.assignment_id,
            "status": self.status,
            "policy_version": self.policy_version,
            "granted_artifacts": self.granted_artifacts,
            "denied_refs": self.denied_refs,
            "unavailable_refs": self.unavailable_refs,
            "added_tokens_estimate": self.added_tokens_estimate,
        }


def load_context_request(data: dict[str, Any]) -> ContextRequest:
    return ContextRequest(
        context_request_id=_as_string(data, "context_request_id"),
        assignment_id=_as_string(data, "assignment_id"),
        missing_information=_as_string(data, "missing_information"),
        requested_refs=_as_string_list(data, "requested_refs"),
        expected_value=_as_string(data, "expected_value"),
    )


def resolve_context_request(
    assignment: AssignmentPacket,
    ledger: Ledger,
    request: ContextRequest,
    *,
    max_artifacts: int = 1,
) -> ContextRequestResolution:
    if request.assignment_id != assignment.assignment_id:
        raise ProtocolError(
            "Context request assignment_id does not match the target assignment"
        )
    if max_artifacts < 1:
        raise ProtocolError("max_artifacts must be at least 1")

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
    return ContextRequestResolution(
        context_request_id=request.context_request_id,
        assignment_id=request.assignment_id,
        status=status,
        policy_version=policy_version,
        granted_artifacts=granted_artifacts,
        denied_refs=denied_refs,
        unavailable_refs=unavailable_refs,
        added_tokens_estimate=added_tokens_estimate,
    )


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
