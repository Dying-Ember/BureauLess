from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import yaml

from ..errors import ProtocolError
from ..protocol import sha256_file


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
