from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any

from .core import ProtocolError


@dataclass(frozen=True)
class WorkspaceReadiness:
    status: str
    requested_mode: str
    effective_mode: str | None
    source_root: str
    reasons: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "requested_mode": self.requested_mode,
            "source_root": self.source_root,
            "reasons": self.reasons,
            "warnings": self.warnings,
        }
        if self.effective_mode is not None:
            payload["effective_mode"] = self.effective_mode
        return payload


def assess_workspace_isolation(
    workdir: Path,
    isolation_mode: str = "copy",
) -> WorkspaceReadiness:
    if isolation_mode not in {"copy", "worktree"}:
        raise ProtocolError(f"Unsupported isolation_mode: {isolation_mode}")

    source_root = workdir.resolve()
    reasons: list[str] = []
    warnings: list[str] = []

    if not source_root.exists():
        reasons.append("source_root_missing")
    elif not source_root.is_dir():
        reasons.append("source_root_not_directory")

    if reasons:
        return WorkspaceReadiness(
            status="blocked",
            requested_mode=isolation_mode,
            effective_mode=None,
            source_root=str(source_root),
            reasons=reasons,
            warnings=warnings,
        )

    if isolation_mode == "copy":
        return WorkspaceReadiness(
            status="ready",
            requested_mode="copy",
            effective_mode="copy",
            source_root=str(source_root),
            reasons=[],
            warnings=[],
        )

    worktree_result = probe_git_worktree(source_root)
    if not worktree_result["ok"]:
        return WorkspaceReadiness(
            status="blocked",
            requested_mode="worktree",
            effective_mode=None,
            source_root=str(source_root),
            reasons=["worktree_unavailable"],
            warnings=_string_list_value(worktree_result.get("warnings")),
        )

    return WorkspaceReadiness(
        status="ready",
        requested_mode="worktree",
        effective_mode="worktree",
        source_root=str(source_root),
        reasons=[],
        warnings=[],
    )


def probe_git_worktree(source_root: Path) -> dict[str, Any]:
    env = git_environment(source_root)
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=source_root,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except OSError as exc:
        return {"ok": False, "warnings": [str(exc)]}

    if probe.returncode != 0:
        return {"ok": False, "warnings": ["worktree mode unavailable outside a git repository"]}
    return {"ok": True, "warnings": []}


def git_environment(source_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    git_local = source_root / ".git-local"
    if git_local.exists():
        env["GIT_DIR"] = str(git_local)
        env["GIT_WORK_TREE"] = str(source_root)
    return env


def _string_list_value(value: Any) -> list[str]:
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []
