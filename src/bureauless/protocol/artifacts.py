from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..core import ProtocolError
from .harness import Ledger


@dataclass(frozen=True)
class ArtifactVerification:
    artifact_id: str
    path: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "path": self.path,
            "status": self.status,
            "message": self.message,
        }


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_artifact_record(record: dict[str, Any], root: Path) -> ArtifactVerification:
    artifact_id = _required_string(record, "artifact_id")
    artifact_path = _required_string(record, "path")
    expected_hash = _required_string(record, "sha256")
    _required_string(record, "created_by")
    _required_string(record, "source_event")

    if record.get("mutable") is not False:
        raise ProtocolError(f"Accepted artifact {artifact_id} must have mutable: false")

    path = (root / artifact_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ProtocolError(f"Artifact {artifact_id} path escapes artifact root") from exc

    if not path.exists():
        return ArtifactVerification(
            artifact_id=artifact_id,
            path=artifact_path,
            status="missing",
            message="Artifact file is missing",
        )

    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        return ArtifactVerification(
            artifact_id=artifact_id,
            path=artifact_path,
            status="invalid",
            message="Artifact sha256 does not match ledger record",
        )

    return ArtifactVerification(
        artifact_id=artifact_id,
        path=artifact_path,
        status="valid",
        message="Artifact hash matches ledger record",
    )


def verify_ledger_artifacts(ledger: Ledger, root: Path) -> list[ArtifactVerification]:
    return [validate_artifact_record(record, root) for record in ledger.artifacts]


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"Artifact field {key!r} must be a non-empty string")
    return value
