from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from ..errors import ProtocolError
from ..protocol.artifacts import sha256_file


@dataclass(frozen=True)
class ProviderUsageCapture:
    assignment_id: str
    session_id: str
    agent_id: str
    provider: str
    model: str
    collected_at: str
    usage: dict[str, Any]
    source: str = "provider_usage_capture_v1"
    result_id: str | None = None
    source_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {"artifact_type": "provider_usage_capture", **self.__dict__}
        return {key: value for key, value in payload.items() if value is not None}


def load_provider_usage_capture(data: dict[str, Any]) -> ProviderUsageCapture:
    if data.get("artifact_type") != "provider_usage_capture":
        raise ProtocolError("Provider usage capture artifact_type must be provider_usage_capture")
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ProtocolError("Provider usage capture usage must be an object")
    _validate_usage(usage)
    required = ("assignment_id", "session_id", "agent_id", "provider", "model", "collected_at", "source")
    if any(not isinstance(data.get(key), str) or not data[key] for key in required):
        raise ProtocolError("Provider usage capture is missing required identity fields")
    return ProviderUsageCapture(**{key: data.get(key) for key in ProviderUsageCapture.__dataclass_fields__})


def write_provider_usage_capture_artifact(path: Path, capture: ProviderUsageCapture, *, created_by: str = "harness", source_event: str | None = None) -> dict[str, Any]:
    content = yaml.safe_dump(capture.to_dict(), sort_keys=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content:
        raise ProtocolError(f"Immutable provider usage artifact differs: {path}")
    if not path.exists():
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if sha256_file(path) != hashlib.sha256(content).hexdigest():
        raise ProtocolError(f"Provider usage artifact hash verification failed: {path}")
    artifact = {"artifact_id": f"artifact-{capture.result_id or capture.session_id}-provider-usage", "path": str(path), "sha256": sha256_file(path), "created_by": created_by, "mutable": False, "artifact_type": "provider_usage_capture"}
    if source_event is not None:
        artifact["source_event"] = source_event
    return artifact


def build_provider_usage_capture(telemetry_capture: dict[str, Any] | None, *, assignment_id: str, session_id: str, agent_id: str, result_id: str, collected_at: str) -> ProviderUsageCapture | None:
    if not isinstance(telemetry_capture, dict) or not isinstance(telemetry_capture.get("usage"), dict):
        return None
    usage = telemetry_capture["usage"]
    _validate_usage(usage)
    provider, model = telemetry_capture.get("provider"), telemetry_capture.get("model")
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        return None
    return ProviderUsageCapture(assignment_id, session_id, agent_id, provider, model, collected_at, dict(usage), result_id=result_id, source_ref=telemetry_capture.get("source_ref") if isinstance(telemetry_capture.get("source_ref"), str) else None)


def merge_provider_usage_into_outcome_metrics(outcome_metrics: dict[str, Any], capture: ProviderUsageCapture | None) -> dict[str, Any]:
    merged = dict(outcome_metrics)
    if capture is None:
        return merged
    for field in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_output_tokens", "cost_usd", "usage_confidence", "cost_source", "cost_confidence"):
        if field in capture.usage:
            merged[field] = capture.usage[field]
    merged["usage_source"] = "provider_attributed"
    if "usage_confidence" not in merged:
        merged["usage_confidence"] = "high"
    if "cost_usd" in merged:
        merged.setdefault("cost_source", "provider_attributed")
        merged.setdefault("cost_confidence", "high")
    if "total_tokens" not in merged and isinstance(merged.get("input_tokens"), int) and isinstance(merged.get("output_tokens"), int):
        merged["total_tokens"] = merged["input_tokens"] + merged["output_tokens"]
    return merged


def _validate_usage(usage: dict[str, Any]) -> None:
    allowed = {"input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_output_tokens", "cost_usd", "cost_source", "cost_confidence", "usage_confidence"}
    if set(usage) - allowed:
        raise ProtocolError("Provider usage capture usage contains unknown fields")
    for key in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_output_tokens"):
        if key in usage and (not isinstance(usage[key], int) or usage[key] < 0):
            raise ProtocolError(f"Provider usage capture {key} must be a non-negative integer")
    if "input_tokens" in usage and "output_tokens" in usage:
        total = usage["input_tokens"] + usage["output_tokens"]
        if usage.get("total_tokens") not in {None, total}:
            raise ProtocolError("Provider usage capture total_tokens must equal input_tokens + output_tokens")
        usage.setdefault("total_tokens", total)
