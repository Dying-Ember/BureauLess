from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any

import yaml

from ..errors import ProtocolError
from ..protocol.artifacts import sha256_file


def prepare_demo_workspace(
    workspace: Path,
    *,
    include_fixture_results: bool = True,
) -> dict[str, Path]:
    source_root = _repo_root() / "examples" / "missions" / "demo"
    if not source_root.exists():
        raise ProtocolError(f"Demo mission fixture root does not exist: {source_root}")

    workspace.mkdir(parents=True, exist_ok=True)
    workflows_dir = workspace / "workflows"
    results_dir = workspace / "results"
    artifacts_dir = workspace / "artifacts"
    src_dir = workspace / "src"
    assignments_dir = workspace / "generated" / "assignments"
    sessions_dir = workspace / "generated" / "sessions"
    packaged_results_dir = workspace / "generated" / "results"
    capsules_dir = workspace / "generated" / "capsules"
    outcomes_dir = workspace / "generated" / "outcomes"
    reviews_dir = workspace / "generated" / "reviews"
    decisions_dir = workspace / "generated" / "decisions"
    telemetry_dir = workspace / "generated" / "telemetry"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    assignments_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    packaged_results_dir.mkdir(parents=True, exist_ok=True)
    capsules_dir.mkdir(parents=True, exist_ok=True)
    outcomes_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    mission_path = workspace / "mission.yaml"
    workflow_path = workflows_dir / "coder_reviewer_committer.yaml"
    ledger_path = workspace / "ledger.yaml"
    shutil.copy2(source_root / "mission.yaml", mission_path)
    shutil.copy2(source_root / "workflows" / "coder_reviewer_committer.yaml", workflow_path)
    shutil.copy2(source_root / "ledger.yaml", ledger_path)
    _write_demo_artifact(workspace / ".gitignore", ".bureauless/\ngenerated/\n")
    _write_demo_artifact(src_dir / "demo.py", "print('old')\n")
    _write_demo_artifact(
        workspace / "README.md",
        "# BureauLess Demo Workspace\n\nImplement updates `src/demo.py` from old to new.\n",
    )

    _write_demo_artifact(
        artifacts_dir / "implement_patch.diff",
        "--- a/src/demo.py\n+++ b/src/demo.py\n@@\n-print('old')\n+print('new')\n",
    )
    _write_demo_artifact(
        artifacts_dir / "review_report.md",
        "# Review Report\n\nPatch reviewed and approved.\n",
    )
    _write_demo_artifact(
        artifacts_dir / "commit_note.md",
        "# Commit Note\n\nCommit created after review approval.\n",
    )

    if include_fixture_results:
        _write_demo_result(
            results_dir / "implement_result.yaml",
            result_id="result-implement",
            assignment_id="assign-implement",
            emitted_events=["patch_ready"],
            changed_files_count=1,
            artifacts=[
                _demo_artifact_payload(
                    artifacts_dir / "implement_patch.diff",
                    artifact_id="artifact-implement-patch",
                    created_by="coder",
                    source_event="event-result-implement",
                )
            ],
        )
        _write_demo_result(
            results_dir / "review_result.yaml",
            result_id="result-review",
            assignment_id="assign-review",
            emitted_events=["review_approved"],
            changed_files_count=0,
            artifacts=[
                _demo_artifact_payload(
                    artifacts_dir / "review_report.md",
                    artifact_id="artifact-review-report",
                    created_by="reviewer",
                    source_event="event-result-review",
                )
            ],
        )
        _write_demo_result(
            results_dir / "commit_result.yaml",
            result_id="result-commit",
            assignment_id="assign-commit",
            emitted_events=["commit_created"],
            changed_files_count=1,
            artifacts=[
                _demo_artifact_payload(
                    artifacts_dir / "commit_note.md",
                    artifact_id="artifact-commit-note",
                    created_by="committer",
                    source_event="event-result-commit",
                )
            ],
        )
    _initialize_demo_git_repo(workspace)

    return {
        "mission": mission_path,
        "workflow": workflow_path,
        "ledger": ledger_path,
        "results_dir": results_dir,
        "artifacts_dir": artifacts_dir,
        "assignments_dir": assignments_dir,
        "sessions_dir": sessions_dir,
        "packaged_results_dir": packaged_results_dir,
        "capsules_dir": capsules_dir,
        "outcomes_dir": outcomes_dir,
        "reviews_dir": reviews_dir,
        "decisions_dir": decisions_dir,
        "telemetry_dir": telemetry_dir,
    }


def load_artifact_session_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProtocolError("Artifact session manifest YAML must be an object")

    manifest = dict(payload)
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
        "routing_decision_path",
        "advisor_gate_decision_path",
        "advisor_gate_outcome_path",
        "metrics_summary_path",
        "workbench_url",
    ):
        _require_string(manifest, field, "Artifact session manifest")

    _require_string_list(manifest, "ready", "Artifact session manifest")
    _require_bool(manifest, "terminal_complete", "Artifact session manifest")
    _require_optional_mapping(manifest, "failure", "Artifact session manifest")
    _require_string_mapping(manifest, "node_states", "Artifact session manifest")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise ProtocolError("Artifact session manifest field 'steps' must be a list of objects")

    for index, step in enumerate(steps):
        _validate_artifact_manifest_step(step, index=index)

    manifest["manifest_path"] = str(path)
    return manifest


def _initialize_demo_git_repo(workspace: Path) -> None:
    git_dir = workspace / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    subprocess.run(
        ["git", "init"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "BureauLess Demo"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "demo@bureauless.local"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initialize demo workspace"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_demo_result(
    path: Path,
    *,
    result_id: str,
    assignment_id: str,
    emitted_events: list[str],
    changed_files_count: int,
    artifacts: list[dict[str, str]],
) -> None:
    payload = {
        "result_id": result_id,
        "assignment_id": assignment_id,
        "agent_id": "manual-demo-worker",
        "status": "completed",
        "emitted_events": emitted_events,
        "artifacts": artifacts,
        "outcome_metrics": {
            "wall_time_ms": 1000,
            "changed_files_count": changed_files_count,
            "usage_confidence": "none",
        },
        "verification": {"status": "passed"},
        "native_log_refs": [],
    }
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def _write_demo_artifact(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


def _demo_artifact_payload(
    path: Path,
    *,
    artifact_id: str,
    created_by: str,
    source_event: str,
) -> dict[str, str | bool]:
    return {
        "artifact_id": artifact_id,
        "path": f"artifacts/{path.name}" if path.parent.name == "artifacts" else str(path),
        "sha256": sha256_file(path),
        "created_by": created_by,
        "source_event": source_event,
        "mutable": False,
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _validate_artifact_manifest_step(step: dict[str, Any], *, index: int) -> None:
    prefix = f"Artifact session manifest steps[{index}]"
    for field in (
        "node_id",
        "assignment_path",
        "context_capsule_path",
        "session_path",
        "record_status",
        "node_state_after",
    ):
        _require_string(step, field, prefix)
    _require_string_list(step, "ready_after", prefix)
    _require_optional_string(step, "context_request_path", prefix)

    if step["record_status"] == "completed":
        for field in (
            "result_path",
            "node_outcome_path",
            "review_decision_path",
            "turn_report_path",
            "dispatch_packet_path",
        ):
            _require_string(step, field, prefix)
    else:
        _require_optional_string(step, "failure_reason", prefix)


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


def _require_optional_mapping(
    data: dict[str, Any],
    field: str,
    prefix: str,
) -> dict[str, Any] | None:
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
